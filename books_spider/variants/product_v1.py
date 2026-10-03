"""Book page."""

import re

from web_poet import field
from zyte_common_items import AggregateRating, Breadcrumb, Image, ProductPage

from selfheal.strict import LayoutMismatch, StrictMixin

_STARS = {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}
_CURRENCIES = {"£": "GBP"}


class BookPageV1(StrictMixin, ProductPage):
    def _price(self) -> tuple[str, str]:
        text = self.must_text("article.product_page .product_main p.price_color")
        match = re.fullmatch(r"(\D)(\d+\.\d{2})", text)
        if not match or match.group(1) not in _CURRENCIES:
            raise LayoutMismatch("p.price_color", f"unexpected price {text!r}")
        return _CURRENCIES[match.group(1)], match.group(2)

    def _info(self) -> dict[str, str]:
        table = self.must("article.product_page table.table")
        return {
            self.must_text("th", root=tr): self.must_text("td", root=tr)
            for tr in self.must("tr", root=table)
        }

    @field
    def name(self) -> str:
        return self.must_text("article.product_page .product_main h1")

    @field
    def price(self) -> str:
        return self._price()[1]

    @field
    def currency(self) -> str:
        return self._price()[0]

    @field
    def currencyRaw(self) -> str:
        return self.must_text("article.product_page .product_main p.price_color")[0]

    @field
    def availability(self) -> str:
        box = self.must("article.product_page .product_main p.availability")
        classes = box.attrib.get("class", "").split()
        if "instock" in classes:
            return "InStock"
        if "outofstock" in classes:
            return "OutOfStock"
        raise LayoutMismatch("p.availability", f"has unknown classes {classes}")

    @field
    def aggregateRating(self) -> AggregateRating:
        stars = self.must("article.product_page .product_main p.star-rating")
        words = [c for c in stars.attrib.get("class", "").split() if c in _STARS]
        if len(words) != 1:
            raise LayoutMismatch("p.star-rating", f"has no single star class: {stars.attrib}")
        return AggregateRating(ratingValue=float(_STARS[words[0]]), bestRating=5.0)

    @field
    def description(self) -> str | None:
        return self.may_text("article.product_page #product_description + p")

    @field
    def sku(self) -> str:
        upc = self._info().get("UPC")
        if not upc:
            raise LayoutMismatch("table.table", "has no UPC row")
        return upc

    @field
    def mainImage(self) -> Image:
        src = self.must("#product_gallery img::attr(src)").get()
        return Image(url=self.response.urljoin(src))

    @field
    def images(self) -> list[Image]:
        return [self.mainImage]

    @field
    def breadcrumbs(self) -> list[Breadcrumb]:
        trail = self.must("ul.breadcrumb")
        return [
            Breadcrumb(name=self.must_text(root=a), url=self.response.urljoin(a.attrib["href"]))
            for a in self.must("li a", root=trail)
        ]
