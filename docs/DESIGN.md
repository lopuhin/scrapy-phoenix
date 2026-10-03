# Design: self-modifying spider (phase 0 + phase 1 outline)

Status: draft, second pass after review.

**Goal.** A Scrapy spider that notices, while running, that the site has drifted
(new layout, pagination gone, a navigation dead end). It then pauses, runs a
coding agent *inside the same process* to repair its own code, validates and
hot-loads the repair, and resumes **the same run**. Fixed intent, mutable
implementation. The prototype supports a conference talk. Out of scope:
external monitoring, coordinating parallel jobs, ban handling, hardening
against prompt injection, and cold start (we assume a human approved a first
correct run).

Facts marked *(verified)* were confirmed by running code against the installed
versions; the rest are from reading source.

Versions: Scrapy 2.19.0 (asyncio reactor) · scrapy-poet 0.27.2 · web-poet 0.24.1 ·
zyte-common-items 0.29.0 · harness-run 0.4.0 (Codex, `gpt-5.6-luna`). We may fork
web-poet or related libraries if the design needs changes there (§4.1).

---

## 1. Shape in one picture

```
            ┌──────────────────────────── one Scrapy process ────────────────────────────┐
 response → │ callback ─► dispatch: try variants newest→oldest: page.to_item()           │
            │               │ one succeeds + item check ok     │ all raise / check fails  │
            │               ▼                                  ▼                          │
            │           yield item / requests         healer.hold(request, evidence)     │
            │                                         (nothing yielded)                  │
            │                                           │ first hold → engine.pause()    │
            │                                           ▼                                │
            │                                  repair task (asyncio)                     │
            │                                   ├ harness-run session (Codex)            │
            │                                   │   edits variants/ in place,           │
            │                                   │   inspects crawl via scrapy-mcp ──┐    │
            │                                   ├ validation gate (subprocess)      │    │
            │                                   ├ hot-load via Remote Control ──────┤    │
            │                                   └ re-enqueue held requests          │    │
            │                                     (dont_filter) + unpause           │    │
            │  Remote Control ext (127.0.0.1, bearer token) ◄────────────────────────┘    │
            └────────────────────────────────────────────────────────────────────────────┘
```

**Resume by re-downloading.** A page that no variant can handle is not parsed and
yields nothing. The spider saves it as evidence for the agent and holds its
*request*. After the repair is hot-loaded, the held requests go back into the
scheduler with `dont_filter=True`, and the normal callback handles them with the new
code. There is a single code path for "parse a page", no callbacks kept waiting in
memory, and no out-of-band item injection. The cost is re-downloading tens of pages.

## 2. Repository layout

```
selfheal/                 # the framework — agent may NOT edit
  strict.py               # must()/may(), LayoutMismatch
  dispatch.py             # variant registry + content-based routing
  healer.py               # Scrapy extension: hold / pause / agent / hot-load / resume / record
  gate.py                 # validation gate (run in a subprocess)
sandbox_spider/           # the case study
  README.md               # intent, in prose: what we want from this site and why
  spider.py               # thin spider: callbacks call dispatch
  items.py                # item class + item checks (ordinary code, not agent-editable)
  variants/               # ◄ agent-editable: one module per variant
    product_v1.py         #   ProductPage subclasses
    navigation_v1.py      #   ProductNavigationPage subclasses
  fixtures/               # web-poet fixtures per variant (regression only)
repairs/<ts>-<id>/        # one dir per repair attempt (record, see §9)
scripts/drift.py          # flip sandbox layout on cue
scripts/run_demo.py       # runs the crawl, maps finish_reason → exit code
```

"Fixed intent, mutable implementation" in repo terms: `README.md` + `items.py` +
`selfheal/` are the intent, and `variants/` is the implementation.

## 3. Test target: the sandbox

