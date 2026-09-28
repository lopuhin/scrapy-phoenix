"""Content-based routing between layout variants (``docs/DESIGN.md`` §4.2, §5).

Variants are web-poet page objects grouped by the item class they return. For a
response, variants are tried newest first; the first whose extraction completes
*and* whose item passes the item check wins. If none does, :class:`Unrecognized`
carries the evidence of why each variant refused the page.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import re
import warnings
from collections.abc import Callable
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any

from scrapy.http import Response
from web_poet import HttpResponse, HttpResponseHeaders, ItemPage
from web_poet.fields import get_fields_dict
from web_poet.pages import get_item_cls

from .strict import LayoutMismatch

ItemCheck = Callable[[Any], None]


class ItemCheckError(Exception):
    """Raised by an item check: the item is not acceptable for delivery."""

    def __init__(self, field: str, message: str) -> None:
        self.field = field
        self.message = message
        super().__init__(f"{field}: {message}")


@dataclass
class Refusal:
    """Why one variant refused one page."""

    variant: str
    stage: str  # "extract" | "check"
    field: str | None
    error: str
    selector: str | None = None

    def __str__(self) -> str:
        where = f"{self.variant}.{self.field}" if self.field else self.variant
        return f"{where} [{self.stage}]: {self.error}"


class Unrecognized(Exception):
    """No variant produced an acceptable item for a page."""

    def __init__(self, item_cls: type, url: str, refusals: list[Refusal]) -> None:
        self.item_cls = item_cls
        self.url = url
        self.refusals = refusals
        lines = "\n  ".join(str(r) for r in refusals) or "no variants registered"
        super().__init__(f"no {item_cls.__name__} variant accepts {url}:\n  {lines}")


@dataclass
class Extracted:
    item: Any
    variant: type[ItemPage]


def to_web_poet(response: Response | HttpResponse) -> HttpResponse:
    if isinstance(response, HttpResponse):
        return response
    return HttpResponse(
        url=response.url,
        body=response.body,
        status=response.status,
        headers=HttpResponseHeaders.from_bytes_dict(response.headers),
    )


def build_page(cls: type[ItemPage], response: HttpResponse) -> ItemPage:
    """The single place page objects are instantiated (phase 0: response only)."""
    return cls(response=response)  # type: ignore[call-arg]


def _describe_error(exc: BaseException) -> tuple[str, str | None]:
    selector = exc.selector if isinstance(exc, LayoutMismatch) else None
    if isinstance(exc, LayoutMismatch):
        return str(exc), selector
    return f"{type(exc).__name__}: {exc}", None


async def _explain(page: ItemPage, exc: Exception) -> list[Refusal]:
    """Evaluate fields one by one to name every field that fails on this page."""
    variant = type(page).__qualname__
    refusals = []
    for name in get_fields_dict(type(page)):
        try:
            value = getattr(page, name)
            if inspect.isawaitable(value):
                await value
        except Exception as field_exc:
            error, selector = _describe_error(field_exc)
            refusals.append(Refusal(variant, "extract", name, error, selector))
    if not refusals:  # failed outside any single field (e.g. item construction)
        error, selector = _describe_error(exc)
        refusals.append(Refusal(variant, "extract", None, error, selector))
    return refusals


def _natural_key(name: str) -> list[Any]:
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", name)]


@dataclass
class Variants:
    """Ordered variants per item class; later registrations are tried first."""

    checks: dict[type, ItemCheck] = field(default_factory=dict)
    _variants: dict[type, list[type[ItemPage]]] = field(default_factory=dict)

    def register(self, cls: type[ItemPage]) -> None:
        item_cls = get_item_cls(cls)
        if item_cls is None:
            raise TypeError(f"{cls!r} does not declare the item class it returns")
        bucket = self._variants.setdefault(item_cls, [])
        if cls in bucket:
            raise ValueError(f"{cls.__qualname__} is already registered")
        bucket.append(cls)

    def register_module(self, module: ModuleType) -> list[type[ItemPage]]:
        """Register the page objects *defined* in ``module``, in definition order."""
        found = [
            obj
            for _, obj in inspect.getmembers(module, inspect.isclass)
            if obj.__module__ == module.__name__
            and issubclass(obj, ItemPage)
            and not inspect.isabstract(obj)
        ]
        found.sort(key=lambda c: inspect.getsourcelines(c)[1])
        for cls in found:
            self.register(cls)
        return found

    def register_package(self, package: str) -> None:
        """Register every module of a variants package, oldest (natural sort) first."""
        pkg = importlib.import_module(package)
        names = sorted(
            (m.name for m in pkgutil.iter_modules(pkg.__path__)), key=_natural_key
        )
        for name in names:
            self.register_module(importlib.import_module(f"{package}.{name}"))

    def for_item(self, item_cls: type) -> list[type[ItemPage]]:
        return list(self._variants.get(item_cls, []))

    def describe(self) -> dict[str, list[str]]:
        return {
            item_cls.__name__: [c.__qualname__ for c in classes]
            for item_cls, classes in self._variants.items()
        }

    async def try_variant(
        self, cls: type[ItemPage], response: Response | HttpResponse
    ) -> tuple[Any | None, list[Refusal]]:
        """Run one variant on one page: ``(item, [])`` or ``(None, refusals)``."""
        page = build_page(cls, to_web_poet(response))
        try:
            item = await page.to_item()
        except Exception as exc:
            return None, await _explain(page, exc)
        check = self.checks.get(get_item_cls(cls))
        if check is not None:
            try:
                check(item)
            except Exception as exc:
                fld = exc.field if isinstance(exc, ItemCheckError) else None
                msg = exc.message if isinstance(exc, ItemCheckError) else repr(exc)
                return None, [Refusal(cls.__qualname__, "check", fld, msg)]
        return item, []

    async def extract(
        self, item_cls: type, response: Response | HttpResponse
    ) -> Extracted:
        refusals: list[Refusal] = []
        for cls in reversed(self._variants.get(item_cls, [])):
            item, why = await self.try_variant(cls, response)
            if item is not None:
                return Extracted(item, cls)
            refusals.extend(why)
        raise Unrecognized(item_cls, response.url, refusals)


# web-poet builds all field coroutines before awaiting them, so a field raising
# during to_item() leaks the others as "never awaited". Harmless for us (we treat
# the exception as a refusal); a web-poet fork could avoid creating them.
warnings.filterwarnings(
    "ignore", message=r"coroutine .* was never awaited", category=RuntimeWarning
)
