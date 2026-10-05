# Findings

Evidence gathered while building, for the design and the talk. The summary
lists what still stands; the dated log below it keeps the details, newest first.

## Summary (as of 2026-10-03: detection, the repair loop, and a 27-run batch on Sol 6.1)

Step 1 built the detection side on four spiders: three layouts of the sandbox
store and books.toscrape.com. Every spider extracts everything correctly on its
own site: 566/566 products against the sandbox's ground truth, and 1000/1000
books. Across 24 crawls (3 sandbox spiders × 8 layouts), every page was either
extracted fully correctly or refused. **No bad item was delivered.**

### Detection

1. **A redesign of the home page or navigation stops the crawl at the first
   page.** Under the `modern` layout, the default spider sees only the home page,
   refuses it, and has nothing else to visit. The repair loop will start with a
   single held page, so it must work in stages: repair navigation, resume, reach
   the product pages, refuse them, repair again.
2. **Content marked `may` can drift unnoticed on each page.** A category page
   that keeps its products but silently loses its subcategories passes. The
   dead-end check catches only pages that lose everything. Catching the rest needs
   state from outside the page (e.g. per-URL counts from a reference run), which
   makes it the first concrete reason to add external state.
3. **Strictness is a choice the author makes, and it cuts both ways.** Anchors
   that no extraction used caused refusals on harmless drift: the scroll spider
   refused the load-more layout only because of the scroll trigger it never read.
   With those anchors removed it crawls load-more fully correctly. But "only
   `must` what you extract with" also lets a variant accept a page of the wrong
   type. `tests/test_routing.py` guards against that offline, and the validation
   gate will need the same check for new variants.
4. **The variant picked to explain a refusal can be wrong on home pages.**
   Refusals are ranked by how much of the page each variant did extract, which
   names the right variant on category and product pages. On a home page the
   category variant extracts more than the home variant does, and this evidence
   feeds the agent's prompt.
5. **Blind pagination works, at a cost.** The scroll spider probes `?page=N+1`
   until a page comes back empty, which costs one extra request per listing.
   A next page repeating the previous page's products is refused, which is how a
   site that ignores the page parameter gets caught. A site that answers past the
   end with an error page we haven't seen would show up as a refusal.
6. **Detection covers only what the spider extracts.** The `variant-dom-change`
   layout (only the product-variant picker changes) is not detected. That's
   correct, since variants are out of scope, but it's a reminder.
7. **Proving "this is the last page" is possible in every site shape we met:**
   a pagination widget that is always rendered (sandbox default), a page label or
   result count (sandbox modern, books.toscrape.com), or probing (sandbox scroll).
   The undetectable case is a site with none of these whose spider doesn't probe.
   There, only a comparison with a previous run helps, and in-process detection
   is weaker than aggregate monitoring.
8. **Evidence is precise enough to paste into a prompt**, e.g.
   `ProductPageV1.price [extract]: '.product-info .price-tag' matched nothing`.
   The `hidden-price` layout fires only on the price and currency fields.

### Test setup

9. **Case C needed a layout of its own.** `hidden-price` only moves the price
   (it is still in the listing cards and at `/partials/price/{id}`). The
   vendored sandbox now has `layout_no_price`, where the price is for
   signed-in members only, everywhere. Case A uses the sandbox's A/B setting to
   switch only product pages, and a ratio of 0.5 serves both layouts at once.
10. **The default catalogue has no single-page categories.** That fixture is
    captured with `ITEMS_PER_PAGE=20`. Fixtures embed `127.0.0.1:8765` URLs, and
    regenerating them rewrites timestamps, which shows up as diff noise.

### Code

11. **web-poet's "coroutine never awaited" warnings are silenced
    process-wide.** web-poet creates every field coroutine before awaiting any, so
    a field raising inside `to_item()` leaks the rest. The filter also matches
    such a warning from a real bug of ours; a web-poet fork could fix the cause.
12. **Some coupling between spiders remains.** The scroll spider's product and
    home variants subclass the default spider's, and the modern and scroll
    spiders import `sandbox_spider.items`.
13. **scrapy-poet isn't used at all.** Plain web-poet page objects built by hand
    are enough.

### Agent inside the crawl (step 2 spike)

14. **The repair agent can run inside the paused crawl without stalling it.**
    A harness-run Codex session awaited as a task on the crawl's event loop never
    delayed the loop by more than 2.4 ms over about 40 s. Remote Control answered
    in under 2 ms throughout. Pausing stops only new requests: responses already
    in flight are still parsed and yield items. Re-queuing the held page and
    unpausing finishes the same run with 566/566 items.
15. **The agent needs two Codex settings beyond `acceptEdits`.** Codex's
    sandbox blocks scrapy-mcp `execute` calls unless that server's tools are
    approved (`mcp_servers.<name>.default_tools_approval_mode = "approve"`).
    Read-only tools such as `list_jobs` work without it. The scrapy-mcp server
    itself runs outside the sandbox, so it reaches Remote Control on localhost.
    The agent's own shell has no network, not even to localhost. A `curl` to the
    sandbox site works only with `sandbox_workspace_write.network_access`.
    Writes outside the project fail with "Read-only file system".

16. **All three cases behave as intended, each in about a minute and for
    1–3 cents.** In the final round of runs:
    - **A (products redesigned):** one repair, 42 s, 566/566 fully correct.
      With half the products redesigned: 281 pages via V1, 285 via V2, all
      correct.
    - **C (price only for signed-in members):** the agent gives up in about
      19 s. Nothing is loaded, the crawl closes with `repair_failed`, and the
      demo script exits 1.
    - **B (listings switch to infinite scroll):** one repair, 65 s, and a
      variant that probes the scroll fragments until one is empty: 566/566.
17. **The agent uses whatever it can reach, so the workspace has to be
    curated.** When it worked in the live repo it found:
    - the vendored site's templates and router, by grepping for "Sign in to see";
    - the hand-written scroll spider for the same layout, which it then followed;
    - the root README, which names the demo cases ("C: … must refuse");
    - the site's `/openapi.json`, through the live crawl, which lists the hidden
      ground-truth endpoints.

    Now the agent works in a one-commit copy of just its spider (66 files). The
    sandbox serves no OpenAPI. Commands that name the live project are counted.
    The answers didn't change, but the evidence for them is now legitimate.
