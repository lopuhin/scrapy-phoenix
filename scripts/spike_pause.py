"""Step-2 spike: run a coding agent inside a paused crawl, then resume it.

Usage: python scripts/spike_pause.py [--hold-after 20] [--model gpt-5.6-luna]
                                      [--codex-config JSON]

Crawls the sandbox store in its default layout. After ``--hold-after``
products, the next product page is *held* as if no variant recognised it: the
engine is paused and a harness-run Codex session (``acceptEdits``, scrapy-mcp
attached) runs on the crawl's own event loop. When it finishes, the held
request is re-queued and the engine unpaused. Nothing is repaired; the point
is to check the plumbing:

- the agent session does not block the loop (heartbeat lag stays small),
- in-flight responses are still processed while paused,
- Remote Control answers during the session (we poll ``/status`` ourselves,
  and the agent reaches it through scrapy-mcp from inside Codex's sandbox),
- re-queue + unpause resumes the same run and nothing is lost (566 items).

Writes ``output/spike/timeline.jsonl`` and ``output/spike/report.json``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from pathlib import Path

import aiohttp
import pydantic
import scrapy
from harness_run import AgentSpec, McpServer, SystemPrompt, local
from scrapy import signals
from scrapy.crawler import AsyncCrawlerProcess
from scrapy.utils.project import get_project_settings

from sandbox_spider.spider import SandboxStoreSpider

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "output" / "spike"


class SpikeReport(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid")

    job_found: bool
    job_id: str
    engine_paused: bool
    scheduler_size: int
    items_scraped: int
    held_urls: list[str]
    curl_sandbox: str
    workspace_write: str
    outside_write: str
    notes: str


PROMPT = """\
This is a plumbing test, not a repair. A Scrapy crawl (pid {pid}) is paused and
waiting for you. Do each step, then report.

1. With the scrapy-mcp tools, list the jobs and find the one with pid {pid}.
2. In that job, execute this code and note what it prints:
       e = crawler.engine
       print(e.paused, len(e._slot.scheduler),
             crawler.stats.get_value("item_scraped_count"),
             [r.url for r in crawler.spider.held])
3. In your shell, run:
       curl -s -o /dev/null -w '%{{http_code}}' http://127.0.0.1:8765/sandbox-store/
   and report the output or the error (curl_sandbox).
4. In your shell, write the word ok to output/spike/agent_note.txt in the
   current directory (workspace_write: "ok" or the error).
5. In your shell, try `touch {outside}` (outside_write: "ok" or the error).
6. Run `sleep 20` in your shell, then repeat step 2 once.

