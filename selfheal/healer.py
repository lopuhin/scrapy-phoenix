"""Hold → pause → agent → gate → hot-load → resume (``docs/DESIGN.md`` §6).

A Scrapy extension, off unless ``SELFHEAL_ENABLED`` is set. When a
:class:`~selfheal.spider.SelfHealingSpider` page is refused by every variant,
the spider hands it here instead of dropping it:

1. The page is held (saved under ``repairs/<id>/held/``) and the engine
   paused. Responses already in flight still go through their callbacks; any
   that are refused too join the held set.
2. A coding agent (harness-run, Codex, ``acceptEdits``, scrapy-mcp attached)
   writes one new variant module in the spider's ``variants/`` package.
3. The gate (``python -m selfheal.gate``) runs as a subprocess. On failure the
   agent gets the gate output and one more try.
4. On success the module is hot-loaded through Remote Control, every held
   request is re-queued, and the engine unpaused. On failure the new files
   are removed and the spider closes with ``repair_failed``.

Settings: ``SELFHEAL_ENABLED``, ``SELFHEAL_MODEL`` (``gpt-5.6-luna``),
``SELFHEAL_REASONING_EFFORT`` (``medium``), ``SELFHEAL_BUDGET_USD`` (3),
``SELFHEAL_MAX_TURNS`` (80), ``SELFHEAL_AGENT_TIMEOUT`` (seconds, 900),
``SELFHEAL_MAX_REPAIRS`` (3), ``SELFHEAL_HELD_PAGES`` (20),
``SELFHEAL_CANARY`` (10), ``SELFHEAL_REPAIRS_DIR`` (``repairs``).
"""

from __future__ import annotations

import asyncio
import difflib
import json
import logging
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import aiohttp
import pydantic
from scrapy import Request, signals
from scrapy.exceptions import NotConfigured
from scrapy.http import Response
from web_poet.utils import get_fq_class_name

from .dispatch import Unrecognized
from .gate import save_held, tracked_files

logger = logging.getLogger(__name__)

ROOT = Path.cwd()


class RepairProposal(pydantic.BaseModel):
    """What the agent reports at the end of a repair attempt."""

    model_config = pydantic.ConfigDict(extra="forbid")

    kind: Literal["variant", "give_up"]
    module: str = pydantic.Field(description="dotted module of the new variant, or ''")
    class_names: list[str]
    summary: str = pydantic.Field(description="what changed on the site, what the variant does")
    confidence: Literal["high", "medium", "low"]
    evidence: str = pydantic.Field(description="how you checked it, incl. the gate result")


PROMPT = """\
# Repair a Scrapy spider whose target site changed

The spider `{spider}` is crawling right now, and it is **paused**: {n_held} page(s)
were refused by every page object it has, so it yielded nothing from them. Your
job is to add **one new page object module** so those pages are extracted
correctly, then the crawl resumes with it.

## What the spider wants

Read `{readme}` (intent, in prose) and `{items}` (hard checks every item must
pass; you may not change them).

## What was refused

Item type: `{item_type}`. Held pages (body + JSON with URL and evidence) are in
`{held}/`. The evidence from the first page, closest variant first:

```
{evidence}
```

## How variants work here

- Page objects live in `{variants_dir}/`, one module per site layout. Read the
  existing ones; they are the style to follow. Modules are never edited: a new
  layout gets a new module.
- They use `selfheal.strict.StrictMixin`: `self.must(css)` / `self.must_text(css)`
  for anything the layout must have (they raise `LayoutMismatch` when it is
  missing, which is how a page is refused), and `may`/`may_text` for things
  that are legitimately optional on some pages. Only `must` what you extract.
- A new variant is tried *before* the old ones. On a page of an old layout it
  must raise (refuse) or produce exactly the same item, so be strict.

## What to do

1. Write `{module_file}` (module `{module}`) with a page object for
   `{item_type}`. Do not edit or create any other file.
2. Check it with the gate, which is exactly what will decide whether it is
   loaded:

       {gate_cmd}

   It checks: only that file was added; existing fixtures still pass; the new
   class doesn't take over other variants' fixture pages; every held page is
   extracted and passes the item checks; values vary across pages.
3. Look at the extracted items yourself too: are they *right*, per the README?
   Passing checks is necessary, not sufficient.

The live crawl is reachable through the scrapy-mcp tools (job pid {pid}); you
may inspect it, but do not change its state: the healer loads your module.
Your shell has no network access.

If the pages cannot be extracted in a way that meets the intent (e.g. data the
README requires is not on the page at all), do not force it: answer with
`kind: "give_up"` and explain why.

Finish with the structured result: `module` = `{module}`, the class names you
defined, a short summary of what changed on the site, your confidence, and the
gate result as evidence.
"""