18. **Outcomes vary from run to run; the loop absorbs it.** Case B produced one
    class covering category pages and fragments in two runs, two classes in
    another. In a third, the first repair forgot the fragments: they were refused
    after resume, which started a second, smaller repair (3 pages, 31 s). In
    every case the crawl ended 566/566.
19. **The live tree must only ever gain the one module.** The first version
    rolled back with `git checkout`, which reverted unrelated edits made by a
    person during a repair. The scope check also failed on those edits. Now
    scope is checked in the agent's workspace, and rollback deletes only the
    module the healer copied in.
20. **A crawl time limit counts the pause.** `CLOSESPIDER_TIMEOUT` fired 20 s
    into a repair. The crawl closed cleanly, the agent was cancelled, and the
    repair was recorded as `interrupted`. Re-downloading doesn't disturb
    duplicate filtering: requests are the normal crawl's plus the held pages.

21. **A variant for pages the agent never had a held example of can be
    wrong without anyone noticing.** On the full `modern` redesign, only the
    home page was held. The agent also wrote a category variant from pages it
    fetched itself. That variant took the "Prev" button for "Next", and the
    dupefilter dropped the backwards links: 445/566 items, with no refusal and
    no error. Now:
    - the gate rejects any class that no held page reaches;
    - page numbers must go up by one;
    - `nextPage` requests skip the dupefilter, so a backwards link is refused;
    - when a page is refused for not following the previous one, the healer
      also holds the previous page (downloaded again), marked with the bad
      link. The gate then requires the new variant to accept it with a
      different `nextPage`.

    With these, `modern` heals in six tested stages: home, top categories,
    subcategories, products, and pagination twice. Result: 566/566 with all 10
    fields correct, $0.11 in total, 5.4 min paused.
22. **The agent gamed a gate check that was unfair.** A first field-coverage
    check compared a home page with category pages, which share an item type.
    The agent passed it on retry by returning category links as `items`,
    hard-coding `pageNumber = 1`, and returning a `nextPage` object whose
    `__bool__` is `False`, so it counts as filled but the spider never
    follows it. Its summary said it did this "to satisfy the navigation field
    contract". The prompt now says not to make a check pass with made-up
    values or tricks, and to give up when a check looks wrong. The agent then
    did exactly that, twice, naming the check. Each time the check was too
    coarse: once for leaf listings without subcategories, once for empty
    scroll fragments. The check now compares fields only with the closest
    existing variant's majority fields, and only for data items, not
    navigation. A wrong check costs a refused repair. It doesn't cost a wrong
    item, as long as the agent is told it may refuse.
23. **The gate compares field coverage with the fixtures, for products.** One
    Case A run passed every other check but left "Color" in
    `additionalProperties`, so 268 products had no `color`. The `fields` check
    rejects that module; later runs got all 10 fields right.

### Sol 6.1, values, more layouts and spiders

24. **On Sol 6.1 (`gpt-6.1-sol`, medium effort) every case behaved as intended
    in 27 runs out of 27.** Nine cases, three runs each:

    | case | stages | $/run | paused |
    |---|---|---|---|
    | A, products redesigned | 1 | 0.12 | 58 s |
    | A, half the products | 1 | 0.13 | 49 s |
    | A, and every price up 13% | 1 | 0.15 | 61 s |
    | B, infinite scroll | 2.7 | 0.36 | 3.1 min |
    | load-more button | 3 | 0.39 | 2.7 min |
    | full `modern` redesign | 4 | 0.43 | 3.1 min |
    | C, price members-only | gives up | 0.06 | 17 s |
    | second spider (scroll) under product redesign | 1 | 0.13 | 47 s |
    | second spider (modern) under infinite scroll | 4.7 | 0.55 | 3.9 min |

    Every healing run ended 566/566 with all 10 fields correct; every C run
    stopped with `repair_failed`. All 55 repairs passed the healer's gate at
    the first attempt (the agent runs the gate itself first). Costs are as
    reported by harness-run, which prices cache writes as plain input; the
    true cost is about 15% higher. The batch cost about $8 in total.
25. **Prices changing doesn't disturb the loop.** With every price up 13%
    before the crawl (`PRICE_SCALE`, a new sandbox knob that changes nothing
    else), Case A heals with all prices matching the new ground truth. Nothing
    compares held values with fixture values: fixtures are saved HTML with the
    output extracted from it. A price change during the pause is described in
    DESIGN §13, not tested.
26. **The held pages are a sample, and the gate must not assume they are
    representative.** In one Case A run all 18 held pages were books, which
    have no brand. The `fields` check wanted `brand` (most fixture products
    have one), and Sol gave up rather than invent one or relabel the
    publisher; it was right. A module may now declare
    `ABSENT_FIELDS = {"brand": "why"}`, which the gate accepts and reports. The
    variant still extracts brand where a page has it: 566/566 in that run.
27. **A second spider needed one change: its workspace must include the
    packages it imports.** `sandbox_scroll` and `sandbox_modern` share item
    checks and base variants with `sandbox_spider`. The workspace now carries
    the project packages the spider's package imports (sibling spiders it
    doesn't import stay hidden), and the prompt finds README and items where
    the item checks live. Both then healed like the first spider.
28. **Sol is more decisive than Luna on staged repairs.** The full redesign
    took 4 stages on Sol (home, top categories, listings, products), against 6
    on Luna; each stage costs 9–15 cents on Sol, against 1–3 on Luna.

29. **In a container, Codex's sandbox can't start, and scrapy-mcp is a way
    around any sandbox anyway.** In the Scrapy Cloud image (tested locally as a
    non-root user) the agent's shell failed to start under `acceptEdits`. The
    agent carried on through scrapy-mcp `execute`, which runs Python inside
    the crawl process, unsandboxed: it read files and ran the gate there. So
    the real boundary is the container, not Codex's sandbox; the image runs
    the agent with `bypassPermissions`. With that (and pytest in the image),
    Case A against the deployed sandbox healed: 566/566, $0.13, first try.

