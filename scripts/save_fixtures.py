"""Save baseline fixtures for the sandbox spider's variants.

Usage: python scripts/save_fixtures.py [--base http://127.0.0.1:8765] [--out sandbox_spider/fixtures]

Run against the sandbox in its default layout. Cases are chosen from the
sandbox's ground truth to cover *normal* page-to-page variation (docs/DESIGN.md
§8): discount / no discount, out of stock, no rating, no brand, single-page and
multi-page listings (first, middle, last page), top-level category, home.
Every page must be accepted by the current variants; the saved output is the
baseline a human reviews before committing.
"""

import argparse
import asyncio
import json
import shutil
import sys
import urllib.request
from pathlib import Path

from web_poet import HttpResponse, HttpResponseHeaders
from zyte_common_items import Product, ProductNavigation

from sandbox_spider.items import check_navigation, check_product
from selfheal.dispatch import Variants
from selfheal.fixtures import save_fixture

sys.path.insert(0, str(Path(__file__).parent))
from drift import apply as apply_sandbox  # noqa: E402

PER_PAGE = 12


def get(url: str) -> HttpResponse:
    with urllib.request.urlopen(url) as r:
        headers = HttpResponseHeaders.from_bytes_dict(
            {k.encode(): v.encode() for k, v in r.headers.items()}
        )
        return HttpResponse(url=url, body=r.read(), status=r.status, headers=headers)


def data(base: str, path: str) -> dict:
    with urllib.request.urlopen(f"{base}/sandbox-store/data/{path}") as r:
        return json.load(r)


def pick_cases(base: str) -> tuple[dict[str, str], dict[str, str]]:
    store = f"{base}/sandbox-store"
    top = [f"cat_{i}" for i in range(8)]
    subs: list[dict] = []
    for cat in top:
        try:
            subs += [data(base, f"category/{s['id']}") for s in data(base, f"category/{cat}")["subcategories"]]
        except Exception:
            break
    multi = max(subs, key=lambda s: len(s["products"]))
    pages = -(-len(multi["products"]) // PER_PAGE)
    nav = {
        "home": f"{store}/",
        "top-category": f"{store}/category/{top[0]}",
        "multi-first": f"{store}/category/{multi['id']}",
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
        "no-attributes": lambda p: not p["attributes"],
    }
    prod = {}
    for case, pred in wanted.items():
        match = next((p for p in products if pred(p)), None)
        if match is None:
            print(f"  (no product for case {case!r} in this catalogue)")
            continue
        prod[case] = f"{store}/product/{match['id']}"
    return nav, prod


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8765")
    parser.add_argument("--out", default="sandbox_spider/fixtures")
    args = parser.parse_args()
    variants = Variants(checks={Product: check_product, ProductNavigation: check_navigation})
    variants.register_package("sandbox_spider.variants")
    shutil.rmtree(args.out, ignore_errors=True)
    apply_sandbox(args.base, {"ITEMS_PER_PAGE": str(PER_PAGE)})
    nav, prod = pick_cases(args.base)
    responses = {url: get(url) for cases in (nav, prod) for url in cases.values()}
    # The default catalogue has no single-page category, so capture one with a
    # bigger page size (the layout is the same; only the page count changes).
    smallest = min(
        (s for c in range(4) for s in data(args.base, f"category/cat_{c}")["subcategories"]),
        key=lambda s: len(data(args.base, f"category/{s['id']}")["products"]),
    )
    apply_sandbox(args.base, {"ITEMS_PER_PAGE": "20"})
    try:
        single = f"{args.base}/sandbox-store/category/{smallest['id']}"
        nav["single-page"] = single
        responses[single] = get(single)
    finally:
        apply_sandbox(args.base, {"ITEMS_PER_PAGE": str(PER_PAGE)})
    for item_cls, cases in ((ProductNavigation, nav), (Product, prod)):
        for case, url in cases.items():
            response = responses[url]
            result = await variants.extract(item_cls, response)  # raises if unrecognised
            fixture = save_fixture(args.out, result.variant, response, result.item, name=case)
            print(f"{result.variant.__qualname__:16} {case:14} {url}  → {fixture.path}")


if __name__ == "__main__":
    asyncio.run(main())
