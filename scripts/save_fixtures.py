"""Save baseline fixtures for a spider's variants.

Usage: python scripts/save_fixtures.py SPIDER [--base http://127.0.0.1:8765]

Sandbox spiders flip the sandbox to their own layout first. Cases are chosen to
cover *normal* page-to-page variation (docs/DESIGN.md §8). For the sandbox they
come from ground truth: discount / no discount, out of stock, no rating, no
brand; single-page and multi-page listings (first, middle, last page),
top-level category, home. Every page must be accepted by the current variants,
and the saved output is the baseline a human reviews before committing.
Fixtures are written to ``<spider package>/fixtures/``, replacing that
directory.
"""

import argparse
import asyncio
import json
import shutil
import sys
import urllib.request
from pathlib import Path

from scrapy.spiderloader import SpiderLoader
from scrapy.utils.project import get_project_settings
from web_poet import HttpResponse, HttpResponseHeaders
from zyte_common_items import Product, ProductNavigation

from selfheal.dispatch import Variants
from selfheal.fixtures import save_fixture

sys.path.insert(0, str(Path(__file__).parent))
from drift import PRESETS, apply as apply_sandbox  # noqa: E402

PER_PAGE = 12
SANDBOX_PRESET = {
    "sandbox_store": "default",
    "sandbox_modern": "modern",
    "sandbox_scroll": "infinite-scroll",
}
BOOKS = "https://books.toscrape.com"
BOOKS_CASES = {
    ProductNavigation: {
        "home": f"{BOOKS}/",
        "all-last": f"{BOOKS}/catalogue/page-50.html",
        "single-page": f"{BOOKS}/catalogue/category/books/travel_2/index.html",
        "multi-first": f"{BOOKS}/catalogue/category/books/mystery_3/index.html",
        "multi-last": f"{BOOKS}/catalogue/category/books/mystery_3/page-2.html",
    },
    Product: {
        "with-description": f"{BOOKS}/catalogue/a-light-in-the-attic_1000/index.html",
        "no-description": f"{BOOKS}/catalogue/alice-in-wonderland-alices-adventures-in-wonderland-1_5/index.html",
    },
}


def get(url: str) -> HttpResponse:
    request = urllib.request.Request(url, headers={"User-Agent": "scrapy-self-heal fixtures"})
    with urllib.request.urlopen(request) as r:
        headers = HttpResponseHeaders.from_bytes_dict(
            {k.encode(): v.encode() for k, v in r.headers.items()}
        )
        return HttpResponse(url=url, body=r.read(), status=r.status, headers=headers)


def data(base: str, path: str) -> dict:
    with urllib.request.urlopen(f"{base}/sandbox-store/data/{path}") as r:
        return json.load(r)


def sandbox_cases(base: str, spider: str) -> dict[type, dict[str, HttpResponse]]:
    store = f"{base}/sandbox-store"
    apply_sandbox(base, PRESETS["default"] | PRESETS[SANDBOX_PRESET[spider]])
    try:
        subs: list[dict] = []
        for cat in range(8):
            try:
                children = data(base, f"category/cat_{cat}")["subcategories"]
            except urllib.error.HTTPError:
                break
            subs += [data(base, f"category/{s['id']}") for s in children]
        multi = max(subs, key=lambda s: len(s["products"]))
        pages = -(-len(multi["products"]) // PER_PAGE)
        nav = {
            "home": f"{store}/",
            "top-category": f"{store}/category/cat_0",
            "multi-first": f"{store}/category/{multi['id']}",
        }
        if spider == "sandbox_scroll":
            fragment = f"{store}/partials/products?category_id={multi['id']}&page="
            nav |= {
                "fragment-middle": f"{fragment}{pages // 2 + 1}",
                "fragment-last": f"{fragment}{pages}",
                "fragment-past-end": f"{fragment}{pages + 1}",
            }
        else:
            nav |= {
                "multi-middle": f"{store}/category/{multi['id']}?page={pages // 2 + 1}",
                "multi-last": f"{store}/category/{multi['id']}?page={pages}",
            }
        products = [data(base, f"product/{p['id']}") for s in subs for p in s["products"]]
        wanted = {
            "discounted": lambda p: p["original_price"],
            "full-price": lambda p: not p["original_price"],
            "out-of-stock": lambda p: not p["in_stock"],
            "no-rating": lambda p: not p["rating"] and not p["reviews_count"],
            "rated": lambda p: p["rating"] and p["reviews_count"],
            "no-brand": lambda p: "Brand" not in p["attributes"],
        }
        prod = {
            case: f"{store}/product/{next(p for p in products if pred(p))['id']}"
            for case, pred in wanted.items()
        }
        cases = {
            ProductNavigation: {k: get(u) for k, u in nav.items()},
            Product: {k: get(u) for k, u in prod.items()},
        }
        # The default catalogue has no single-page category, so capture one with
        # a bigger page size (same layout; only the page count changes).
        smallest = min(subs, key=lambda s: len(s["products"]))
        apply_sandbox(base, {"ITEMS_PER_PAGE": "20"})
        cases[ProductNavigation]["single-page"] = get(f"{store}/category/{smallest['id']}")
    finally:
        apply_sandbox(base, PRESETS["default"])
    return cases


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("spider")
    parser.add_argument("--base", default="http://127.0.0.1:8765")
    args = parser.parse_args()
    spider_cls = SpiderLoader.from_settings(get_project_settings()).load(args.spider)
    variants = Variants(checks=dict(spider_cls.item_checks))
    variants.register_package(spider_cls.variants_package)
    out = Path(spider_cls.variants_package.split(".")[0], "fixtures")
    if args.spider == "books":
        cases = {t: {k: get(u) for k, u in c.items()} for t, c in BOOKS_CASES.items()}
    else:
        cases = sandbox_cases(args.base, args.spider)
    shutil.rmtree(out, ignore_errors=True)
    for item_cls, responses in cases.items():
        for case, response in responses.items():
            result = await variants.extract(item_cls, response)  # raises if unrecognised
            fixture = save_fixture(out, result.variant, response, result.item, name=case)
            print(f"{result.variant.__qualname__:22} {case:18} {response.url}  → {fixture.path}")


if __name__ == "__main__":
    asyncio.run(main())