30. **It runs on Scrapy Cloud.** Job 880721/4/5: Case A against the deployed
    sandbox paused 99 s, hot-loaded the variant, resumed, and delivered
    566/566 fully correct items. Getting there took two fixes the local
    container didn't catch: the project root must come from where `selfheal`
    lives (jobs run in `/scrapinghub`, the project is in `/app`), and the
    error for a failed `git ls-files` must say why. The OpenAI key is a
    spider argument (visible in job metadata; a temporary key), passed to
    Codex as a per-run secret; it appears nowhere in the log.

### Still unverified

- The retry path where the agent fixes its own module after the healer's gate
  run fails. So far the agent has fixed problems itself, using the gate,
  before answering.
- Whether the agent ever needs shell network access: it hasn't so far.

# Log

## 2026-10-03 — Sol 6.1: values change, load-more, second spider, 27-run batch

Setup: harness-run pinned to main `4028849` (zytedata/harness-run#6, Codex CLI
0.159.2), model `gpt-6.1-sol`, medium effort. harness-run prices it from
LiteLLM at $2.00 / $0.10 / $10.00 per 1M input / cached / output tokens, so
the budget cap works; cache writes ($2.50) are priced as input.

1. **First Case A run: an honest refusal of an unfair check.** All 18 held
   pages were books; the `fields` check demanded `brand`. Sol's evidence: "GATE
   FAILED only on the brand field profile … README requests brand only when
   shown; inventing it or relabeling Publisher would be incorrect." Fixed with
   `ABSENT_FIELDS` (summary 26). Rerun: 566/566, $0.13, 45 s.
2. **Values test.** New sandbox knob `PRICE_SCALE` multiplies every generated
   price without touching the random sequence (ids, names, attributes stay).
   Preset `product-modern-repriced`: 566/566 against the new prices, first try.
3. **load-more.** Three stages (listing with button, fragment, empty fragment
   ending a category), 566/566, $0.41. No code changes needed.
4. **Second spider.** Preset `scroll-modern` (infinite-scroll listings, modern
   products) is Case A for `sandbox_scroll` and Case B for `sandbox_modern`.
   First attempt needed the workspace to include `sandbox_spider`, which both
   import (summary 27); both spiders also got `dont_filter` on `nextPage`.
5. **Batch** (`scripts/batch.py`, results in `output/batch/results.jsonl`):
   one round of 9 cases, checked, then two more. 27/27 as intended, 55/55
   repairs first-try (summary 24). Long pauses are agent time: healer overhead
   is under a second per repair.

Note on earlier Luna costs: harness-run's LiteLLM price for `gpt-5.6-luna`
($0.20 / $0.02 / $1.20) is a fifth of its own fallback table ($1.00 / $0.10 /
$6.00). The Luna figures above use LiteLLM's; if the fallback is right, they
are 5× too low.

## 2026-10-03 — the full redesign heals; the agent games a bad check, then refuses one

Continuing from the entry below:

- **Bad next links.** When the progress check refuses a page, the healer
  downloads the previous page again and holds it with `bad_next` (the link
  that went wrong). It doesn't re-queue the refused page, whose fetch is now
  up to the repaired link. The gate requires a candidate to accept a
  `bad_next` page with a different `nextPage`. On `modern`, stages 5 and 6
  each held 2 such pages, and the crawl finished 566/566.
- **Gaming.** With the first version of the `fields` check, `modern`'s home
  page repair failed the healer's gate run. On the retry the agent made the
  home page variant fill `items` (category links), `pageNumber` (1) and a
  falsy `nextPage`, and passed. That was also the first time the retry path
  ran. After the prompt change, an agent facing the same kind of wrong check
  answered `give_up` with the reason. That happened in a `modern` stage
  (subcategories) and in Case B (empty end-of-list fragments).
- **Final field check.** Profiles come from the closest existing variant's
  fixtures, counting only fields filled on at least half of them. They apply
  to data items only. Verified on the bad Case A module (rejected: `color`),
  the honest leaf-listing variant (accepted), and a minimal home page variant
  (accepted).

| run | stages | paused (total) | cost | result |
|---|---|---|---|---|
| `modern` | 6: home 1 page, top categories 4, subcategories 20, products 16, pagination 4 + 4 | 323 s | $0.111 | 566/566, all 10 fields, 683 requests |
| `infinite-scroll` | 1: 20 listing pages, one class for listings and fragments | 50 s | $0.024 | 566/566, all 10 fields |

## 2026-10-03 — the full `modern` redesign: staged repairs and what they exposed

`modern` changes every page type, so the crawl first refuses the home page,
which is the only page it has. Three runs:

1. **Before the new rules: 445/566, silently.**
   - Repair 1 held only the home page. The agent wrote `HomePageV2` plus a
     `CategoryPageV2` based on category pages it fetched through scrapy-mcp.
   - Repair 2 handled products.
   - The category variant's `nextPage` took the first `.control-panel` button.
     On page 2 and later that is "Prev". The link back was dropped as a
     duplicate, so each listing stopped at page 2. No refusal, nothing in the
     stats.
2. **After "every class must handle a held page" (limit 3 repairs).** The
   stages were home (1 page, 34 s), top categories (4 pages, 25 s) and
   subcategory pages (20 pages, 46 s). Then the limit was reached while products
   and later listing pages waited: `repair_failed`.
3. **Limit 6.** Six stages: home, top categories, subcategories, products, then
   twice "page 1 does not follow page 2". The progress check now catches the
   same Prev/Next bug. Each time the held page was the target page 1, not
   page 2 with the bad link. Variants V5 and V6 were written for page 1,
   which never fixes page 2. The run ended `repair_failed` with 63 correct
   items and no wrong ones.

Case B under the same rules goes through two tested stages: category pages
(20 held, 58 s), then the fragment probes (3 held, 29 s). It ends 566/566,
same as the staged run earlier. Case A is unaffected (566/566). A plain
default crawl still makes 627 requests, since `dont_filter` on `nextPage`
costs nothing when links go forward.

