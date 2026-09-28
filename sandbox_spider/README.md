# Sandbox store spider

The site is `zyte-monitoring-sandbox`'s store, a fake e-commerce catalogue.
We want **every product in every subcategory**, one item per product page, as
`zyte_common_items.Product`.

What matters in each item:

- `name`, `price`, `currency` and `availability` are required; an item without
  them is useless to the consumer.
- `price` is what a customer pays today, i.e. the discounted price when there is
  a discount; `regularPrice` is the pre-discount price and is only present then.
- `brand`, `aggregateRating`, `breadcrumbs`, `mainImage` and the remaining
  attributes (`additionalProperties`) are wanted whenever the page shows them. A
  product with no reviews has no `aggregateRating`, which is normal.
- Variants (colour, size, …) are out of scope for now.

Navigation: the home page links top-level categories, which link subcategories,
which list products across numbered pages. Categories with a single page are
common. Nothing should be skipped: missing a listing page silently loses up to
a page worth of products.

Running locally: start the sandbox (`uvicorn app.main:app --port 8765` from the
sandbox repo root), then `scrapy crawl sandbox_store -O output/items.jsonl`.
Override the target with `-s SANDBOX_URL=...`.
