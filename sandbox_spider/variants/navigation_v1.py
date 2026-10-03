"""Home and category pages, sandbox ``layout_default``.

A category page must *prove* where its pagination ends (``docs/DESIGN.md``
§4.3): this layout always renders ``.pagination`` with an active page link when
there are products, so "last page" means "the active page is the highest
numbered one", and a missing "Next" link before that is a mismatch.
"""

import re

from web_poet import field
from zyte_common_items import ProbabilityRequest, ProductNavigationPage, Request

from selfheal.strict import LayoutMismatch, NavigationMismatch, StrictMixin


class HomePageV1(StrictMixin, ProductNavigationPage):
    @field
    def subCategories(self) -> list[ProbabilityRequest]:
        return [
            ProbabilityRequest(url=self.response.urljoin(href))
            for href in self.must(".hero ~ .grid .card a::attr(href)").getall()
        ]


class CategoryPageV1(StrictMixin, ProductNavigationPage):
    def _pagination(self) -> tuple[int, int, str | None]:
        """(active page, highest page, next URL) — only valid with products."""
        box = self.must(".pagination")
        active = int(self.must_text("a.active", root=box))
        numbers = [
            int(t) for t in (_norm(a) for a in self.may("a::text", root=box).getall()) if t.isdigit()
        ]
        next_href = next(
            (a.attrib["href"] for a in self.may("a", root=box) if "Next" in a.xpath("string()").get()),
            None,
        )
        return active, max(numbers), next_href

    @field
    def categoryName(self) -> str:
        return self.must_text("h1")

    @field
    def subCategories(self) -> list[ProbabilityRequest] | None:
        hrefs = self.may(".grid-4 .card a::attr(href)").getall()
        return [ProbabilityRequest(url=self.response.urljoin(h)) for h in hrefs] or None

    @field
    def items(self) -> list[ProbabilityRequest] | None:
        grid = self.must(".grid-3")
        hrefs = self.may(".card a::attr(href)", root=grid).getall()
        return [ProbabilityRequest(url=self.response.urljoin(h)) for h in hrefs] or None

    @field
    def pageNumber(self) -> int | None:
        if not self.items:
            return None
        return self._pagination()[0]

    @field
    def nextPage(self) -> Request | None:
        if not self.items:
            return None
        active, highest, next_href = self._pagination()
        if active < highest and next_href is None:
            raise NavigationMismatch(".pagination", f"page {active} of {highest} has no Next link")
        if active == highest and next_href is not None:
            raise NavigationMismatch(".pagination", f"last page {active} has a Next link")
        if active > highest:
            raise LayoutMismatch(".pagination a.active", f"page {active} beyond highest {highest}")
        return Request(url=self.response.urljoin(next_href)) if next_href else None


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