**A field dropped silently.** One Case A run passed every gate check but left
"Color" in `additionalProperties` instead of `color`: 298/566 correct on
`color` and `additionalProperties`. The new `fields` check fails that module:
"color is filled on 4/6 existing fixtures but on none of the held pages". In
the next run the agent passed the gate on the first attempt with all 10 fields
566/566, after 17 turns, 90 s and $0.026.

## 2026-10-03 — Cases B and C, a clean workspace for the agent

Vendored the sandbox into `sandbox/` and added `layout_no_price` (drift preset
`no-price`). In that layout product pages say "Sign in to see our price",
listing cards have no price, and `/partials/price/{id}` returns 401. Only
`price`/`currency` are refused, the same way `hidden-price` behaves.

**What the agent found when it could see the whole repo**, and what we changed:

| run | what it read | change |
|---|---|---|
| C, first | `rg "Sign in to see" .` hit `sandbox/app/templates/.../layout_no_price/detail.html` and the router | agent works in a temp copy |
| A, copy | ran `rg` on the live repo's absolute path, learned from the `.venv/bin/python` path in the gate command | `.selfheal/python` wrapper |
| B | read `sandbox_scroll/variants/navigation_v1.py` before writing its own | copy only the repaired spider's package + `selfheal/` |
| C | fetched `/openapi.json` through the crawl, found `/sandbox-store/data/product/{id}` | sandbox: `openapi_url=None`, `docs_url=None` |
| C | read the root `README.md` ("C: price gone; must refuse") | top-level files: only `scrapy.cfg`, `pyproject.toml`, `.gitignore`, `LICENSE` |
| C | probed `?member=true`, `?auth=true`, `/login` through the crawl | prompt: don't get around sign-in or access controls |

Every Case C run gave up for the right reason. In the run that found
`/data/product/{id}`, the agent noted that a page object only gets the product
page, so it couldn't use the endpoint anyway. After the prompt change it
stopped probing and gave up from the held pages alone: 6 turns, 19 s,
$0.011, versus 14 turns and $0.024 before.

**A bug in the healer, found by accident.** I edited `README.md` while a Case A
repair ran. The healer's live-tree scope check flagged the edit on both
attempts, failed the repair, and rolled back with `git checkout`, which reverted
the edit. Now the scope check runs in the agent's workspace, and rollback
deletes only the copied module. A test edit to `docs/FINDINGS.md` during the
next Case A repair survived, and the repair passed.

**scrapy-mcp in use.** The agent first passed the pid as `job_id`, which
failed; the prompt now gives the exact job id. Since then it uses the live crawl
for its own checks: fetching a held page again (`download_async` while paused
works), comparing listing pages, and probing URLs. In the final round only Case
B used it (2 calls).

**Final round** (clean workspace, 66 files):

| case | held | agent | paused | cost | turns | gate | result |
|---|---|---|---|---|---|---|---|
| A `product-modern` | 18 | 41.3 s | 42.3 s | $0.017 | 9 | pass | 566/566 fully correct, 645 requests |
| C `no-price` | 17 | 18.8 s | 18.9 s | $0.011 | 6 | — (gave up) | `repair_failed`, exit 1 |
| B `infinite-scroll` | 20 | 64.2 s | 65.2 s | $0.026 | 16 | pass | 566/566, 670 requests |
| A `product-modern-half` | 9 | 44.1 s | 45.0 s | $0.021 | 11 | pass | 566/566 (281 V1 + 285 V2) |

- **Case B is how a navigation repair continues.** Re-queued listing pages go
  through the new variant, which yields product requests and then fragment
  probes. The scroll spider built by hand made 647 requests; the healed one
  makes 670 (20 held pages fetched again, plus a few probes). Across the runs
  the agent's design varied:
  - one class matching both category pages and fragments;
  - two classes;
  - one class that forgot the fragments, followed by a second repair.

  All of them ended 566/566.
- **The canary records `refused` > 0 for a variant that missed something.**
  In the staged Case B run, the first repair's canary had `refused: 3`. The
  refused fragments were held and started the second repair.

## 2026-10-03 — Case A end to end: healer, gate, hot-load

Built `selfheal/healer.py` (a Scrapy extension, off unless `SELFHEAL_ENABLED`),
`selfheal/gate.py` (`python -m selfheal.gate`) and `scripts/run_demo.py`. The
loop:

1. A refused page is held: saved as body + JSON with its evidence under
   `repairs/<id>/held/`.
2. The engine pauses. The healer waits for in-flight responses to drain, since
   they add more held pages.
3. The healer takes a file-hash baseline and writes the prompt, then runs a
   Codex session. The settings are `gpt-5.6-luna`, medium effort,
   `acceptEdits`, and scrapy-mcp with its tools approved.
4. The healer runs the gate itself. If it fails, the agent gets one retry with
   the gate output.
5. The healer hot-loads the module through Remote Control `/execute`,
   re-queues the held requests and unpauses.

| run | held | agent | gate | paused | cost | turns | result |
|---|---|---|---|---|---|---|---|
| `product-modern` (all products drift) | 18 | 47.8 s | pass, 1st try | 48.7 s | $0.026 | 17 | 566/566 fully correct, all via V2 |
| `product-modern-half` (A/B 0.5) | 8 | 46.5 s | pass, 1st try | 47.4 s | $0.022 | 13 | 566/566 fully correct, 281 V1 + 285 V2 |
| `product-modern` + `CLOSESPIDER_TIMEOUT=20` | 17 | cut at 20 s | — | — | — | — | closed `closespider_timeout`, repair `interrupted`, 0 items |

- **Every field of V1 failed, and the evidence says so.** The held page's
  evidence lists all 14 V1 fields with the selector that matched nothing.
  `metrics.json` records only the first, which is `description` because of
  web-poet's field order. This is a full redesign, not a renamed class, and
  the agent rewrote every selector from the held HTML.
- **What the agent did.** About 17 commands: list the spider package and held
  pages, read README/items/`product_v1.py`, the V1 fixtures' outputs, and the
  held HTML (several `rg`/`sed` passes). Then it wrote `product_v2.py` (118
  lines in the first run, `must`/`may` throughout), ran the gate (pass), and
  read `selfheal/gate.py` and `dispatch.py` to check the extracted items with a
  snippet of its own. It didn't call scrapy-mcp; it had no need to.
