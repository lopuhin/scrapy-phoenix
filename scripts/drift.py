"""Flip the sandbox site's layout on cue.

Usage:
    python scripts/drift.py PRESET [--base http://127.0.0.1:8765]
    python scripts/drift.py --show

The admin endpoint requires every setting on each update, so the current values
are read from the admin form first and only the preset's keys are changed.
Changes apply to the next request; no sandbox restart is needed.
"""

import argparse
import sys
import urllib.parse
import urllib.request

from parsel import Selector

PRESETS: dict[str, dict[str, str]] = {
    "default": {"ACTIVE_LAYOUT": "layout_default", "AB_TEST_RATIO": "0.0", "ITEMS_PER_PAGE": "12",
                "PRICE_SCALE": "1.0"},
    # Case A: product pages switch to the "modern" design, listings unchanged.
    "product-modern": {
        "ACTIVE_LAYOUT": "layout_default",
        "AB_TEST_TARGET": "products",
        "AB_TEST_LAYOUT": "layout_modern",
        "AB_TEST_RATIO": "1.0",
    },
    # Case A while every price went up 13%: the fixtures' values are stale.
    "product-modern-repriced": {
        "ACTIVE_LAYOUT": "layout_default",
        "AB_TEST_TARGET": "products",
        "AB_TEST_LAYOUT": "layout_modern",
        "AB_TEST_RATIO": "1.0",
        "PRICE_SCALE": "1.13",
    },
    # Case A, half the products: both variants must coexist.
    "product-modern-half": {
        "ACTIVE_LAYOUT": "layout_default",
        "AB_TEST_TARGET": "products",
        "AB_TEST_LAYOUT": "layout_modern",
        "AB_TEST_RATIO": "0.5",
    },
    # Case B: listings lose pagination links; products unchanged.
    "infinite-scroll": {"ACTIVE_LAYOUT": "layout_infinite_scroll", "AB_TEST_RATIO": "0.0"},
    "load-more": {"ACTIVE_LAYOUT": "layout_load_more", "AB_TEST_RATIO": "0.0"},
    "modern": {"ACTIVE_LAYOUT": "layout_modern", "AB_TEST_RATIO": "0.0"},
    "hidden-price": {"ACTIVE_LAYOUT": "layout_hidden_price", "AB_TEST_RATIO": "0.0"},
    "variant-dom-change": {"ACTIVE_LAYOUT": "layout_variant_dom_change", "AB_TEST_RATIO": "0.0"},
    # Case C: prices only for signed-in members, everywhere (pages, cards, API).
    "no-price": {"ACTIVE_LAYOUT": "layout_no_price", "AB_TEST_RATIO": "0.0"},
}


def current_settings(base: str) -> dict[str, str]:
    html = urllib.request.urlopen(f"{base}/admin/").read().decode()
    sel = Selector(html)
    values = {i.attrib["name"]: i.attrib.get("value", "") for i in sel.css("form input[name]")}
    for select in sel.css("form select[name]"):
        chosen = select.css("option[selected]::attr(value)").get()
        values[select.attrib["name"]] = chosen or select.css("option::attr(value)").get()
    return values


def apply(base: str, overrides: dict[str, str]) -> None:
    """Update the sandbox config, keeping every setting not in ``overrides``."""
    values = current_settings(base)
    values.update(overrides)
    data = urllib.parse.urlencode(values).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(f"{base}/admin/update", data=data))
    except urllib.error.HTTPError as exc:
        sys.exit(f"update failed: {exc.code} {exc.read()[:500]!r}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("preset", nargs="?", choices=sorted(PRESETS))
    parser.add_argument("--base", default="http://127.0.0.1:8765")
    parser.add_argument("--show", action="store_true")
    args = parser.parse_args()
    values = current_settings(args.base)
    if args.show or not args.preset:
        for key in ("ACTIVE_LAYOUT", "AB_TEST_TARGET", "AB_TEST_LAYOUT", "AB_TEST_RATIO"):
            print(f"{key}={values.get(key)}")
        return
    apply(args.base, PRESETS[args.preset])
    print(f"sandbox now: {args.preset}")


if __name__ == "__main__":
    main()
