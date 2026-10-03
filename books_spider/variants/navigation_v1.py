"""Catalogue listing pages (home, "All products", categories).

Proving the last page (``docs/DESIGN.md`` §4.3):

- with a pager, ``Page x of y`` says where the listing ends (case 1);
- single-page categories have no pager, only "N results": the page must then
  list exactly N books (case 2). More than a page's worth of results without a
  pager is a mismatch, not a last page.
"""

import re

from web_poet import field
from zyte_common_items import ProbabilityRequest, ProductNavigationPage, Request

from selfheal.strict import LayoutMismatch, NavigationMismatch, StrictMixin


class CatalogueListingV1(StrictMixin, ProductNavigationPage):
    def _books(self):
        section = self.must("#default .page_inner section")
        return self.may("ol.row > li article.product_pod", root=section)

    def _result_count(self) -> int:
        text = self.must_text("#default form.form-horizontal")
        match = re.match(r"(\d+) results?\b", text)
        if not match:
            raise LayoutMismatch("form.form-horizontal", f"unexpected results text {text!r}")
        return int(match.group(1))

    def _pager(self) -> tuple[int, int] | None:
        if not self.may("ul.pager"):
            return None
        label = self.must_text("ul.pager li.current")
        match = re.fullmatch(r"Page (\d+) of (\d+)", label)
        if not match:
            raise LayoutMismatch("ul.pager li.current", f"unexpected label {label!r}")
        return int(match.group(1)), int(match.group(2))

    @field
    def categoryName(self) -> str:
        return self.must_text("#default .page-header h1")

    @field
    def subCategories(self) -> list[ProbabilityRequest] | None:
        # The sidebar is on every listing; only the root listing "owns" it.
        if self.must_text("ul.breadcrumb li.active") != "All products":
            return None
        links = self.must(".side_categories ul.nav-list > li > ul a::attr(href)").getall()
        return [ProbabilityRequest(url=self.response.urljoin(h)) for h in links]

    @field
    def items(self) -> list[ProbabilityRequest]:
        return [
            ProbabilityRequest(url=self.response.urljoin(self.must("h3 a::attr(href)", root=book).get()))
            for book in self._books()
        ]

    @field
    def pageNumber(self) -> int:
        pager = self._pager()
        return pager[0] if pager else 1

    @field
    def nextPage(self) -> Request | None:
        count, books, pager = self._result_count(), len(self._books()), self._pager()
        if pager is None:
            if books != count:
                raise NavigationMismatch(
                    "ul.pager", f"no pager, but {count} results and {books} books listed"
                )
            return None
        page, total = pager
        next_href = self.may("ul.pager li.next a::attr(href)").get()
        if page < total and next_href is None:
            raise NavigationMismatch("ul.pager li.next", f"page {page} of {total} has no next link")
        if page == total and next_href is not None:
            raise NavigationMismatch("ul.pager li.next", f"last page {page} has a next link")
        return Request(url=self.response.urljoin(next_href)) if next_href else None
