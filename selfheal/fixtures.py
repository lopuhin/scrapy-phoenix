"""Save web-poet fixtures for variants (regression tests for known layouts)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from web_poet import HttpResponse
from web_poet.testing import Fixture
from web_poet.utils import get_fq_class_name


def save_fixture(
    base_dir: str | Path,
    variant: type,
    response: HttpResponse,
    item: Any,
    name: str | None = None,
) -> Fixture:
    """Save ``response`` → ``item`` as a fixture of ``variant``.

    The frozen time is the item's ``dateDownloaded`` so the fixture replays the
    exact output; fixtures live under ``<base_dir>/<fully.qualified.Variant>/``.
    """
    downloaded = getattr(getattr(item, "metadata", None), "dateDownloaded", None)
    frozen = downloaded or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return Fixture.save(
        Path(base_dir, get_fq_class_name(variant)),
        inputs=[response],
        item=item,
        meta={"frozen_time": frozen},
        fixture_name=name,
    )
