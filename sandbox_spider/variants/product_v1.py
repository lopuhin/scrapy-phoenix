"""Product page, sandbox ``layout_default``."""

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

_MONEY = re.compile(r"^([A-Z]{3})\s+(\d+(?:\.\d+)?)$")


def _money(text: str, selector: str) -> tuple[str, str]:
    match = _MONEY.match(text)
    if not match:
        raise LayoutMismatch(selector, f"is not '<CUR> <amount>': {text!r}")
    return match.group(1), match.group(2)


class ProductPageV1(StrictMixin, ProductPage):
    def _price_text(self) -> tuple[str, str]:
        tag = self.must(".product-info .price-tag")
        if self.may(".current-price", root=tag):
            return self.must_text(".current-price", root=tag), ".price-tag .current-price"
        return self.must_text(".product-info .price-tag"), ".price-tag"

    def _attributes(self) -> dict[str, str]:
        dl = self.must(".product-info .attributes dl")
        return {
            self.must_text(root=dt): self.must_text(root=dt.xpath("following-sibling::dd[1]"))
            for dt in self.may("dt", root=dl)
        }

    @field
    def name(self) -> str:
        return self.must_text(".product-info h1")

    @field
    def price(self) -> str:
        return _money(*self._price_text())[1]

    @field
    def currency(self) -> str:
        return _money(*self._price_text())[0]

    @field
    def currencyRaw(self) -> str:
        return self.currency

    @field
    def regularPrice(self) -> str | None:
        text = self.may_text(".product-info .price-tag .original-price")
        return _money(text, ".original-price")[1] if text else None

    @field
    def availability(self) -> str:
        status = self.must(".product-info .stock-status")
        classes = status.attrib.get("class", "").split()
        if "in-stock" in classes:
            return "InStock"
        if "out-of-stock" in classes:
            return "OutOfStock"
        raise LayoutMismatch(".stock-status", f"has unknown classes {classes}")

    @field
    def aggregateRating(self) -> AggregateRating | None:
        box = self.must(".product-info .rating-container")
        rating = float(self.must_text(".rating-text", root=box))
        reviews = int(re.sub(r"\D", "", self.must_text(".reviews", root=box)))
        if rating == 0 and reviews == 0:  # the site renders "0.0 (0 reviews)"
            return None
        return AggregateRating(ratingValue=rating, bestRating=5.0, reviewCount=reviews)

    @field
    def description(self) -> str:
        return self.must_text(".product-info > p")

    @field
    def mainImage(self) -> Image:
        src = self.must(".product-image img::attr(src)").get()
        return Image(url=self.response.urljoin(src))

    @field
    def images(self) -> list[Image]:
        return [self.mainImage]

    @field
    def breadcrumbs(self) -> list[Breadcrumb]:
        trail = self.must(".breadcrumbs")
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
