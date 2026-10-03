# Sandbox store (vendored)

The test site the sandbox spiders crawl: a FastAPI app serving a fake
e-commerce store whose layout and behaviour can be switched at runtime through
`/admin`. Vendored from `zyte-monitoring-sandbox` (commit `9343155`, `app/`
and `requirements.txt` only); changes for this project are made here.

```
uv venv sandbox/.venv && uv pip install --python sandbox/.venv/bin/python -r sandbox/requirements.txt
cd sandbox && .venv/bin/uvicorn app.main:app --port 8765
```

Ground truth for scoring is at `/sandbox-store/data/...`; `scripts/drift.py`
switches layouts.
