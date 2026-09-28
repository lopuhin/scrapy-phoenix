"""Strict extraction helpers: page objects that fail loudly on the wrong layout.

A page object written for one layout variant uses :meth:`StrictMixin.must` for
structure that layout guarantees and :meth:`StrictMixin.may` for content that is
legitimately absent on some pages. When a ``must`` selector matches nothing,
:class:`LayoutMismatch` is raised, which the dispatcher reads as "this page is not
mine" (see ``docs/DESIGN.md`` §4.1).
"""

from __future__ import annotations

from parsel import Selector, SelectorList


class LayoutMismatch(Exception):
    """A selector that the layout guarantees matched nothing (or matched wrongly)."""

    def __init__(self, selector: str, message: str = "matched nothing") -> None:
        self.selector = selector
        self.message = message
        super().__init__(f"{selector!r} {message}")


class NavigationMismatch(LayoutMismatch):
    """Navigation on the page contradicts itself or what the previous page implied."""


Root = Selector | SelectorList


def _norm(text: str | None) -> str:
    return " ".join((text or "").split())


class StrictMixin:
    """Mixin for web-poet page objects with a ``response`` attribute."""

    def _root(self, root: Root | None) -> Root:
        return self.response.selector if root is None else root  # type: ignore[attr-defined]

    def must(self, css: str, *, root: Root | None = None) -> SelectorList:
        """Return the non-empty ``SelectorList`` for ``css``, or raise."""
        result = self._root(root).css(css)
        if not result:
            raise LayoutMismatch(css)
        return result

    def must_text(self, css: str | None = None, *, root: Root | None = None) -> str:
        """Return the normalized text of the first match of ``css``, or raise.

        With ``css=None`` the text of ``root`` itself is returned. An element that
        exists but has no text also raises: the layout guarantees the value, not
        just the tag.
        """
        matched = self.must(css, root=root) if css is not None else self._root(root)
        if isinstance(matched, SelectorList):
            matched = matched[0] if matched else None
        text = _norm(matched.xpath("string()").get()) if matched is not None else ""
        if not text:
            raise LayoutMismatch(css or "<root>", "matched an element with no text")
        return text

    def may(self, css: str, *, root: Root | None = None) -> SelectorList:
        """Return the (possibly empty) ``SelectorList`` for ``css``."""
        return self._root(root).css(css)

    def may_text(self, css: str, *, root: Root | None = None) -> str | None:
        """Return the normalized text of the first match of ``css``, or ``None``."""
        result = self.may(css, root=root)
        if not result:
            return None
        return _norm(result[0].xpath("string()").get()) or None