- **The agent did a review beyond the gate on its own.** Its evidence field
  says it compared the extracted values with the README after the gate passed.
  The prompt asks for that, and the event log shows it ran a snippet to print
  the items.
- **Two runs wrote two different `product_v2.py` modules**, 118 and 130 lines,
  both fully correct. We keep neither: `run_demo.py --reset` deletes untracked
  variant modules, so every demo starts broken.
- **The canary is not much of a test as built.** A page routed to the new
  variant has passed extraction and the item checks by definition. What it
  records is `routed` (113 and 57 pages before the poll noticed K=10) and
  `refused` after resume (0 in both).
- **Timeout.** `CLOSESPIDER_TIMEOUT` is a plain `call_later` from spider start,
  so it fires during a pause. The healer's `spider_closed` handler cancels the
  repair task (the Codex process exits with it), rolls back added files and
  records `interrupted`. In this run the agent hadn't written its file yet, so
  rollback had nothing to remove. We keep the behaviour: the pause is part of
  the run's time budget.
- **Duplicate filtering.** 645 requests = 627 (normal crawl) + 18 held pages
  re-downloaded with `dont_filter`, and 566 unique items. Nothing else was
  re-fetched.

## 2026-10-03 — step 2 spike: agent inside a paused crawl

`scripts/spike_pause.py` crawls the sandbox store in its default layout. After
20 products, it holds the next product page as if no variant recognised it,
calls `engine.pause()`, and starts a harness-run Codex session (`gpt-5.6-luna`,
`acceptEdits`, scrapy-mcp via `uvx`) as a task on the crawl's loop. The prompt is
a plumbing test with no repair. The agent is asked to find the job through
scrapy-mcp, run a snippet in it, `curl` the sandbox, write a file in the
workspace, write one outside it, and sleep 20 s. Afterwards the held request is
re-queued with `dont_filter=True` and the engine is unpaused.

The crawl side was the same in all three runs:

- A heartbeat task measured event-loop lag every 0.5 s while paused (75–81
  samples per run). The maximum lag was 2.4 ms, so the session doesn't block
  the loop.
- Our own `GET /status` to Remote Control during the pause returned 200 every
  time, in at most 1.5 ms.
- In-flight requests drained after the pause and their callbacks ran: 15–20
  product callbacks, and items went from about 24 to about 40 while paused. The
  scheduler held 267–283 requests untouched.
- The agent session took 38–41 s, cost about $0.01 and used 6 turns.
- Resume: the crawl finished with 566/566 items (`finished`), including the held
  page.
- One setup step: `local.deploy` with Codex needs the `openai-codex` SDK, i.e.
  `harness-run[local]` (our `agent` extra). Without it the run fails at once
  and the crawl resumes, which shows the failure path works too.

What the agent could do depended on `codex_config`:

| run | codex_config | scrapy-mcp `list_jobs` | scrapy-mcp `execute` | shell `curl` 127.0.0.1:8765 | write in project | write in `~` |
|---|---|---|---|---|---|---|
| 1 | none | ok | blocked ("approval policy is never") | refused (exit 7) | ok | Read-only file system |
| 2 | `default_tools_approval_mode=approve` + `network_access` | ok | ok | 200 | ok | Read-only file system |
| 3 | `default_tools_approval_mode=approve` | ok | ok | refused (exit 7) | ok | Read-only file system |

In runs 2 and 3, the agent's snippet saw the live state: `paused=True`, the
scheduler size, the item count and the held URL. Its second snippet, 20 s
later, printed the same values, so nothing moved during the pause.

Consequences for the design:

- `acceptEdits` is usable as planned. Add
  `mcp_servers.scrapy.default_tools_approval_mode = "approve"` to the spec's
  `codex_config`.
- Shell network access is off by default. Repairs should first try working
  from held pages and from fetches made through the crawl via scrapy-mcp. Turn
  network on only if that turns out to be too limiting.
- `execute` approval is per-server, so it covers every snippet the agent sends.
  A read-only mode for scrapy-mcp would be the place to restrict that.

## 2026-10-03 — review follow-ups

- **Pure anchors removed everywhere.** Every `must` that only checked an element
  existed (`.breadcrumbs`, `.nav-path`, `.dashboard-header`, `.hero h1`, an empty
  `.pagination` on product-less pages) is gone. Where an anchor was telling page
  types apart, that context now lives in the selector used for extraction
  (`.hero ~ .grid .card a`). All fixtures still produce identical output.
  - Re-run breakage matrix (below). Items and fully-correct counts are unchanged
    in every cell. The one difference: under `infinite-scroll` and `load-more`,
    `sandbox_store` now accepts the 4 product-less top-level categories
    (identical output, nothing to fix there) and refuses the 20 subcategory pages,
    exactly where pagination went missing. Before, it refused the 4 top-level
    categories and never reached the subcategories. That's more evidence for a
    repair, in the right place. Some "first refusal" evidence now names a
    different selector because the anchors are gone.
- **New offline gate test: no routing theft** (`tests/test_routing.py`). Every
  variant of every spider is run on every other variant's fixtures (228 pairs).
  A variant may accept a page only if it produces exactly the fixture's output.
  It passes. The only acceptances are between spiders that share a layout
  (default ↔ scroll product and home pages, and default category ↔ scroll
  top-category).
- **Spiders are self-contained.** The crawl logic (navigation → products, with
  `previous` passed along `nextPage`) is repeated in each spider rather than
  shared through a base class. The framework keeps only what self-healing
  needs.
- **Open: drift in `may`-only content.** Example: `subCategories` on the modern
  layout's category pages is a `may`, so if the tag cloud were renamed, those
  pages would keep "working" with no subcategories. Partly covered today:
  - a page left with neither products nor subcategories fails the
    `check_navigation` dead-end check;
  - a page that keeps its products and loses only its subcategories goes
    unnoticed per page.

  A fix would need state from outside the page: e.g. per-URL counts (of
  subcategories, products) from a reference run, with a refusal on a large
  deviation. That is the "reference run" in DESIGN §8, and the first concrete
  reason to add external state.

Breakage matrix after the cleanup (`python scripts/matrix.py`):

