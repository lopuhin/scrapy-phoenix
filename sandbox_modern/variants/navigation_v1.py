"""Dashboard (home) and category pages, sandbox ``layout_modern``.

Pagination is a pair of buttons with ``onclick`` handlers around a
``PAGE x / y`` label: there are no ``<a>`` links, but the label proves where
the listing ends (``docs/DESIGN.md`` §4.3 case 2).
"""

import re

from web_poet import field
from zyte_common_items import ProbabilityRequest, ProductNavigationPage, Request

from selfheal.strict import LayoutMismatch, NavigationMismatch, StrictMixin


class DashboardPageV1(StrictMixin, ProductNavigationPage):
    @field
    def subCategories(self) -> list[ProbabilityRequest]:
        stream = self.must(".category-stream")
        return [
            ProbabilityRequest(url=self.response.urljoin(h))
            for h in self.must(".stream-item a.btn-explore::attr(href)", root=stream).getall()
        ]


class CategoryPageV1(StrictMixin, ProductNavigationPage):
    def _page_label(self) -> tuple[int, int]:
        label = self.must_text(".control-panel > span")
        match = re.fullmatch(r"PAGE (\d+) / (\d+)", label)
        if not match:
            raise LayoutMismatch(".control-panel > span", f"unexpected label {label!r}")
        return int(match.group(1)), int(match.group(2))

    @field
    def categoryName(self) -> str:
        return self.must_text("h1")

    @field
    def subCategories(self) -> list[ProbabilityRequest] | None:
        hrefs = self.may(".tags-cloud a::attr(href)").getall()
        return [ProbabilityRequest(url=self.response.urljoin(h)) for h in hrefs] or None

    @field
    def items(self) -> list[ProbabilityRequest] | None:
        body = self.must(".inventory-table table tbody")
        hrefs = [
            self.must("a[href*='/product/']::attr(href)", root=tr).get()
            for tr in self.may("tr", root=body)
        ]
        return [ProbabilityRequest(url=self.response.urljoin(h)) for h in hrefs] or None

    @field
    def pageNumber(self) -> int | None:
        page, _ = self._page_label()
        return page if self.items else None

    @field
    def nextPage(self) -> Request | None:
        page, total = self._page_label()
        if not self.items:
            return None
        forward = [
            b for b in self.may(".control-panel > button")
            if re.search(rf"\?page={page + 1}'", b.attrib.get("onclick", ""))
        ]
        if page < total and not forward:
            raise NavigationMismatch(".control-panel", f"page {page} of {total} has no forward button")
        if page >= total and forward:
            raise NavigationMismatch(".control-panel", f"last page {page} has a forward button")
        if not forward:
            return None
        return Request(url=self.response.urljoin(f"?page={page + 1}"))
