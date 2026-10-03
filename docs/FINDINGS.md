# Findings log

Evidence gathered while building, for the design and the talk. Newest first.

## 2026-10-03 — review follow-ups

- **Pure anchors removed everywhere.** Every `must` that only checked an element
  existed (`.breadcrumbs`, `.nav-path`, `.dashboard-header`, `.hero h1`, an empty
  `.pagination` on product-less pages) is gone. Where an anchor was telling page
  types apart, that context now lives in the selector used for extraction
  (`.hero ~ .grid .card a`). All fixtures still produce identical output.
  - **The matrices below predate this cleanup and need a re-run.** One known
    change: the default spider's category variant now accepts the scroll
    layout's product-less top-category page with identical output, so refusals
    on scroll/load-more move from top-level categories to subcategory pages.
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

Breakage matrix, 3 sandbox spiders × 8 layouts (`python scripts/matrix.py`):

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

Breakage matrix (`python scripts/matrix.py`, no healer; "fully correct" = every
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