We run `zyte-monitoring-sandbox` locally (Python 3.12, `uvicorn app.main:app` from
its repo root). The drift script uses `POST /admin/update` (form data; **all fields
required**, so read the current config first) and `POST /admin/reset`. Changes take
effect on the next request, mid-crawl, with no restart. `AB_TEST_SEED` and `BAN_SEED`
are the exception: they are read only at import. We can add layouts to the sandbox
(our team's repo) when a case needs them.

| Case | Sandbox config | Breaks | Notes |
|---|---|---|---|
| A layout | `ACTIVE_LAYOUT=default`, `AB_TEST_TARGET=products`, `AB_TEST_RATIO=1.0`, `AB_TEST_LAYOUT=modern` | product page only | Default listings with modern product pages. A ratio <1.0 gives **mixed** layouts, which tests V1 and V2 running side by side. |
| B navigation | `ACTIVE_LAYOUT=infinite_scroll` (or `load_more`) | listing: no `.pagination`, `?page>1` ignored, JS pulls `/partials/products?category_id&page` | Product pages unchanged. Fix = new navigation variant using the partials endpoint. |
| C unsafe | new sandbox layout `no_price` (to add) | price nowhere | `hidden_price` becomes a "harder repair" once variants may make extra requests (D1). |

`layout_modern` for all pages gives A+B at once: a stretch demo. `/data/product/{id}`
exposes ground truth, which is useful for scoring our own tests. The agent must not
see it.

## 4. Detection (problem A)

All detection is one mechanism: **a page object raises when the page isn't what it
was written for.** There is no separate recognizer, expectation record or anchor list.

### 4.1 Strict extraction

Each variant is an ordinary web-poet page object (`zyte_common_items.ProductPage` /
`ProductNavigationPage` subclass with `@field` methods). In phase 0 its only
dependency is `response`, which lets us build it by hand for dispatch and gating
*(verified)*. Page objects are built in one place (`dispatch.build_page`), so extra
dependencies (`HttpClient`, …) can be added there later.

```python
from selfheal.strict import StrictMixin   # must() / may()

class ProductPageV1(StrictMixin, ProductPage):
    @field
    def name(self) -> str:
        return self.must(".product-info h1::text")          # raises if absent

    @field
    def price(self) -> str:
        return parse_price(self.must(".price-tag .current-price::text, .price-tag::text"))

    @field
    def aggregateRating(self) -> AggregateRating | None:
        block = self.must(".product-rating")               # container always there…
        if (v := block.css(".rating-text::text").get()) is None:
            return None                                    # …value legitimately optional
        return AggregateRating(ratingValue=float(v), bestRating=5.0)
```

- `must(sel)` returns the non-empty result or raises
  `LayoutMismatch(page, field, selector, url)`. `may(sel)` is plain `css().get()`.
- The author decides **where the selector is**: `must` for structure this layout
  guarantees, `may` for content that varies. The usual pattern is `must` the
  container and `may` the value inside it.
- **Any exception** from `to_item()` means "not this variant" (`AttributeError` on
  `None`, a price that doesn't parse, …). `LayoutMismatch` only gives the best
  evidence. Spiders written the usual way still get detection, with worse evidence.
  This is how Scrapy code already fails when a layout changes. We make it deliberate
  and catch it before the item leaves.
- **Only `must` what you extract with.** An anchor that no extraction uses
  (e.g. a scroll trigger) only adds false positives on harmless drift. This was
  found in the breakage matrix (FINDINGS step 1b), and it is a rule for the
  agent's prompt too.
- Candidate for a web-poet fork: field-aware errors (the field name gets attached
  automatically), or `@field(required=True)` so that a field returning `None` raises
  without an explicit `must`.

### 4.2 Dispatch and the two gates before any yield

Dispatch tries variants newest → oldest and calls `to_item()`. The first to succeed
wins, and if all raise the request is held. The cost is one extra extraction per
older variant, which is negligible next to a download.

1. **Structural:** some variant's extraction completes.
2. **Item check:** the item passes `items.check_item` (ordinary code next to the item
   class: required fields present, price > 0, …). This catches a forgotten `must`,
   "selector matched but meaning moved", and bugs in new variants.

Either failure → hold, don't yield. This is how we meet "never yield an item from an
unrecognised page". Drift that only touches `may` content is not caught per page. We
accept that: an explicit anchor list would duplicate selectors and drift out of sync
with extraction.

Normal page-to-page variation (discount or not, out of stock, no rating, a listing
with a single page) must pass both gates. The baseline fixtures cover each case on
purpose (§8). They are the false-positive test set, and where a wrongly placed `must`
shows up. We use no threshold at first: the cost of a false positive is one pause and one
agent run.

### 4.3 Navigation

A navigation variant is a `ProductNavigationPage`: product links (`items`), `nextPage`,
`subCategories`. It is dispatched the same way. The hard part is that **"no next
link" is normally the last page, not an error**. So the principle is:

> A navigation variant must **positively establish** that a page is the last one.
> The absence of a next link is never evidence on its own.

How a variant establishes it depends on what the site renders:

1. **A pagination widget is always rendered**, even for single-page listings (often
   with a disabled "next"). This is the common case, and the sandbox default layout
   does it (`.pagination` with `a.active` even on one page). The variant does
   `must(".pagination a.active")`, and "last page" means "active number == highest
   number". `infinite_scroll` has no `.pagination`, so it raises on the first listing
   page, which is where the drift happens.
2. **No widget on single-page listings, but a result count** ("57 products") →
   `must` the count and derive the page count from it.
3. **Nothing on the page says how many pages there are** → the variant **probes**: it
   requests `?page=N+1` blindly. The check then moves to the next response, and the
   expectation travels with the request in `cb_kwargs` (a hash of the previous page's
   product URLs). On the probed page:
   - new products → continue;
   - empty result / 404 → a proven last page, a normal end;
   - **the same products as the previous page**, or a redirect to page 1 → the
     parameter is being ignored. `NavigationMismatch` is raised on that page. This
     is exactly what the sandbox `infinite_scroll` does with `?page=2`.

   The framework runs the repeat check in dispatch for navigation pages, so every
   variant gets it.

All three cases now have a working spider: `sandbox_store` (case 1),
`sandbox_modern` and `books` (case 2), and `sandbox_scroll` (case 3, probing).
See `docs/FINDINGS.md`.

What stays undetectable per page: a site with no widget and no count, whose variant
neither probes nor proves the last page. That would fail silently. The principle above
rules it out when a variant is written, and the gate enforces it for new variants.
Without it, only a comparison with a previous run could catch it (talk point:
this is where in-process detection is weaker than aggregate monitoring).

### 4.4 Why the spider must be written differently (talk point)

This works only because:

- extraction is split into small, swappable variants;
- variants fail loudly instead of returning partial items;
- navigation is an explicit page type that has to *prove* where the site ends, not
  `CrawlSpider` rules that silently follow whatever links exist;
- the intent (README + item checks) is separate from the code that implements it.

The existing `sandbox_store` spider has none of this.

## 5. Routing and hot-swap

**Routing does not use scrapy-poet rules.** The injector copies its registry at
startup, and rules match URL only *(verified)*. `selfheal.dispatch.Variants` is an
ordered list per page type, and callbacks dispatch by content. web-poet is still
used for page-object base classes, `HttpResponse`, fixtures and the pytest plugin.

**A repair is a new module, never a reload.** `importlib.reload` leaves stale class
identities and duplicate rules *(verified)*. The agent writes
`variants/product_v2.py`, and a fix to an existing variant becomes
`product_v2_1.py`. The healer imports it and appends it to `Variants`. Old variants
stay: "add, don't overwrite", and sites that revert are covered.

A new variant is tried first, so on old-layout fixtures it must **raise** or produce
the **same output**. Otherwise it would take over pages the old variants handle and
extract them differently (gate check, §7).

### 5.1 Hot-load through Remote Control

Remote Control is on by default. It is an aiohttp server on `127.0.0.1:<random>` with
a bearer token, and its port and token are in a 0600 job file at
`~/.local/state/scrapy/job_files/<pid>-<uuid>.json`. `POST /execute {code}` runs code
**on the crawl's own asyncio loop**. `crawler` and a persistent `stash` are in scope,
top-level `await` is allowed, and `print()` is the only output channel.

The healer applies the patch with a fixed snippet:

```python
import importlib
importlib.invalidate_caches()
m = importlib.import_module("sandbox_spider.variants.product_v2")
added = crawler.spider.variants.register_module(m)
print(json.dumps([c.__qualname__ for c in added]))
```

The healer is in-process, so a direct call would work too. We use Remote Control
because it is the same channel the agent uses to inspect the crawl, it is the hook
the "beside" mode would use, and it makes code entering the process an auditable
boundary.

**The agent has scrapy-mcp from phase 0.** It runs as a stdio MCP server in the
`AgentSpec` and finds the job through the Remote Control job file (same host by
construction). The agent sees live state: queue, held requests, stats, current
`Variants`. It can try a candidate against real crawler objects and fetch fresh pages
through the crawl itself. The healer is the only thing that hot-loads, and only after
the gate. Every agent `execute` call is in `events.jsonl`. This is enforced by the
prompt in phase 0; a read-only scrapy-mcp mode is possible hardening.

## 6. Repair and resume (problem B)

### 6.1 Sequence

1. Callback: dispatch fails → `healer.hold(request, evidence)`. The response body and
   headers are saved to `repairs/<id>/held/` (web-poet `HttpResponse` form, capped at
   ~20 pages; beyond that only the request is kept). The callback yields nothing and
   returns.
2. On the **first** hold, the healer calls `crawler.engine.pause()` and starts the
   repair task on the loop. Later holds (other in-flight responses) just add to the
   held set.
3. While paused, nothing is taken from the scheduler. In-flight downloads finish, and
   their callbacks either parse normally (old layout still served, as in mixed A/B) or
   hold. Pipelines keep working. `spider_idle` is not sent while paused, so there is
   no idle close.
4. Repair task: agent (§6.2) → gate (§7) → hot-load (§5.1).
5. Resume: every held request goes back through `engine.crawl(request.replace(dont_filter=True))`.
   Then `engine.unpause()`. `engine.crawl` also wakes the engine, which `unpause()` alone
   doesn't: it would wait for the 5 s heartbeat. The same path works for both repair
   kinds. A repaired navigation variant produces its new requests (e.g.
   `/partials/products?...&page=2..N`) when its held listing pages are processed
   again. The dupefilter drops product URLs already seen, so nothing is yielded twice.
6. Canary: the next K pages routed to the new variant are watched (§7).
7. Failure (gate fails after one retry, the agent gives up, or the budget or wall
   clock runs out): the healer writes `report.md` and calls
   `engine.close_spider(spider, "repair_failed")`. `run_demo.py` exits non-zero on
   that reason, because Scrapy itself exits 0.

### 6.2 The agent session

- **The agent edits the live tree in place:** `local.deploy(spec, workspace=<project root>)`.
  This is safe because the running process only imports new code when the healer
  hot-loads it, so a half-written file has no effect. The healer takes the diff from
  git. On failure it restores the agent-editable paths (`git checkout`/`git clean` on
  `variants/` only). An edit outside those paths fails the gate.
- **Permissions (`permission_mode="acceptEdits"`).** harness-run translates its
  `permission_mode` into a Codex *sandbox mode* plus an *approval policy*:

  | permission_mode | Codex sandbox | approvals |
  |---|---|---|
  | `bypassPermissions` (harness-run default) | `full_access`: no sandbox | never asked |
  | `acceptEdits` | `workspace_write` | never asked; anything outside the sandbox is denied |
  | `default` | `workspace_write` | Codex's auto-reviewer decides escalations |
  | `plan` | `read_only` | — |

  `workspace_write` means every shell command the agent runs goes through Codex's OS
  sandbox on Linux (Landlock/seccomp). Commands may read anywhere but **write only
  inside the workspace (the project root) and temp dirs**, and have **no network** by
  default. The agent itself is never blocked waiting for approval: disallowed actions
  just fail. So the agent can edit `variants/`, run `pytest` and the gate, and use
  scrapy-mcp, but it can't write to `~/.ssh`, `~/.local`, other repos, or reach the
  internet from its shell.

  Confirmed in the spike (§10, FINDINGS 2026-10-03):
  - the scrapy-mcp server runs outside the command sandbox and reaches Remote
    Control on localhost, but Codex blocks its `execute` tool under `acceptEdits`
    unless `codex_config` sets `mcp_servers.scrapy.default_tools_approval_mode = "approve"`;
  - the agent's shell has no network at all, localhost included, so a `curl` to
    the sandbox site needs `sandbox_workspace_write.network_access`. We start
    without it: held pages and fetches through the crawl via scrapy-mcp should
    be enough.

  Scope rules such as "only `variants/`" are enforced by the gate, not the sandbox:
  the sandbox boundary is the whole project root. If this turns out to be friction,
  `bypassPermissions` is the fallback. It is simpler, but the agent could then write
  anywhere on the machine.
- **Inputs:** `repairs/<id>/held/*.html` + info JSON, the `LayoutMismatch` /
  `NavigationMismatch` evidence, `README.md`. The existing variants, items and fixtures
  are already in the tree, and the live crawl is reachable via scrapy-mcp. The prompt
  names the check command:
  `python -m selfheal.gate --spider sandbox_store --candidate sandbox_spider.variants.product_v2
  --held repairs/<id>/held --baseline repairs/<id>/baseline.json`
  (the same gate the healer runs, §7).
- **Structured output** (pydantic, `extra="forbid"`, all fields required):
  `RepairProposal{kind: "variant"|"give_up", module, class_names, summary,
  confidence: "high"|"medium"|"low", evidence}`. The healer picks the module name
  (`<prefix>_v<N+1>`) and the item type, so the agent doesn't choose them.
  `give_up` is how the agent says a repair isn't safe (Case C).
- **Budget:** `max_budget_usd` and `max_turns`, plus a wall-clock `asyncio.wait_for`
  → `session.interrupt()`, since harness-run has no overall timeout. If the gate
  fails, the agent gets one retry: `session.send()` with the gate output.
- One session per repair, deployed lazily, with `checkpoint=True` so the retry
  continues the same conversation. `session.run()` runs as a task on the crawl's
  loop and doesn't block it *(verified, §10)*.

### 6.3 Settings that matter during a pause

- `CLOSESPIDER_TIMEOUT*` keep running on wall-clock time during a repair *(verified)*.
  When one fires mid-repair, the crawl closes normally: the healer cancels the
  agent, rolls back its files and records the repair as `interrupted`. We count the
  pause as part of the run's time budget, so set the timeout above the repair
  budget.
- No `DontCloseSpider` guard is needed: `spider_idle` isn't sent while paused.
- `Spider.start()` is still consumed while paused. That is harmless, since it only
  enqueues.
- Dedup is stable across a swap *(verified)*: a Case A run makes exactly the
  normal crawl's requests plus the held ones, with no duplicate items. scrapy-poet
  isn't used, so its fingerprinter doesn't come into it.

## 7. Validation gate

It runs in a **subprocess** (`python -m selfheal.gate`) so agent code can't crash or
block the crawl. The healer runs it itself and does not trust the agent's claim.

1. **Regression:** `pytest sandbox_spider/fixtures`: all old-variant fixtures pass.
2. **No routing theft:** on every existing fixture of other variants, the candidate
   raises or produces output identical to the fixture.
3. **Coverage:** the candidate handles every held page of its type without raising.
4. **Item check:** every item from the held pages passes `items.check_item`.
5. **Cross-page consistency:** the same fields are populated across held pages, and
   values differ where they should (name and price aren't constant across pages, which
   catches "extracted the page header").
6. **Navigation variants:** each held listing either produces a next request or
   positively establishes that it is the last page (§4.3).
7. **Scope:** the diff touches only `variants/`.

As built, checks 3, 4 and 6 are one `coverage` check: each held page goes
through `Variants.try_variant`, which runs the item checks, and navigation
variants prove the last page themselves (§4.3). Check 5 is `variation`: with 3
or more held pages, `name`, `sku`, `description` and `items` must not have the
same value on every page. Check 7 compares file hashes with a baseline the
healer takes when the repair starts. The only change allowed is the one new
module.

**Canary** (live, after resume): the first K (e.g. 10) new pages routed to the new
variant must pass both gates of §4.2. A failure re-holds the page and triggers a
second repair, or a stop if the budget is spent.
As built, a page routed to the new variant has passed both gates by definition.
So the canary records how many pages the new variant took (`routed`) and
whether any page of that type was refused after resume (`refused`). A refusal
holds the page, which starts the next repair on its own.

"Confidence" for stop-vs-continue = all checks pass AND agent confidence ≠ low. No
scores in phase 0. Independent extractors (e.g. Zyte API automatic extraction) are
out: they are not reliable enough to act as a judge.

**Promotion:** after the gate passes, the held pages + new-variant output are saved as
web-poet fixtures under `repairs/<id>/fixtures/`. A human promotes them into
`fixtures/` (later: via a PR). Until then the record marks them
unreviewed.

## 8. Intent and baseline

- **Intent is prose.** `README.md` in the spider package says what we want from the
  site and why ("every product in every subcategory; price is the current,
  discounted price; …"). No imposed structure. The agent reads it.
- **Hard requirements are ordinary code.** They live in `items.py`: the item class and
  `check_item`, the few things that must be machine-checkable before a yield. These
  are code a spider would normally have; the agent may not edit them.
- **No expectation record.** Everything it was for is now handled by the page objects
  (§4.3) or the gate. The only approved baseline is **fixtures**: saved from a crawl a
  human looked at (`Fixture.save`, frozen time), chosen to cover normal variation
  (discount / no discount, out of stock, no rating, single-page listing, last page of
  a multi-page listing).
- **Reference run (later, optional):** if we want aggregate comparisons, such as item
  count per category vs the previous run, the README links a Scrapy Cloud job (a
  local items file in phase 0). This is not needed for phase 0.

## 9. Recording and metrics

`repairs/<ts>-<id>/`: `held/`, `prompt.md`, `events.jsonl` (streamed harness events,
including scrapy-mcp calls), `proposal.json`, `diff.patch`, `gate.json`, `fixtures/`,
`report.md` (on failure), `metrics.json`. The metrics:

`trigger` (exception, page URL, field and selector), `pages_held`, `paused_s`,
`agent_wall_s`, `cost_usd`, `usage` (in/cached/out/reasoning tokens), `num_turns`,
`diff_lines`, `gate` (per check), `canary` (K, passed), `requests_redownloaded`,
`outcome`. One `repairs/index.jsonl` row per repair.

## 10. Build order

**Step 1: framework first, proven on several spiders, before any agent.** The point
is to find gaps in the detection model while they are cheap to fix.

1. `selfheal.strict` + `dispatch` + item checks + fixture tooling. No healer: a
   dispatch failure just logs and drops the page.
2. Write spiders with it:
   - **sandbox, default layout**: product + numbered-pagination navigation;
   - **sandbox, `modern` layout** written as its own V1. It tests authoring `must`/`may`
     on different markup, and a button-only pagination;
   - **sandbox, `infinite_scroll`** as V1: probe-style navigation over `/partials`;
   - **books.toscrape.com**: a different site shape. It has single-page categories
     *with no pager* and a next-only pager on others, so it exercises exactly the
     §4.3 cases 1–3. It is used only to test how writing and detection work, not as a
     breakage target, since we can't control when real sites break.
3. **Breakage matrix:** each sandbox spider × each sandbox layout, full crawls.
   - Expected: detection fires on the first mismatching page, and never on the
     spider's own layout (the false-positive test).
   - The table goes into the talk as-is.
   - Anything surprising feeds back into §4 before we build the healer.

**Step 2: the loop.**

4. Spike (done, `scripts/spike_pause.py`): from a callback, `pause()` → a
   background-task `session.run()` (Codex, trivial prompt, with scrapy-mcp
   attached, `acceptEdits`). Confirmed:
   - Remote Control stays responsive;
   - in-flight callbacks proceed;
   - scrapy-mcp works from inside the Codex sandbox (once its tools are approved);
   - `engine.crawl` + `unpause()` resumes.
5. Healer + gate + hot-load; Case A end to end (full swap, then ratio 0.5 mixed).
   Done: `scripts/run_demo.py product-modern` / `product-modern-half`.
6. Case C: add the `no_price` sandbox layout; scripted rejection, report, non-zero
   exit.
7. Case B (phase 1): `infinite_scroll` drift → navigation repair.
8. Metrics and record polish; repeatable `make demo-a/b/c`.

## 11. Decisions (from review)

- **D1: Case C.** Start simple: variants are response-only, so a price missing from
  the HTML can't be fixed. This is not a constraint built into the design:
  `build_page` is the one place to add dependencies later, and then `hidden_price`
  becomes a "harder repair" demo.
- **D2: sandbox.** Add layouts as needed (`no_price`; maybe a milder product-only
  redesign).
- **D3: the agent edits the live tree in place**, with a git-based record and rollback
  (§6.2).
- **D4: scrapy-mcp is core from phase 0** (§5.1).
- **D5: detection = page objects raising** (`must`/`may`, any exception), with no
  separate recognizer (§4).
- **D6: resume by re-downloading held requests** (§1, §6.1).
- **D7: intent is prose (README) plus ordinary item-check code.** No spec file and no
  expectation record (§8).
- **D8: no Zyte API automatic-extraction check** (§7).
- **D9: build several spiders on the framework before building the loop** (§10).

## 12. Known risks

- The spike (§10.4) is the load-bearing assumption. If harness-run blocks the loop,
  the fallback is running the agent in a subprocess awaited via
  `asyncio.create_subprocess_exec`.
- Remote Control is new in 2.19. Resume uses only public engine APIs now
  (`engine.crawl`, `pause`, `unpause`).
- Probe-style navigation (§4.3 case 3) costs one extra request per listing, and relies
  on "empty page" and "repeated page" being distinguishable on the site.
- Codex strict structured output may reject optional fields, so the schemas are
  all-required.