| spider | sandbox layout | requests | items | fully correct | variants used | refused | first refusal |
|---|---|---|---|---|---|---|---|
| sandbox_store | default | 627 | 566 | 566/566 | CategoryPageV1 60, HomePageV1 1, ProductPageV1 566 | — |  |
| sandbox_store | product-modern | 627 | 0 | — | CategoryPageV1 60, HomePageV1 1 | Product 566 | no Product variant accepts /product/…: — ProductPageV1.description [extract]: '.product-info > p' matched nothing |
| sandbox_store | product-modern-half | 627 | 281 | 281/281 | CategoryPageV1 60, HomePageV1 1, ProductPageV1 281 | Product 285 | no Product variant accepts /product/…: — ProductPageV1.description [extract]: '.product-info > p' matched nothing |
| sandbox_store | infinite-scroll | 25 | 0 | — | CategoryPageV1 4, HomePageV1 1 | ProductNavigation 20 | no ProductNavigation variant accepts /category/cat_3_sub_4: — CategoryPageV1.pageNumber [extract]: '.pagination' matched nothing |
| sandbox_store | load-more | 25 | 0 | — | CategoryPageV1 4, HomePageV1 1 | ProductNavigation 20 | no ProductNavigation variant accepts /category/cat_3_sub_4: — CategoryPageV1.pageNumber [extract]: '.pagination' matched nothing |
| sandbox_store | modern | 1 | 0 | — | — | ProductNavigation 1 | no ProductNavigation variant accepts /: — CategoryPageV1.items [extract]: '.grid-3' matched nothing |
| sandbox_store | hidden-price | 627 | 0 | — | CategoryPageV1 60, HomePageV1 1 | Product 566 | no Product variant accepts /product/…: — ProductPageV1.currency [extract]: '.product-info .price-tag' matched nothing |
| sandbox_store | variant-dom-change | 627 | 566 | 566/566 | CategoryPageV1 60, HomePageV1 1, ProductPageV1 566 | — |  |
| sandbox_modern | default | 1 | 0 | — | — | ProductNavigation 1 | no ProductNavigation variant accepts /: — CategoryPageV1.items [extract]: '.inventory-table table tbody' matched nothing |
| sandbox_modern | product-modern | 1 | 0 | — | — | ProductNavigation 1 | no ProductNavigation variant accepts /: — CategoryPageV1.items [extract]: '.inventory-table table tbody' matched nothing |
| sandbox_modern | product-modern-half | 1 | 0 | — | — | ProductNavigation 1 | no ProductNavigation variant accepts /: — CategoryPageV1.items [extract]: '.inventory-table table tbody' matched nothing |
| sandbox_modern | infinite-scroll | 1 | 0 | — | — | ProductNavigation 1 | no ProductNavigation variant accepts /: — CategoryPageV1.items [extract]: '.inventory-table table tbody' matched nothing |
| sandbox_modern | load-more | 1 | 0 | — | — | ProductNavigation 1 | no ProductNavigation variant accepts /: — CategoryPageV1.items [extract]: '.inventory-table table tbody' matched nothing |
| sandbox_modern | modern | 627 | 566 | 566/566 | CategoryPageV1 60, DashboardPageV1 1, ProductPageV1 566 | — |  |
| sandbox_modern | hidden-price | 1 | 0 | — | — | ProductNavigation 1 | no ProductNavigation variant accepts /: — CategoryPageV1.items [extract]: '.inventory-table table tbody' matched nothing |
| sandbox_modern | variant-dom-change | 1 | 0 | — | — | ProductNavigation 1 | no ProductNavigation variant accepts /: — CategoryPageV1.items [extract]: '.inventory-table table tbody' matched nothing |
| sandbox_scroll | default | 5 | 0 | — | HomePageV1 1 | ProductNavigation 4 | no ProductNavigation variant accepts /category/cat_3: — ScrollCategoryPageV1.items [extract]: '#product-grid' matched nothing |
| sandbox_scroll | product-modern | 5 | 0 | — | HomePageV1 1 | ProductNavigation 4 | no ProductNavigation variant accepts /category/cat_3: — ScrollCategoryPageV1.items [extract]: '#product-grid' matched nothing |
| sandbox_scroll | product-modern-half | 5 | 0 | — | HomePageV1 1 | ProductNavigation 4 | no ProductNavigation variant accepts /category/cat_3: — ScrollCategoryPageV1.items [extract]: '#product-grid' matched nothing |
| sandbox_scroll | infinite-scroll | 647 | 566 | 566/566 | HomePageV1 1, ProductCardsFragmentV1 56, ProductPageV1 566, ScrollCategoryPageV1 24 | — |  |
| sandbox_scroll | load-more | 647 | 566 | 566/566 | HomePageV1 1, ProductCardsFragmentV1 56, ProductPageV1 566, ScrollCategoryPageV1 24 | — |  |
| sandbox_scroll | modern | 1 | 0 | — | — | ProductNavigation 1 | no ProductNavigation variant accepts /: — ScrollCategoryPageV1.items [extract]: '#product-grid' matched nothing |
| sandbox_scroll | hidden-price | 5 | 0 | — | HomePageV1 1 | ProductNavigation 4 | no ProductNavigation variant accepts /category/cat_3: — ScrollCategoryPageV1.items [extract]: '#product-grid' matched nothing |
| sandbox_scroll | variant-dom-change | 5 | 0 | — | HomePageV1 1 | ProductNavigation 4 | no ProductNavigation variant accepts /category/cat_3: — ScrollCategoryPageV1.items [extract]: '#product-grid' matched nothing |

## 2026-09-28 — step 1b: three more spiders on the framework

Spiders, each written against its own site/layout:

- `sandbox_modern`: the store's `modern` design, written as its own V1. Table
  listings, button-only pagination around a `PAGE x / y` label (§4.3 case 2),
  "spec sheet" product pages.
- `sandbox_scroll`: `infinite_scroll`. There are no pagination links, so the
  spider probes `/partials/products?...&page=N+1` until a fragment is empty
  (§4.3 case 3). A new framework check refuses a next page that repeats the
  previous page's products: `check_progress` in `selfheal/dispatch.py`, run by
  `Variants.try_variant` when the spider passes the previous page along
  `nextPage` (`cb_kwargs={"previous": nav}`).
