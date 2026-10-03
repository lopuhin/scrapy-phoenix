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
  through Scrapy's Remote Control, and the same run resumes. On Sol 6.1, 27
  runs over nine cases (three spiders, five kinds of site change, one with all
  prices changed too) all ended as intended, for 6–55 cents a run:
  - A, product pages redesigned: 566/566 correct items, also when every
    price changed too.
  - B, listings switch to infinite scroll: 566/566 correct items.
  - C, the price becomes members-only: the agent refuses and the crawl stops
    with `repair_failed`.
  - The whole site redesigned: four tested repairs in a row (home, categories,
    listings, products), 566/566 correct items.
  - Listings with a "Show more" button, and a second spider built for
    another layout: 566/566 correct items.

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
python scripts/run_demo.py scroll-modern --spider sandbox_modern --reset  # second spider
python scripts/batch.py -n 1                         # every case once, tallied
```

Each repair is recorded under `repairs/<id>/`: held pages, prompt, agent
events, proposal, diff, gate result, the new fixtures and metrics.

## License

Apache 2.0, see `LICENSE`.
