# Books to Scrape spider

<https://books.toscrape.com/> is a public demo bookshop built for scraping
practice. We want **every book**, one `zyte_common_items.Product` per book page.

- `name`, `price` (GBP), `currency`, `availability` and `sku` (the UPC) are
  required.
- `aggregateRating` is the star rating (1–5); every book has one.
- `description` is wanted when present; some books have none, which is normal.
- `breadcrumbs`, `mainImage` wanted.

Navigation: the home page lists all books (50 pages) and a sidebar of
categories. Categories range from a single page (no pager, just "N results")
to several pages ("Page 1 of 3", with a "next" link). We crawl the categories
and the full listing; duplicate book URLs are dropped by Scrapy.

This spider exists to test how well the framework handles a different site's
shapes. The site doesn't change, so it is not a breakage target.