@dataclass
class Repair:
    id: str
    dir: Path
    item_cls: type
    started: float = field(default_factory=time.monotonic)
    held: list[Request] = field(default_factory=list)
    saved: int = 0
    trigger: dict[str, Any] = field(default_factory=dict)
    task: asyncio.Task | None = None
    metrics: dict[str, Any] = field(default_factory=dict)


class Healer:
    def __init__(self, crawler) -> None:
        settings = crawler.settings
        if not settings.getbool("SELFHEAL_ENABLED"):
            raise NotConfigured
        self.crawler = crawler
        self.model = settings.get("SELFHEAL_MODEL", "gpt-5.6-luna")
        self.reasoning_effort = settings.get("SELFHEAL_REASONING_EFFORT", "medium")
        self.budget_usd = settings.getfloat("SELFHEAL_BUDGET_USD", 3.0)
        self.max_turns = settings.getint("SELFHEAL_MAX_TURNS", 80)
        self.agent_timeout = settings.getfloat("SELFHEAL_AGENT_TIMEOUT", 900)
        self.max_repairs = settings.getint("SELFHEAL_MAX_REPAIRS", 3)
        self.max_held_pages = settings.getint("SELFHEAL_HELD_PAGES", 20)
        self.canary_size = settings.getint("SELFHEAL_CANARY", 10)
        self.repairs_dir = ROOT / settings.get("SELFHEAL_REPAIRS_DIR", "repairs")
        self.repairs: list[Repair] = []
        self.active: Repair | None = None
        self.failed = False
        self.spider = None
        crawler.signals.connect(self.spider_opened, signals.spider_opened)
        crawler.signals.connect(self.spider_closed, signals.spider_closed)

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler)

    def spider_opened(self, spider) -> None:
        self.spider = spider
        spider.healer = self

    # -- hold ---------------------------------------------------------------------

    def hold(self, exc: Unrecognized, response: Response) -> None:
        """Keep a refused page for the repair; pause and start one if none is running."""
        if self.failed:
            return
        request = response.request
        repair = self.active
        if repair is None:
            if len(self.repairs) >= self.max_repairs:
                logger.error("selfheal: repair limit (%d) reached", self.max_repairs)
                self._fail(None, "repair limit reached")
                return
            repair = self._start(exc, response)
        repair.held.append(request)
        self.crawler.stats.inc_value("selfheal/held")
        item_type = get_fq_class_name(exc.item_cls)
        if repair.saved < self.max_held_pages:
            headers = {k.decode(): [v.decode() for v in vs]
                       for k, vs in response.headers.items()}
            save_held(repair.dir / "held", repair.saved, response.url, response.status,
                      headers, response.body, item_type, str(exc))
            repair.saved += 1

    def _start(self, exc: Unrecognized, response: Response) -> Repair:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        repair_id = f"{stamp}-{len(self.repairs) + 1}"
        repair = Repair(repair_id, self.repairs_dir / repair_id, exc.item_cls)
        repair.dir.mkdir(parents=True)
        first = exc.refusals[0] if exc.refusals else None
        repair.trigger = {
            "url": response.url,
            "item_type": exc.item_cls.__name__,
            "variant": first and first.variant,
            "field": first and first.field,
            "selector": first and first.selector,
            "error": first and first.error,
        }
        self.repairs.append(repair)
        self.active = repair
        self.crawler.engine.pause()
        logger.warning("selfheal: paused; repair %s for %s", repair_id, response.url)
        repair.task = asyncio.create_task(self._repair(repair))
        return repair

    # -- repair -------------------------------------------------------------------

    async def _repair(self, repair: Repair) -> None:
        m = repair.metrics
        m["trigger"] = repair.trigger
        try:
            await self._drain()
            baseline = tracked_files(ROOT)
            (repair.dir / "baseline.json").write_text(json.dumps(baseline))
            module = self._next_module(repair.item_cls)
            gate_cmd = self._gate_cmd(repair, module)
            prompt = self._prompt(repair, module, gate_cmd)
            (repair.dir / "prompt.md").write_text(prompt)
            m["pages_held_at_start"] = repair.saved

            proposal, gate = None, None
            async with self._agent(repair) as agent:
                message = prompt
                for attempt in (1, 2):
                    proposal = await agent.turn(message)
                    if proposal is None or proposal.kind == "give_up":
                        break
                    gate = await self._run_gate(repair, gate_cmd, final=True)
                    m[f"gate_attempt_{attempt}"] = gate["ok"]
                    if gate["ok"]:
                        break
                    message = (
                        "The gate failed when the healer ran it:\n\n```\n"
                        + gate["output"][-6000:]
                        + "\n```\nFix the module (same file) and run the gate again."
                    )
                m |= agent.totals()

            (repair.dir / "proposal.json").write_text(
                proposal.model_dump_json(indent=1) if proposal else "null"
            )
            m["diff_lines"] = self._write_diff(repair, baseline)
            if proposal is None:
                return self._fail(repair, "agent returned no proposal")
            if proposal.kind == "give_up":
                return self._fail(repair, f"agent gave up: {proposal.summary}")
            if not gate or not gate["ok"]:
                return self._fail(repair, "gate failed after retry")
            if proposal.confidence == "low":
                return self._fail(repair, "agent confidence is low")
            m["loaded"] = await self._hotload(module)
            self._resume(repair, "repaired")
            asyncio.create_task(self._canary(repair, m["loaded"]))
        except Exception as exc:
            logger.exception("selfheal: repair %s crashed", repair.id)
            self._fail(repair, f"healer error: {exc!r}")

    async def _drain(self, timeout: float = 30) -> None:
        """Let responses already in flight reach their callbacks (more held pages)."""
        engine = self.crawler.engine
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not engine.downloader.active and engine.scraper.slot.is_idle():
                return
            await asyncio.sleep(0.1)

    def _next_module(self, item_cls: type) -> str:
        """``<package>.<prefix>_v<N+1>``, prefix taken from existing modules of that type."""
        variants = self.spider.variants
        package = self.spider.variants_package
        modules = {c.__module__.rpartition(".")[2] for c in variants.for_item(item_cls)}
        prefixes = {re.sub(r"_v\d+(_\d+)?$", "", m) for m in modules}
        prefix = min(prefixes) if prefixes else item_cls.__name__.lower()
        pkg_dir = ROOT / package.replace(".", "/")
        taken = [int(n) for p in pkg_dir.glob(f"{prefix}_v*.py")
                 for n in re.findall(rf"^{prefix}_v(\d+)", p.stem)]
        return f"{package}.{prefix}_v{max(taken, default=0) + 1}"

    def _gate_cmd(self, repair: Repair, module: str, json_out: str | None = None) -> str:
        rel = repair.dir.relative_to(ROOT)
        cmd = (f"{_python()} -m selfheal.gate --spider {self.spider.name} --candidate {module} "
               f"--held {rel}/held --baseline {rel}/baseline.json")
        return cmd + (f" --json {json_out}" if json_out else "")

    def _prompt(self, repair: Repair, module: str, gate_cmd: str) -> str:
        package = self.spider.variants_package
        pkg_root = package.split(".")[0]
        evidence = json.loads(sorted((repair.dir / "held").glob("*.json"))[0].read_text())
        return PROMPT.format(
            spider=self.spider.name,
            n_held=len(repair.held),
            readme=f"{pkg_root}/README.md",
            items=f"{pkg_root}/items.py",
            item_type=get_fq_class_name(repair.item_cls),
            held=repair.dir.relative_to(ROOT) / "held",
            evidence=evidence["evidence"],
            variants_dir=package.replace(".", "/"),
            module=module,
            module_file=module.replace(".", "/") + ".py",
            gate_cmd=gate_cmd,
            pid=os.getpid(),
        )

    def _agent(self, repair: Repair) -> _AgentSession:
        return _AgentSession(self, repair)

    async def _run_gate(self, repair: Repair, gate_cmd: str, final: bool) -> dict:
        rel = repair.dir.relative_to(ROOT)
        cmd = gate_cmd.split()[1:]  # drop "python": use our interpreter
        cmd += ["--json", f"{rel}/gate.json"]
        if final:
            cmd += ["--save-fixtures", f"{rel}/fixtures"]
        started = time.monotonic()
        proc = await asyncio.create_subprocess_exec(
            sys.executable, *cmd, cwd=ROOT,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await proc.communicate()
        result = {"ok": proc.returncode == 0, "output": out.decode(errors="replace"),
                  "seconds": round(time.monotonic() - started, 1)}
        logger.info("selfheal: gate %s\n%s", "passed" if result["ok"] else "failed",
                    result["output"])
        return result

    def _write_diff(self, repair: Repair, baseline: dict[str, str]) -> int:
        from .gate import changed_files

        added, changed = changed_files(ROOT, baseline)
        chunks = []
        for rel in added:
            if rel.startswith(str(self.repairs_dir.relative_to(ROOT))):
                continue
            text = (ROOT / rel).read_text(errors="replace").splitlines(keepends=True)
            chunks += difflib.unified_diff([], text, "/dev/null", f"b/{rel}")
        chunks += [f"# modified or deleted (not shown): {rel}\n" for rel in changed]
        (repair.dir / "diff.patch").write_text("".join(chunks))
        return sum(1 for line in chunks if line.startswith("+") and not line.startswith("+++"))

    # -- hot-load + resume ---------------------------------------------------------

    async def _hotload(self, module: str) -> list[str]:
        """Import ``module`` in the crawl and register its page objects via Remote Control."""
        code = (
            "import importlib, json\n"
            "importlib.invalidate_caches()\n"
            f"m = importlib.import_module({module!r})\n"
            "added = crawler.spider.variants.register_module(m)\n"
            "print(json.dumps([c.__qualname__ for c in added]))\n"
        )
        job = self._job_file()
        async with aiohttp.ClientSession() as http:
            async with http.post(
                f"http://127.0.0.1:{job['port']}/execute",
                json={"code": code},
                headers={"Authorization": f"Bearer {job['token']}"},
            ) as r:
                result = await r.json()
        if result.get("status") != "ok":
            raise RuntimeError(f"hot-load failed: {result}")
        loaded = json.loads(result["output"])
        logger.warning("selfheal: hot-loaded %s: %s; variants now %s", module, loaded,
                       self.spider.variants.describe())
        return loaded

    def _job_file(self) -> dict:
        from scrapy.extensions.remote_control import RemoteControl

        for ext in self.crawler.extensions.middlewares:
            if isinstance(ext, RemoteControl) and ext._job_file_path:
                return json.loads(ext._job_file_path.read_text())
        raise RuntimeError("Remote Control is not running (REMOTE_CONTROL_ENABLED?)")

    def _resume(self, repair: Repair, outcome: str) -> None:
        engine = self.crawler.engine
        for request in repair.held:
            engine.crawl(request.replace(dont_filter=True))
        engine.unpause()
        m = repair.metrics
        m["outcome"] = outcome
        m["requests_redownloaded"] = len(repair.held)
        m["paused_s"] = round(time.monotonic() - repair.started, 1)
        self.active = None
        self._record(repair)
        logger.warning("selfheal: resumed after %ss; re-queued %d held request(s)",
                       m["paused_s"], len(repair.held))

    async def _canary(self, repair: Repair, loaded: list[str]) -> None:
        """Watch the next pages of this type: are they routed to the new variant?"""
        stats = self.crawler.stats
        refused_key = f"selfheal/unrecognized/{repair.item_cls.__name__}"
        before = {name: stats.get_value(f"selfheal/variant/{name}", 0) for name in loaded}
        refused_before = stats.get_value(refused_key, 0)
        while self.crawler.crawling:
            routed = sum(stats.get_value(f"selfheal/variant/{n}", 0) - before[n] for n in loaded)
            refused = stats.get_value(refused_key, 0) - refused_before
            repair.metrics["canary"] = {"k": self.canary_size, "routed": routed,
                                        "refused": refused}
            if routed >= self.canary_size or refused:
                break
            await asyncio.sleep(0.2)
        self._record(repair)

    # -- failure ----------------------------------------------------------------------

    def _fail(self, repair: Repair | None, reason: str) -> None:
        self.failed = True
        logger.error("selfheal: repair failed: %s", reason)
        if repair is not None:
            baseline = json.loads((repair.dir / "baseline.json").read_text()) \
                if (repair.dir / "baseline.json").exists() else None
            if baseline is not None:
                self._rollback(baseline)
            repair.metrics["outcome"] = "failed"
            repair.metrics["reason"] = reason
            repair.metrics["paused_s"] = round(time.monotonic() - repair.started, 1)
            (repair.dir / "report.md").write_text(self._report(repair, reason))
            self._record(repair)
        self.crawler.stats.set_value("selfheal/failed", reason)
        self.crawler.engine.unpause()
        asyncio.create_task(self.crawler.engine.close_spider_async(reason="repair_failed"))

    def _rollback(self, baseline: dict[str, str]) -> None:
        """Remove files the agent added; restore tracked files it changed."""
        from .gate import changed_files

        added, changed = changed_files(ROOT, baseline)
        repairs_rel = str(self.repairs_dir.relative_to(ROOT))
        for rel in added:
            if not rel.startswith(repairs_rel):
                (ROOT / rel).unlink(missing_ok=True)
                logger.warning("selfheal: rolled back %s", rel)
        if changed:
            subprocess.run(["git", "checkout", "--", *changed], cwd=ROOT, check=False)
            logger.warning("selfheal: restored %s", changed)

    def _report(self, repair: Repair, reason: str) -> str:
        proposal = repair.dir / "proposal.json"
        gate = repair.dir / "gate.json"
        lines = [
            f"# Repair {repair.id} failed",
            "",
            f"**Reason:** {reason}",
            "",
            f"Trigger: `{json.dumps(repair.trigger)}`",
            "",
            f"Held pages: {len(repair.held)} (saved: {repair.saved}) in `held/`.",
            "",
        ]
        if proposal.exists():
            lines += ["## Agent proposal", "", "```json", proposal.read_text(), "```", ""]
        if gate.exists():
            lines += ["## Last gate run", "", "```json", gate.read_text(), "```", ""]
        return "\n".join(lines)

    def _record(self, repair: Repair) -> None:
        m = dict(repair.metrics, id=repair.id)
        (repair.dir / "metrics.json").write_text(json.dumps(m, indent=1, default=str))
        index = self.repairs_dir / "index.jsonl"
        rows = [json.loads(l) for l in index.read_text().splitlines()] if index.exists() else []
        rows = [r for r in rows if r.get("id") != repair.id] + [m]
        index.write_text("".join(json.dumps(r, default=str) + "\n" for r in rows))

    def spider_closed(self, spider, reason) -> None:
        repair = self.active
        if repair is not None and repair.task and not repair.task.done():
            # e.g. CLOSESPIDER_TIMEOUT fired mid-repair: stop the agent, undo its files.
            logger.error("selfheal: spider closed (%s) during repair %s", reason, repair.id)
            repair.task.cancel()
            baseline = repair.dir / "baseline.json"
            if baseline.exists():
                self._rollback(json.loads(baseline.read_text()))
            repair.metrics |= {"outcome": "interrupted", "reason": reason}
            self._record(repair)
        self.crawler.stats.set_value("selfheal/repairs", len(self.repairs))


class _AgentSession:
    """One harness-run Codex session per repair; ``turn()`` runs one message."""

    def __init__(self, healer: Healer, repair: Repair) -> None:
        self.healer = healer
        self.repair = repair
        self.events = (repair.dir / "events.jsonl").open("w")
        self.cost = 0.0
        self.turns = 0
        self.usage: list[Any] = []
        self.wall = 0.0
        self.started = False

    async def __aenter__(self) -> _AgentSession:
        from harness_run import AgentSpec, McpServer, local

        h = self.healer
        spec = AgentSpec(
            name="scrapy-phoenix-healer",
            harness="codex",
            model=h.model,
            reasoning_effort=h.reasoning_effort,
            permission_mode="acceptEdits",
            max_turns=h.max_turns,
            max_budget_usd=h.budget_usd,
            output_schema=RepairProposal,
            checkpoint=True,  # the retry continues the same conversation
            mcp_servers=[McpServer.stdio(
                "scrapy", "uvx", ["--from", "scrapy-mcp-official", "scrapy-mcp"])],
            codex_config={"mcp_servers.scrapy.default_tools_approval_mode": "approve"},
        )
        engine = local.deploy(spec, workspace=str(ROOT),
                              workdir=str(h.repairs_dir / ".harness"))
        self.session = engine.start_session()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        self.events.close()

    async def turn(self, message: str) -> RepairProposal | None:
        started = time.monotonic()
        run = self.session.send(message) if self.started else self.session.run(message)
        self.started = True
        try:
            await asyncio.wait_for(self._stream(run), self.healer.agent_timeout)
        except TimeoutError:
            self._event("healer", f"wall-clock timeout ({self.healer.agent_timeout}s)")
            await self.session.interrupt()
            return None
        finally:
            self.wall += time.monotonic() - started
        result = run.result
        self.cost += result.cost_usd or 0
        self.turns += result.num_turns or 0
        self.usage.append(result.usage)
        if result.is_error:
            self._event("healer", f"run error: {result.text}")
        out = result.structured_output
        if isinstance(out, dict):
            out = RepairProposal.model_validate(out)
        return out

    async def _stream(self, run) -> None:
        async for event in run:
            self._event(event.kind, event.summary or "")

    def _event(self, kind: str, summary: str) -> None:
        row = {"t": round(time.monotonic() - self.repair.started, 2), "kind": kind,
               "summary": summary[:2000]}
        self.events.write(json.dumps(row) + "\n")
        self.events.flush()
        if kind in ("tool_use", "message", "status", "healer"):
            logger.info("selfheal agent [%s] %s", kind, " ".join(summary.split())[:200])

    def totals(self) -> dict[str, Any]:
        return {"agent_wall_s": round(self.wall, 1), "cost_usd": round(self.cost, 4),
                "num_turns": self.turns, "usage": [_plain(u) for u in self.usage]}


def _python() -> str:
    """The interpreter to show the agent: relative when it is the project's venv."""
    exe = Path(sys.executable)
    try:
        return str(exe.relative_to(ROOT))
    except ValueError:
        return str(exe)


def _plain(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "__dataclass_fields__"):
        from dataclasses import asdict

        return asdict(value)
    return value