- `books`: books.toscrape.com. Multi-page categories use the "Page x of y" pager
  (case 1). Single-page categories have no pager, only "N results", and must list
  exactly N books (case 2).

Own-layout crawls (no false positives, everything correct):

| spider | requests | items | correct |
|---|---|---|---|
| sandbox_store on default | 627 | 566 | 566/566 vs ground truth |
| sandbox_modern on modern | 627 | 566 | 566/566 vs ground truth |
| sandbox_scroll on infinite-scroll | 647 | 566 | 566/566 vs ground truth |
| books on books.toscrape.com | 1130 | 1000 | no ground truth; 1000 unique SKUs, all required fields filled, 998 descriptions (the 2 missing are absent on the site) |

Probing costs **one extra request per listing** (647 vs 627: 20 subcategories →
20 empty "past the end" fragments).

Breakage matrix, 3 sandbox spiders × 8 layouts (`python scripts/matrix.py`;
superseded by the re-run after the anchor cleanup above):

| spider | sandbox layout | requests | items | fully correct | variants used | refused | first refusal |
|---|---|---|---|---|---|---|---|
| sandbox_store | default | 627 | 566 | 566/566 | CategoryPageV1 60, HomePageV1 1, ProductPageV1 566 | — |  |
| sandbox_store | product-modern | 627 | 0 | — | CategoryPageV1 60, HomePageV1 1 | Product 566 | no Product variant accepts /product/…: — ProductPageV1.description [extract]: '.product-info > p' matched nothing |
| sandbox_store | product-modern-half | 627 | 281 | 281/281 | CategoryPageV1 60, HomePageV1 1, ProductPageV1 281 | Product 285 | no Product variant accepts /product/…: — ProductPageV1.description [extract]: '.product-info > p' matched nothing |
| sandbox_store | infinite-scroll | 5 | 0 | — | HomePageV1 1 | ProductNavigation 4 | no ProductNavigation variant accepts /category/cat_3: — CategoryPageV1.pageNumber [extract]: '.pagination' matched nothing |
| sandbox_store | load-more | 5 | 0 | — | HomePageV1 1 | ProductNavigation 4 | no ProductNavigation variant accepts /category/cat_3: — CategoryPageV1.pageNumber [extract]: '.pagination' matched nothing |
| sandbox_store | modern | 1 | 0 | — | — | ProductNavigation 1 | no ProductNavigation variant accepts /: — CategoryPageV1.categoryName [extract]: '.breadcrumbs' matched nothing |
| sandbox_store | hidden-price | 627 | 0 | — | CategoryPageV1 60, HomePageV1 1 | Product 566 | no Product variant accepts /product/…: — ProductPageV1.currency [extract]: '.product-info .price-tag' matched nothing |
| sandbox_store | variant-dom-change | 627 | 566 | 566/566 | CategoryPageV1 60, HomePageV1 1, ProductPageV1 566 | — |  |
| sandbox_modern | default | 1 | 0 | — | — | ProductNavigation 1 | no ProductNavigation variant accepts /: — CategoryPageV1.categoryName [extract]: '.nav-path' matched nothing |
| sandbox_modern | product-modern | 1 | 0 | — | — | ProductNavigation 1 | no ProductNavigation variant accepts /: — CategoryPageV1.categoryName [extract]: '.nav-path' matched nothing |
| sandbox_modern | product-modern-half | 1 | 0 | — | — | ProductNavigation 1 | no ProductNavigation variant accepts /: — CategoryPageV1.categoryName [extract]: '.nav-path' matched nothing |
| sandbox_modern | infinite-scroll | 1 | 0 | — | — | ProductNavigation 1 | no ProductNavigation variant accepts /: — CategoryPageV1.categoryName [extract]: '.nav-path' matched nothing |
| sandbox_modern | load-more | 1 | 0 | — | — | ProductNavigation 1 | no ProductNavigation variant accepts /: — CategoryPageV1.categoryName [extract]: '.nav-path' matched nothing |
| sandbox_modern | modern | 627 | 566 | 566/566 | CategoryPageV1 60, DashboardPageV1 1, ProductPageV1 566 | — |  |
| sandbox_modern | hidden-price | 1 | 0 | — | — | ProductNavigation 1 | no ProductNavigation variant accepts /: — CategoryPageV1.categoryName [extract]: '.nav-path' matched nothing |
| sandbox_modern | variant-dom-change | 1 | 0 | — | — | ProductNavigation 1 | no ProductNavigation variant accepts /: — CategoryPageV1.categoryName [extract]: '.nav-path' matched nothing |
| sandbox_scroll | default | 5 | 0 | — | HomePageV1 1 | ProductNavigation 4 | no ProductNavigation variant accepts /category/cat_3: — ScrollCategoryPageV1.items [extract]: '#product-grid' matched nothing |
| sandbox_scroll | product-modern | 5 | 0 | — | HomePageV1 1 | ProductNavigation 4 | no ProductNavigation variant accepts /category/cat_3: — ScrollCategoryPageV1.items [extract]: '#product-grid' matched nothing |
| sandbox_scroll | product-modern-half | 5 | 0 | — | HomePageV1 1 | ProductNavigation 4 | no ProductNavigation variant accepts /category/cat_3: — ScrollCategoryPageV1.items [extract]: '#product-grid' matched nothing |
| sandbox_scroll | infinite-scroll | 647 | 566 | 566/566 | HomePageV1 1, ProductCardsFragmentV1 56, ProductPageV1 566, ScrollCategoryPageV1 24 | — |  |
| sandbox_scroll | load-more | 647 | 566 | 566/566 | HomePageV1 1, ProductCardsFragmentV1 56, ProductPageV1 566, ScrollCategoryPageV1 24 | — |  |
| sandbox_scroll | modern | 1 | 0 | — | — | ProductNavigation 1 | no ProductNavigation variant accepts /: — ProductCardsFragmentV1.items [extract]: 'body > *' fragment has non-card elements: <aside> |
| sandbox_scroll | hidden-price | 5 | 0 | — | HomePageV1 1 | ProductNavigation 4 | no ProductNavigation variant accepts /category/cat_3: — ScrollCategoryPageV1.items [extract]: '#product-grid' matched nothing |
| sandbox_scroll | variant-dom-change | 5 | 0 | — | HomePageV1 1 | ProductNavigation 4 | no ProductNavigation variant accepts /category/cat_3: — ScrollCategoryPageV1.items [extract]: '#product-grid' matched nothing |

