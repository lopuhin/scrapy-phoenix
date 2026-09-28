import attrs
import pytest
from web_poet import HttpResponse, Returns, WebPage, field

from selfheal.dispatch import ItemCheckError, Unrecognized, Variants
from selfheal.strict import LayoutMismatch, StrictMixin


@attrs.define
class Thing:
    name: str
    price: str | None = None


class ThingV1(StrictMixin, WebPage, Returns[Thing]):
    @field
    def name(self) -> str:
        return self.must_text(".v1 h1")

    @field
    def price(self) -> str | None:
        return self.may_text(".v1 .price")


class ThingV2(StrictMixin, WebPage, Returns[Thing]):
    @field
    def name(self) -> str:
        return self.must_text(".v2 .title")

    @field
    def price(self) -> str:
        return self.must_text(".v2 .cost")


class ThingCrashes(WebPage, Returns[Thing]):
    """Written the usual (non-strict) way: fails with AttributeError."""

    @field
    def name(self) -> str:
        return self.css(".v3 h1::text").get().strip()


def page(body: str) -> HttpResponse:
    return HttpResponse("https://example.com/p", body=body.encode(), encoding="utf-8")


V1_HTML = "<div class=v1><h1> One </h1></div>"
V2_HTML = "<div class=v2><span class=title>Two</span><span class=cost>9</span></div>"


def check(item: Thing) -> None:
    if item.price is not None and float(item.price) <= 0:
        raise ItemCheckError("price", "not positive")


@pytest.fixture
def variants() -> Variants:
    v = Variants(checks={Thing: check})
    v.register(ThingV1)
    v.register(ThingV2)
    return v


async def test_old_variant_still_handles_old_layout(variants):
    result = await variants.extract(Thing, page(V1_HTML))
    assert result.variant is ThingV1
    assert result.item == Thing(name="One", price=None)  # may() absent is fine


async def test_newest_variant_is_tried_first(variants):
    result = await variants.extract(Thing, page(V2_HTML))
    assert result.variant is ThingV2
    assert result.item == Thing(name="Two", price="9")


async def test_unrecognized_names_every_failing_field(variants):
    with pytest.raises(Unrecognized) as info:
        await variants.extract(Thing, page("<div class=v2><span class=title>x</span></div>"))
    refusals = {(r.variant, r.field): r for r in info.value.refusals}
    assert refusals[("ThingV2", "price")].selector == ".v2 .cost"
    assert refusals[("ThingV1", "name")].selector == ".v1 h1"
    assert ("ThingV2", "name") not in refusals  # that field was fine


async def test_item_check_refuses_item(variants):
    body = "<div class=v2><span class=title>x</span><span class=cost>-1</span></div>"
    with pytest.raises(Unrecognized) as info:
        await variants.extract(Thing, page(body))
    [v2] = [r for r in info.value.refusals if r.variant == "ThingV2"]
    assert (v2.stage, v2.field) == ("check", "price")


async def test_any_exception_is_a_refusal():
    v = Variants()
    v.register(ThingCrashes)
    with pytest.raises(Unrecognized) as info:
        await v.extract(Thing, page(V1_HTML))
    [refusal] = info.value.refusals
    assert refusal.field == "name" and "AttributeError" in refusal.error


def test_register_twice_fails(variants):
    with pytest.raises(ValueError):
        variants.register(ThingV1)


async def test_must_text_rejects_empty_element():
    p = ThingV1(response=page("<div class=v1><h1>  </h1></div>"))
    with pytest.raises(LayoutMismatch, match="no text"):
        p.name
