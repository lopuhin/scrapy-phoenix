"""Product "spec sheet" page, sandbox ``layout_modern``."""

import re

from web_poet import field
from zyte_common_items import (
    AdditionalProperty,
    AggregateRating,
    Breadcrumb,
    Image,
    ProductPage,
)

from selfheal.strict import LayoutMismatch, StrictMixin

_AMOUNT = re.compile(r"^\d+(?:\.\d+)?$")


def _amount(text: str, selector: str) -> str:
    if not _AMOUNT.match(text):
        raise LayoutMismatch(selector, f"is not an amount: {text!r}")
    return text


class ProductPageV1(StrictMixin, ProductPage):
    def _attributes(self) -> dict[str, str]:
        table = self.must(".spec-sheet .technical-data table")
        rows = {}
        for tr in self.may("tr", root=table):
            key, value = (self.must_text(root=td) for td in self.must("td", root=tr)[:2])
            rows[key] = value
        return rows

    @field
    def name(self) -> str:
        return self.must_text(".spec-sheet .data-column h1")

    @field
    def description(self) -> str:
        return self.must_text(".spec-sheet .data-column > p")

    @field
    def price(self) -> str:
        return _amount(self.must_text("#price-container #price-val"), "#price-val")

    @field
    def currency(self) -> str:
        text = self.must_text("#price-container .cost-display > span:not(#price-val)")
        if not re.fullmatch(r"[A-Z]{3}", text):
            raise LayoutMismatch(".cost-display > span", f"is not a currency code: {text!r}")
        return text

    @field
    def currencyRaw(self) -> str:
        return self.currency

    @field
    def regularPrice(self) -> str | None:
        was = self.must("#price-container #was-price-val")  # rendered, hidden when no discount
        text = _text_or_none(was)
        if text is None:
            return None
        match = re.fullmatch(r"PREVIOUSLY:\s*(\S+)", text)
        if not match:
            raise LayoutMismatch("#was-price-val", f"unexpected text {text!r}")
        return _amount(match.group(1), "#was-price-val")

    @field
    def availability(self) -> str:
        status = self.must("#availability-section .status-indicator")
        classes = status.attrib.get("class", "").split()
        if "online" in classes:
            return "InStock"
        if "offline" in classes:
            return "OutOfStock"
        raise LayoutMismatch(".status-indicator", f"has unknown classes {classes}")

    @field
    def aggregateRating(self) -> AggregateRating | None:
        panel = self.must(".technical-data .metrics-panel")
        rating = float(self.must_text(".metric-score span", root=panel))
        reviews = int(self.must_text(".metric-volume span", root=panel))
        if rating == 0 and reviews == 0:
            return None
        return AggregateRating(ratingValue=rating, bestRating=5.0, reviewCount=reviews)

    @field
    def mainImage(self) -> Image:
        return Image(url=self.response.urljoin(self.must("#main-image::attr(src)").get()))

    @field
    def images(self) -> list[Image]:
        return [self.mainImage]

    @field
    def breadcrumbs(self) -> list[Breadcrumb]:
        trail = self.must(".nav-path")
        return [
            Breadcrumb(name=self.must_text(root=a), url=self.response.urljoin(a.attrib["href"]))
            for a in self.must("a", root=trail)
        ]

    @field
    def brand(self) -> str | None:
        return self._attributes().get("Brand")

    @field
    def color(self) -> str | None:
        return self._attributes().get("Color")

    @field
    def additionalProperties(self) -> list[AdditionalProperty] | None:
        props = [
            AdditionalProperty(name=k, value=v)
            for k, v in self._attributes().items()
            if k not in ("Brand", "Color")
        ]
        return props or None

    @field
    def productId(self) -> str:
        match = re.search(r"/product/([^/?#]+)", str(self.response.url))
        if not match:
            raise LayoutMismatch("url", "has no /product/<id>")
        return match.group(1)


def _text_or_none(sel) -> str | None:
    text = " ".join(sel[0].xpath("string()").get().split())
    return text or None
