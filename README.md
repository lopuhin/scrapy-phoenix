# scrapy-phoenix

A prototype of a Scrapy spider that notices, mid-crawl, that the site it is
crawling has changed, and repairs itself without stopping the run: it pauses,
runs a coding agent inside the same process to add a new page-object variant,
validates and hot-loads it, and resumes.

Fixed intent, mutable implementation.

This repository accompanies a conference talk. It is a prototype and is not
developed further after the talk.

## Status

- Done: detection. Page objects fail loudly on a layout they were not written
  for, and the spider never yields an item from a page it doesn't recognise.
  Four spiders are built on this (three layouts of a test store and
  books.toscrape.com), plus a breakage matrix that crawls each spider against
  each layout.
- Done: the repair loop. The crawl pauses, a Codex agent writes a new variant
  in a clean copy of the spider, a validation gate checks it, it is hot-loaded
  through Scrapy's Remote Control, and the same run resumes. Three cases on the
  test store, about a minute and 1–3 cents each:
  - A, product pages redesigned: 566/566 correct items.
  - B, listings switch to infinite scroll: 566/566 correct items.
  - C, the price becomes members-only: the agent refuses and the crawl stops
    with `repair_failed`.
  - The whole site redesigned: six tested repairs in a row (home, categories,
    listings, products, pagination), 566/566 correct items, 11 cents.

## Layout

- `selfheal/`: the framework. Strict extraction helpers (`must`/`may`),
  dispatch between layout variants, a spider base class, the healer
  (a Scrapy extension) and the validation gate.
- `sandbox_spider/`, `sandbox_modern/`, `sandbox_scroll/`, `books_spider/`:
  spiders. Each has `variants/` (one module per layout variant, never edited
  in place) and `fixtures/` (web-poet regression fixtures). `sandbox_spider/`
  also has the item checks and the README with the crawl's intent.
- `sandbox/`: the test store (a FastAPI app), with a `no_price` layout added.
- `scripts/`: drift the test site's layout, score items against its ground
  truth, save fixtures, build the breakage matrix.
- `docs/DESIGN.md`: the design. `docs/FINDINGS.md`: what building it showed.

## Running

```
uv venv && uv pip install -e '.[test]'
pytest                                   # framework tests + fixtures, offline
scrapy crawl books -O books.jsonl        # books.toscrape.com
```

The sandbox spiders crawl the test store in `sandbox/` (vendored from
[zyte-monitoring-sandbox](https://github.com/zytedata/zyte-monitoring-sandbox),
see `sandbox/README.md` to run it on port 8765). Its layout can be switched on
the fly with `python scripts/drift.py PRESET`, and
`python scripts/matrix.py` crawls every sandbox spider under every layout.

The self-healing demo needs the `agent` extra (`uv pip install -e '.[agent]'`),
an OpenAI API key for Codex, and `uv` (scrapy-mcp runs through `uvx`):

```
python scripts/run_demo.py product-modern --reset    # A: products change layout
python scripts/run_demo.py no-price --reset          # C: price gone; must refuse
python scripts/run_demo.py infinite-scroll --reset   # B: listings switch to scrolling
python scripts/run_demo.py modern --reset            # everything changes
```

Each repair is recorded under `repairs/<id>/`: held pages, prompt, agent
events, proposal, diff, gate result, the new fixtures and metrics.

## License

Apache 2.0, see `LICENSE`.
