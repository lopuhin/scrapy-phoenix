"""No variant may take over another variant's pages with different output.

Variants are tried newest first, so a variant that accepts a page written for
another one wins it. That's fine only if it extracts exactly the same item
(e.g. two spiders sharing a layout); otherwise it's "routing theft"
(docs/DESIGN.md §5, gate check 2). This runs every variant of every spider
against every other variant's fixtures, offline.
"""

import asyncio
from pathlib import Path

import pytest
from scrapy.spiderloader import SpiderLoader
from scrapy.utils.project import get_project_settings
from web_poet.pages import get_item_cls
from web_poet.testing import Fixture
from web_poet.utils import get_fq_class_name

from selfheal.dispatch import Variants

_loader = SpiderLoader.from_settings(get_project_settings())
SPIDERS = [_loader.load(name) for name in sorted(_loader.list())]


def _variants(spider_cls) -> Variants:
    v = Variants(checks=dict(spider_cls.item_checks))
    v.register_package(spider_cls.variants_package)
    return v


def _cases():
    variants = [(cls, v) for s in SPIDERS for v in [_variants(s)] for item in v._variants for cls in v.for_item(item)]
    for spider_cls in SPIDERS:
        root = Path(spider_cls.variants_package.split(".")[0], "fixtures")
        for path in sorted(root.glob("*/*/output.json")):
            owner = path.parent.parent.name
            fixture = Fixture(path.parent)
            for cls, v in variants:
                if get_fq_class_name(cls) == owner:
                    continue
                owner_cls = next(c for c, _ in variants if get_fq_class_name(c) == owner)
                if get_item_cls(cls) is not get_item_cls(owner_cls):
                    continue
                yield pytest.param(fixture, cls, v, id=f"{get_fq_class_name(cls)}@{owner}/{path.parent.name}")


@pytest.mark.parametrize(("fixture", "cls", "variants"), list(_cases()))
def test_no_routing_theft(fixture: Fixture, cls, variants: Variants):
    # sync test: Fixture.get_output() runs its own event loop
    response = fixture.get_page(cls).response
    item, _ = asyncio.run(variants.try_variant(cls, response))
    if item is not None:
        assert fixture.get_output(cls) == fixture.get_expected_output()
