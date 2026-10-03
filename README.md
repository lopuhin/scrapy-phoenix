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
- Next: the repair loop (pause, agent, validation gate, hot-load, resume).

## Layout

- `selfheal/`: the framework. Strict extraction helpers (`must`/`may`),
  dispatch between layout variants, and a spider base class.
- `sandbox_spider/`, `sandbox_modern/`, `sandbox_scroll/`, `books_spider/`:
  spiders. Each has `variants/` (one module per layout variant, never edited
  in place) and `fixtures/` (web-poet regression fixtures). `sandbox_spider/`
  also has the item checks and the README with the crawl's intent.
- `scripts/`: drift the test site's layout, score items against its ground
  truth, save fixtures, build the breakage matrix.
- `docs/DESIGN.md`: the design. `docs/FINDINGS.md`: what building it showed.

## Running

```
uv venv && uv pip install -e '.[test]'
pytest                                   # framework tests + fixtures, offline
scrapy crawl books -O books.jsonl        # books.toscrape.com
```

The sandbox spiders crawl a local
[zyte-monitoring-sandbox](https://github.com/zytedata/zyte-monitoring-sandbox)
instance (`uvicorn app.main:app --port 8765` from its repo root). Its layout
can be switched on the fly with `python scripts/drift.py PRESET`, and
`python scripts/matrix.py` crawls every sandbox spider under every layout.

## License

Apache 2.0, see `LICENSE`.