Observations:

- **Every cell is either fully correct or refused. No bad items in 24 crawls.**
- **Only `must` what you extract with.** At first the scroll spider refused the
  `load-more` layout, only because it `must`-ed `#sentinel` (the scroll trigger),
  which it doesn't use. Load-more serves the same grid and the same fragment
  endpoint. Once that anchor was removed, `sandbox_scroll` crawls `load-more` fully
  correctly: harmless drift passes, and the check refused only what it could not
  handle. Rule for authors (and for the agent's prompt): an anchor that no
  extraction uses buys false positives, not safety.
- **Evidence has to name the right variant.** At first the refusal listed first
  came from whichever variant was tried first (e.g. the fragment variant
  complaining about `<header>` on a full page). Refusals are now ranked by how
  much of the page each variant *did* extract: item-check refusals first, then
  the most non-empty fields. With that, category and product pages lead with the
  intended variant's failure.
  - It stays ambiguous for **home pages**: the category variant extracts more
    from a home page than the home variant does. A role hint from the request
    ("this is the start URL") would fix it. Deferred.
- A spider for one layout refuses every other layout at the first page of the
  type that differs. When the home/navigation differs, the crawl stops after 1
  request. That is what we want (nothing wrong delivered), but it confirms that
  repairs must work in stages (see step 1).
- `sandbox_scroll` and `sandbox_store` reuse the default product variant by
  subclassing it. A subclass in its own module is the cheapest way to share a
  variant between spiders while keeping one module per variant.

## 2026-09-28 — step 1: framework core + sandbox default-layout spider

Breakage matrix (superseded by later runs above; `python scripts/matrix.py`, no healer; "fully correct" = every
scored field matches the sandbox ground truth):

| preset | items | fully correct | variants used | refused | first refusal |
|---|---|---|---|---|---|
| default | 566 | 566/566 | CategoryPageV1 60, HomePageV1 1, ProductPageV1 566 | — |  |
| product-modern | 0 | — | CategoryPageV1 60, HomePageV1 1 | Product 566 | no Product variant accepts http://127.0.0.1:8765/sandbox-store/product/b05731fd-8916-40b7-b9ba-547e7b4bcaf8: — ProductPageV1.description [extract]: '.product-info > p' matched nothing |
| product-modern-half | 281 | 281/281 | CategoryPageV1 60, HomePageV1 1, ProductPageV1 281 | Product 285 | no Product variant accepts http://127.0.0.1:8765/sandbox-store/product/6c44821e-af05-4764-8234-af07f3e08b1f: — ProductPageV1.description [extract]: '.product-info > p' matched nothing |
| infinite-scroll | 0 | — | HomePageV1 1 | ProductNavigation 4 | no ProductNavigation variant accepts http://127.0.0.1:8765/sandbox-store/category/cat_3: — CategoryPageV1.pageNumber [extract]: '.pagination' matched nothing |
| load-more | 0 | — | HomePageV1 1 | ProductNavigation 4 | no ProductNavigation variant accepts http://127.0.0.1:8765/sandbox-store/category/cat_3: — CategoryPageV1.pageNumber [extract]: '.pagination' matched nothing |
| modern | 0 | — | — | ProductNavigation 1 | no ProductNavigation variant accepts http://127.0.0.1:8765/sandbox-store/: — CategoryPageV1.categoryName [extract]: '.breadcrumbs' matched nothing |
| hidden-price | 0 | — | CategoryPageV1 60, HomePageV1 1 | Product 566 | no Product variant accepts http://127.0.0.1:8765/sandbox-store/product/b05731fd-8916-40b7-b9ba-547e7b4bcaf8: — ProductPageV1.currency [extract]: '.product-info .price-tag' matched nothing |
| variant-dom-change | 566 | 566/566 | CategoryPageV1 60, HomePageV1 1, ProductPageV1 566 | — |  |

Observations:

- **No false positives** on the default layout: 566/566 products and 61/61
  navigation pages accepted, every item fully correct against ground truth. The
  default catalogue covers discount, out of stock, no rating and no brand.
- **No bad items under drift.** Every page was either extracted fully correctly
  or refused. In the mixed A/B run (`product-modern-half`), 281 old-layout pages
  went through V1 correctly and 285 new-layout pages were refused.
- **Detection fires where the drift is.** Product redesign: on each product page.
  `hidden-price`: only the price/currency fields, nothing else. Infinite scroll
  and load more: on the first category page (`.pagination` missing). That is
  §4.3 case 1, "pagination is always rendered", working as designed.
- **A whole-site redesign (`modern`) stops the crawl at the home page.** Only one
  page is ever seen, so the healer would get a single held page and would
  have to repair navigation before it sees any product page. That is a
  repair-in-stages case to design for (repair nav → resume → product pages are
  refused → second repair).
- `variant-dom-change` is not detected, and correctly so: only the variant picker
  changes, and variants are out of scope in the README.
- Evidence is precise enough to paste into a prompt:
  `ProductPageV1.price [extract]: '.product-info .price-tag' matched nothing`.

Friction found (candidates for a web-poet fork or for framework polish):

- web-poet creates every field coroutine before awaiting any of them, so a field
  that raises inside `to_item()` leaks "coroutine never awaited" warnings. We
  filter the warning for now.
- On failure, dispatch evaluates the fields one by one again so it can name every
  failing field. The extra cost is paid only for refused pages.
- A page type with nothing to extract but an anchor (the home page) puts its
  `must` inside the one real field. That works, but it's implicit.
- scrapy-poet is not used at all so far. Plain web-poet page objects built by
  hand are enough.
- The default catalogue has no single-page category. The `single-page`
  fixture is captured with `ITEMS_PER_PAGE=20` (same layout).
