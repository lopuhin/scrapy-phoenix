"""Score crawled sandbox products against the sandbox's ground-truth JSON.

Usage: python scripts/score.py output/items.jsonl [--base http://127.0.0.1:8765]

Ground truth comes from ``/sandbox-store/data/product/{id}``, which the agent
never sees; this is for evaluating our own spiders and repairs.
"""

import argparse
import asyncio
import json
from collections import Counter
from decimal import Decimal

import aiohttp


def expected(truth: dict) -> dict:
    attrs = dict(truth["attributes"])
    rating = None
    if truth["rating"] or truth["reviews_count"]:
        rating = (truth["rating"], truth["reviews_count"])
    return {
        "name": truth["name"],
        "price": Decimal(str(truth["price"])),
        "regularPrice": Decimal(str(truth["original_price"])) if truth["original_price"] else None,
        "currency": truth["currency"],
        "availability": "InStock" if truth["in_stock"] else "OutOfStock",
        "aggregateRating": rating,
        "brand": attrs.pop("Brand", None),
        "color": attrs.pop("Color", None),
        "additionalProperties": attrs or None,
        "breadcrumbs": ["Home"] + [b["name"] for b in truth["breadcrumbs"]],
    }


def actual(item: dict) -> dict:
    rating = item.get("aggregateRating")
    props = item.get("additionalProperties")
    return {
        "name": item.get("name"),
        "price": Decimal(item["price"]) if item.get("price") else None,
        "regularPrice": Decimal(item["regularPrice"]) if item.get("regularPrice") else None,
        "currency": item.get("currency"),
        "availability": item.get("availability"),
        "aggregateRating": (rating["ratingValue"], rating["reviewCount"]) if rating else None,
        "brand": (item.get("brand") or {}).get("name"),
        "color": item.get("color"),
        "additionalProperties": {p["name"]: p["value"] for p in props} if props else None,
        "breadcrumbs": [b["name"] for b in item.get("breadcrumbs") or []],
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("items")
    parser.add_argument("--base", default="http://127.0.0.1:8765")
    parser.add_argument("--full-only", action="store_true", help="print only N fully correct")
    args = parser.parse_args()
    items = [json.loads(line) for line in open(args.items)]
    if not items:
        print("—" if args.full_only else "0 items")
        return
    wrong: Counter[str] = Counter()
    examples: dict[str, tuple] = {}
    async with aiohttp.ClientSession() as http:
        sem = asyncio.Semaphore(16)

        async def truth_for(pid: str) -> dict:
            async with sem, http.get(f"{args.base}/sandbox-store/data/product/{pid}") as r:
                return await r.json()

        truths = await asyncio.gather(*(truth_for(i["productId"]) for i in items))
    fully_correct = 0
    for item, truth in zip(items, truths):
        exp, act = expected(truth), actual(item)
        bad = [key for key in exp if exp[key] != act[key]]
        fully_correct += not bad
        for key in bad:
            wrong[key] += 1
            examples.setdefault(key, (item["url"], exp[key], act[key]))
    if args.full_only:
        print(f"{fully_correct}/{len(items)}")
        return
    print(f"{len(items)} items, {len({i['productId'] for i in items})} unique")
    for key in expected(truths[0]):
        print(f"  {key:22} {len(items) - wrong[key]:5}/{len(items)} correct")
    for key, (url, exp, act) in examples.items():
        print(f"  e.g. {key}: {url}\n       expected {exp!r}\n       got      {act!r}")


if __name__ == "__main__":
    asyncio.run(main())
