"""Home, category pages and product-card fragments, ``layout_infinite_scroll``.

Category pages render only page 1 (the server ignores ``?page=``) and load the
rest from ``/partials/products?category_id=<id>&page=N`` as JavaScript scrolls.
Nothing in the HTML links to those fragments, so this variant *probes*
(``docs/DESIGN.md`` §4.3 case 3): it requests page N+1 until a fragment comes
back empty, which proves the end. The framework's progress check refuses a
fragment that repeats the previous page's products.

(The page also embeds ``const totalPages = N`` in a script, which would allow
proving the end without probing — case 2. We probe on purpose here.)
"""

import re
from urllib.parse import parse_qs, urlparse

from web_poet import field
from zyte_common_items import ProbabilityRequest, ProductNavigationPage, Request

from sandbox_spider.variants import navigation_v1
from selfheal.strict import LayoutMismatch, StrictMixin


class HomePageV1(navigation_v1.HomePageV1):
    pass


def _fragment_url(response_url: str, category_id: str, page: int) -> str:
    base = response_url.split("/sandbox-store/")[0]
    return f"{base}/sandbox-store/partials/products?category_id={category_id}&page={page}"


class ScrollCategoryPageV1(StrictMixin, ProductNavigationPage):
    def _category_id(self) -> str:
        match = re.search(r"/category/([^/?#]+)", str(self.response.url))
        if not match:
            raise LayoutMismatch("url", "has no /category/<id>")
        return match.group(1)

    @field
    def categoryName(self) -> str:
        return self.must_text("h1")

    @field
    def subCategories(self) -> list[ProbabilityRequest] | None:
        hrefs = self.may(".grid-4 .card a::attr(href)").getall()
        return [ProbabilityRequest(url=self.response.urljoin(h)) for h in hrefs] or None

    @field
    def items(self) -> list[ProbabilityRequest] | None:
        grid = self.must("#product-grid")
        hrefs = self.may(".card a::attr(href)", root=grid).getall()
        return [ProbabilityRequest(url=self.response.urljoin(h)) for h in hrefs] or None

    @field
    def pageNumber(self) -> int | None:
        return 1 if self.items else None

    @field
    def nextPage(self) -> Request | None:
        if not self.items:
            return None
        return Request(url=_fragment_url(str(self.response.url), self._category_id(), 2))


class ProductCardsFragmentV1(StrictMixin, ProductNavigationPage):
    """An HTML fragment that is nothing but product cards (or empty)."""

    def _query(self) -> tuple[str, int]:
        query = parse_qs(urlparse(str(self.response.url)).query)
        if "category_id" not in query or "page" not in query:
            raise LayoutMismatch("url", "is not a product-cards fragment URL")
        return query["category_id"][0], int(query["page"][0])

    @field
    def items(self) -> list[ProbabilityRequest] | None:
        top_level = self.may("body > *")
        not_cards = [e for e in top_level if "product-card" not in e.attrib.get("class", "").split()]
        if not_cards:
            raise LayoutMismatch("body > *", f"fragment has non-card elements: <{not_cards[0].root.tag}>")
        hrefs = [self.must("a::attr(href)", root=card).get() for card in top_level]
        return [ProbabilityRequest(url=self.response.urljoin(h)) for h in hrefs] or None

    @field
    def pageNumber(self) -> int:
        return self._query()[1]

    @field
    def nextPage(self) -> Request | None:
        if not self.items:  # an empty fragment proves the end
            return None
        category_id, page = self._query()
        return Request(url=_fragment_url(str(self.response.url), category_id, page + 1))