Do not edit any other file. Report the first step-2 output in the fields, and
anything surprising in notes.
"""


class SpikeSpider(SandboxStoreSpider):
    name = "spike_pause"

    def __init__(self, *args, hold_after: int = 20, model: str = "gpt-5.6-luna",
                 codex_config: str = "{}", **kwargs):
        super().__init__(*args, **kwargs)
        self.hold_after = int(hold_after)
        self.model = model
        self.codex_config = json.loads(codex_config)
        self.held: list[scrapy.Request] = []
        self.timeline = (OUT / "timeline.jsonl").open("w")
        self.report: dict = {}
        self._repair: asyncio.Task | None = None
        self._t0 = time.monotonic()

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super().from_crawler(crawler, *args, **kwargs)
        crawler.signals.connect(spider._opened, signals.spider_opened)
        crawler.signals.connect(spider._response, signals.response_received)
        return spider

    def log_event(self, kind: str, **data) -> None:
        engine = self.crawler.engine
        row = {
            "t": round(time.monotonic() - self._t0, 3),
            "kind": kind,
            "paused": engine.paused,
            "items": self.crawler.stats.get_value("item_scraped_count", 0),
            "in_flight": len(engine.downloader.active),
            **data,
        }
        self.timeline.write(json.dumps(row) + "\n")
        self.timeline.flush()

    def _opened(self, spider):
        self._heartbeat = asyncio.create_task(self.heartbeat())

    def _response(self, response, request, spider):
        if self.crawler.engine.paused:
            self.log_event("response_while_paused", url=response.url)

    async def heartbeat(self) -> None:
        """Loop lag every 0.5 s, plus our own Remote Control ``/status`` call."""
        job = await self._job_file()
        headers = {"Authorization": f"Bearer {job['token']}"}
        url = f"http://127.0.0.1:{job['port']}/status"
        async with aiohttp.ClientSession() as http:
            while True:
                start = time.monotonic()
                await asyncio.sleep(0.5)
                lag = time.monotonic() - start - 0.5
                if self.crawler.engine.paused:
                    t = time.monotonic()
                    async with http.get(url, headers=headers) as r:
                        ok = r.status == 200
                    self.log_event("heartbeat", lag=round(lag, 4), rc_status=ok,
                                   rc_ms=round((time.monotonic() - t) * 1000, 1))
                elif lag > 0.1:
                    self.log_event("heartbeat_lag", lag=round(lag, 4))

    async def _job_file(self) -> dict:
        jobs = Path(os.path.expanduser("~/.local/state/scrapy/job_files"))
        for _ in range(50):
            for path in jobs.glob(f"{os.getpid()}-*.json"):
                return json.loads(path.read_text())
            await asyncio.sleep(0.1)
        raise RuntimeError("no Remote Control job file")

    async def parse_product(self, response):
        scraped = self.crawler.stats.get_value("item_scraped_count", 0)
        if self._repair is None and scraped >= self.hold_after:
            self.hold(response.request)
            return
        if self._repair is not None and not self._repair.done():
            self.log_event("callback_while_paused", url=response.url)
        async for item in super().parse_product(response):
            yield item

    def hold(self, request: scrapy.Request) -> None:
        self.held.append(request)
        self.crawler.engine.pause()
        self.log_event("hold", url=request.url)
        self._repair = asyncio.create_task(self.repair())

    async def repair(self) -> None:
        started = time.monotonic()
        outside = Path.home() / ".scrapy-phoenix-spike-outside"
        spec = AgentSpec(
            name="scrapy-phoenix-spike",
            harness="codex",
            model=self.model,
            reasoning_effort="low",
            permission_mode="acceptEdits",
            max_turns=30,
            max_budget_usd=1.0,
            output_schema=SpikeReport,
            codex_config=self.codex_config,
            system_prompt=SystemPrompt.inherit(append="Be brief."),
            mcp_servers=[
                McpServer.stdio(
                    "scrapy", "uvx", ["--from", "scrapy-mcp-official", "scrapy-mcp"]
                )
            ],
        )
        engine = local.deploy(spec, workspace=str(ROOT))
        session = engine.start_session()
        run = session.run(PROMPT.format(pid=os.getpid(), outside=outside))
        self.log_event("agent_start")
        try:
            async for event in run:
                self.log_event(f"agent_{event.kind}", summary=(event.summary or "")[:300])
            result = run.result
            self.report = {
                "structured": result.structured_output,
                "text": result.text,
                "cost_usd": result.cost_usd,
                "turns": result.num_turns,
                "is_error": result.is_error,
            }
        except Exception as exc:  # report and resume regardless
            self.report = {"error": repr(exc)}
        self.report["agent_seconds"] = round(time.monotonic() - started, 1)
        self.report["outside_file_exists"] = outside.exists()
        outside.unlink(missing_ok=True)
        self.resume()

    def resume(self) -> None:
        engine = self.crawler.engine
        for request in self.held:
            engine.crawl(request.replace(dont_filter=True))
        engine.unpause()
        self.log_event("resume", requeued=len(self.held))

    def closed(self, reason):
        super().closed(reason)
        self._heartbeat.cancel()
        self.log_event("closed", reason=reason)
        self.timeline.close()
        stats = self.crawler.stats
        self.report["final_items"] = stats.get_value("item_scraped_count", 0)
        self.report["finish_reason"] = reason
        self.report["held"] = [r.url for r in self.held]
        (OUT / "report.json").write_text(json.dumps(self.report, indent=2, default=str))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--hold-after", type=int, default=20)
    parser.add_argument("--model", default="gpt-5.6-luna")
    parser.add_argument("--codex-config", default="{}", help="JSON: dotted key → value")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "agent_note.txt").unlink(missing_ok=True)
    settings = get_project_settings()
    settings.set("FEEDS", {str(OUT / "items.jsonl"): {"format": "jsonlines", "overwrite": True}})
    process = AsyncCrawlerProcess(settings)
    process.crawl(SpikeSpider, hold_after=args.hold_after, model=args.model,
                  codex_config=args.codex_config)
    process.start()


if __name__ == "__main__":
    main()
