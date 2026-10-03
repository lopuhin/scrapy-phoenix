"""Spider base class wiring callbacks to the variant dispatcher."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar

import scrapy
from scrapy.http import Response

from .dispatch import ItemCheck, Unrecognized, Variants

_LOG_UNRECOGNIZED_MAX = 10


class SelfHealingSpider(scrapy.Spider):
    """Callbacks call :meth:`extract` instead of parsing responses themselves.

    Subclasses set ``variants_package`` (a package whose modules define page
    objects, one module per layout variant) and ``item_checks`` (item class →
    check function raising :class:`~selfheal.dispatch.ItemCheckError`).
    """

    variants_package: ClassVar[str]
    item_checks: ClassVar[dict[type, ItemCheck]] = {}

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.variants = Variants(checks=dict(self.item_checks))
        self.variants.register_package(self.variants_package)
        self._unrecognized_logged = 0

    async def extract(
        self, item_cls: type, response: Response, previous: Any | None = None
    ) -> Any | None:
        """Return the item from the first variant that accepts ``response``.

        Returns ``None`` when no variant does; the page then yields nothing
        (never an item from an unrecognised page). Pass ``previous`` (the
        navigation item whose ``nextPage`` led here) to check that pagination
        makes progress.
        """
        stats = self.crawler.stats
        try:
            result = await self.variants.extract(item_cls, response, previous)
        except Unrecognized as exc:
            stats.inc_value(f"selfheal/unrecognized/{item_cls.__name__}")
            if not stats.get_value("selfheal/first_unrecognized"):
                stats.set_value("selfheal/first_unrecognized", str(exc))
            if self._unrecognized_logged < _LOG_UNRECOGNIZED_MAX:
                self._unrecognized_logged += 1
                self.logger.warning(str(exc))
            else:
                self.logger.debug(str(exc))
            await self.on_unrecognized(exc, response)
            return None
        stats.inc_value(f"selfheal/variant/{result.variant.__qualname__}")
        return result.item

    def closed(self, reason: str) -> None:
        """With ``SELFHEAL_STATS_FILE`` set, dump final stats as JSON there."""
        path = self.settings.get("SELFHEAL_STATS_FILE")
        if path:
            stats = dict(self.crawler.stats.get_stats(), finish_reason=reason)
            Path(path).write_text(json.dumps(stats, default=str, indent=1, sort_keys=True))

    async def on_unrecognized(self, exc: Unrecognized, response: Response) -> None:
        """Hand the page to the healer (``selfheal.healer``) when it is enabled."""
        healer = getattr(self, "healer", None)
        if healer is not None:
            healer.hold(exc, response)

