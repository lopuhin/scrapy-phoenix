"""Validation gate for a candidate variant module (``docs/DESIGN.md`` §7).

Usage::

    python -m selfheal.gate --spider sandbox_store \\
        --candidate sandbox_spider.variants.product_v2 --held repairs/<id>/held \\
        [--baseline repairs/<id>/baseline.json] [--json gate.json] \\
        [--save-fixtures repairs/<id>/fixtures]

The agent runs it while working and the healer runs it again before
hot-loading; both run it as a subprocess so candidate code can't crash or block
the crawl. Exit status 0 means every check passed.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib
import json
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from web_poet import HttpResponse, HttpResponseHeaders
from zyte_common_items import ProductNavigation
from web_poet.pages import get_item_cls
from web_poet.testing import Fixture
from web_poet.utils import get_fq_class_name

from .dispatch import Variants
from .fixtures import save_fixture

# Fields that must not be identical across held pages of different URLs:
# a variant extracting e.g. the site header instead of the product name would
# produce one constant value (check 5).
VARYING_FIELDS = ("name", "sku", "description", "items")
MIN_PAGES_FOR_VARIATION = 3


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    problems: list[str] = field(default_factory=list)


# -- held pages -----------------------------------------------------------------


@dataclass
class HeldPage:
    path: Path
    url: str
    item_type: str
    evidence: str
    response: HttpResponse
    bad_next: str | None = None  # this page's old nextPage, which went wrong


def save_held(
    directory: Path, index: int, url: str, status: int, headers: dict, body: bytes,
    item_type: str, evidence: str, bad_next: str | None = None,
) -> Path:
    """Write one held page as ``NNN.html`` (body) + ``NNN.json`` (the rest)."""
    directory.mkdir(parents=True, exist_ok=True)
    stem = directory / f"{index:03d}"
    stem.with_suffix(".html").write_bytes(body)
    info = {"url": url, "status": status, "headers": headers,
            "item_type": item_type, "evidence": evidence}
    if bad_next:
        info["bad_next"] = bad_next
    stem.with_suffix(".json").write_text(json.dumps(info, indent=1))
    return stem


def load_held(directory: Path) -> list[HeldPage]:
    pages = []
    for meta in sorted(directory.glob("*.json")):
        info = json.loads(meta.read_text())
        body = meta.with_suffix(".html").read_bytes()
        headers = HttpResponseHeaders.from_name_value_pairs(
            [{"name": k, "value": v} for k, vs in info["headers"].items() for v in vs]
        )
        response = HttpResponse(url=info["url"], body=body, status=info["status"],
                                headers=headers)
        pages.append(HeldPage(meta, info["url"], info["item_type"], info["evidence"],
                              response, info.get("bad_next")))
    return pages


# -- scope ------------------------------------------------------------------------


def tracked_files(root: Path) -> dict[str, str]:
    """``path → sha256`` for every file git would see (tracked + untracked, not ignored)."""
    out = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard", "-z"],
        cwd=root, check=True, capture_output=True,
    ).stdout.decode()
    files = {}
    for rel in filter(None, out.split("\0")):
        path = root / rel
        if path.is_file():
            files[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return files


def changed_files(root: Path, baseline: dict[str, str]) -> tuple[list[str], list[str]]:
    """``(added, modified_or_deleted)`` relative to ``baseline``."""
    now = tracked_files(root)
    added = sorted(set(now) - set(baseline))
    changed = sorted(p for p in baseline if now.get(p) != baseline[p])
    return added, changed


def check_scope(root: Path, baseline: dict[str, str], variants_dir: str, module_file: str) -> Check:
    added, changed = changed_files(root, baseline)
    problems = [f"modified or deleted: {p}" for p in changed]
    problems += [f"added outside {variants_dir}/: {p}" for p in added
                 if not p.startswith(variants_dir + "/")]
    if module_file not in added:
        problems.append(f"candidate is not a new file: {module_file}")
    detail = f"added: {', '.join(added) or 'nothing'}"
    return Check("scope", not problems, detail, problems)


# -- checks -----------------------------------------------------------------------


def check_regression(root: Path, fixtures_dir: str) -> Check:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", fixtures_dir],
        cwd=root, capture_output=True, text=True,
    )
    tail = proc.stdout.strip().splitlines()[-1:] or [proc.stderr.strip()[-300:]]
    return Check("regression", proc.returncode == 0, tail[0],
                 [] if proc.returncode == 0 else [proc.stdout[-2000:]])


def check_routing(candidates: list[type], variants: Variants, fixtures_dir: Path) -> Check:
    """Candidates must refuse other variants' fixtures or extract them identically."""
    problems, tried = [], 0
    for path in sorted(fixtures_dir.glob("*/*/output.json")):
        fixture = Fixture(path.parent)
        owner = path.parent.parent.name
        owner_cls = _import_class(owner)
        for cls in candidates:
            if get_item_cls(cls) is not get_item_cls(owner_cls):
                continue
            tried += 1
            response = fixture.get_page(cls).response
            item, _ = asyncio.run(variants.try_variant(cls, response))
            if item is not None and fixture.get_output(cls) != fixture.get_expected_output():
                problems.append(
                    f"{cls.__qualname__} accepts {owner}/{path.parent.name} "
                    "with different output"
                )
    return Check("routing", not problems, f"{tried} fixture runs", problems)


def run_held(
    candidates: list[type], variants: Variants, pages: list[HeldPage]
) -> tuple[list[tuple[HeldPage, type, Any]], list[str]]:
    """Try candidates newest first on each page, like the spider would."""
    accepted, problems = [], []
    for page in pages:
        refusals = []
        for cls in reversed(candidates):
            item, why = asyncio.run(variants.try_variant(cls, page.response))
            if item is not None:
                next_page = getattr(item, "nextPage", None)
                if page.bad_next and next_page and str(next_page.url) == page.bad_next:
                    refusals.append(f"{cls.__qualname__} still sends nextPage to {page.bad_next}")
                    continue
                accepted.append((page, cls, item))
                break
            refusals += why
        else:
            reasons = "; ".join(str(r) for r in refusals[:5])
            problems.append(f"{page.path.stem} {page.url}: {reasons}")
    return accepted, problems


def check_variation(accepted: list[tuple[HeldPage, type, Any]]) -> Check:
    if len({p.url for p, _, _ in accepted}) < MIN_PAGES_FOR_VARIATION:
        return Check("variation", True, f"skipped: fewer than {MIN_PAGES_FOR_VARIATION} pages")
    problems = []
    for name in VARYING_FIELDS:
        values = [getattr(item, name, None) for _, _, item in accepted]
        if any(v in (None, [], "") for v in values):
            continue
        if len({json.dumps(_plain(v), sort_keys=True, default=str) for v in values}) == 1:
            problems.append(f"{name} is the same on all {len(values)} pages: {values[0]!r:.80}")
    return Check("variation", not problems, f"{len(accepted)} pages", problems)


def check_fields(accepted: list[tuple[HeldPage, type, Any]], fixtures_dir: Path,
                 item_cls: type, absent: dict[str, str] | None = None) -> Check:
    """The candidate must fill the fields some existing variant fills.

    Each existing variant of this item type has a field profile: the fields
    filled on at least half of its fixtures (a field only some pages have,
    like subcategories on top-level categories only, is not expected). The
    fields the candidate fills across the held pages must cover at least one
    of those profiles. This catches a new
    variant that silently drops a field (e.g. leaves "Color" in
    ``additionalProperties`` instead of ``color``), while a home page is
    compared with the home-page variant, not with category pages that share
    its item type.

    The held pages are only a sample, and it may not be representative (e.g.
    all books, which have no brand). So the candidate module may declare a field
    absent with ``ABSENT_FIELDS = {"brand": "why"}``: the check then accepts it,
    and the declaration is part of the reviewed diff and the report.
    """
    absent = absent or {}
    counts: dict[str, dict[str, int]] = {}
    totals: dict[str, int] = {}
    for path in sorted(fixtures_dir.glob("*/*/output.json")):
        owner = path.parent.parent.name
        if get_item_cls(_import_class(owner)) is not item_cls:
            continue
        owner = owner.rpartition(".")[2]
        totals[owner] = totals.get(owner, 0) + 1
        for name, value in json.loads(path.read_text()).items():
            if value not in (None, [], "", {}):
                counts.setdefault(owner, {})[name] = counts.get(owner, {}).get(name, 0) + 1
    profiles = {owner: {n for n, c in counts.get(owner, {}).items() if 2 * c >= totals[owner]}
                for owner in totals}
    if not profiles:
        return Check("fields", True, "no existing fixtures of this item type")
    filled = {
        name for _, _, item in accepted
        for name, value in _plain(item).items() if value not in (None, [], "", {})
    }
    missing = {owner: sorted(p - filled) for owner, p in profiles.items()}
    closest = min(missing, key=lambda o: len(set(missing[o]) - set(absent)))
    undeclared = [n for n in missing[closest] if n not in absent]
    problems = [] if not undeclared else [
        f"closest existing variant {closest} fills {', '.join(undeclared)}; "
        "the candidate fills none of these on any held page (if no held page "
        "shows them, declare them in ABSENT_FIELDS)"
    ]
    problems += [f"{n} is declared absent but filled on a held page"
                 for n in sorted(set(absent) & filled)]
    declared = [f"{n} declared absent: {absent[n]}" for n in missing[closest] if n in absent]
    detail = "; ".join([f"field profile of {closest}"] + declared)
    return Check("fields", not problems, detail, problems)


def _plain(value: Any) -> Any:
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if hasattr(value, "__attrs_attrs__"):
        import attrs

        return attrs.asdict(value)
    return value


def _import_class(fq_name: str) -> type:
    module, _, name = fq_name.rpartition(".")
    return getattr(importlib.import_module(module), name)


# -- entry point ------------------------------------------------------------------


def run_gate(args: argparse.Namespace) -> list[Check]:
    from scrapy.spiderloader import SpiderLoader
    from scrapy.utils.project import get_project_settings

    root = Path.cwd()
    settings = get_project_settings()
    # In the agent's workspace only the repaired spider's package exists.
    settings.set("SPIDER_LOADER_WARN_ONLY", True)
    spider_cls = SpiderLoader.from_settings(settings).load(args.spider)
    package = spider_cls.variants_package
    pkg_root = package.split(".")[0]
    module_file = args.candidate.replace(".", "/") + ".py"
    checks: list[Check] = []

    if args.baseline:
        baseline = json.loads(Path(args.baseline).read_text())
        checks.append(check_scope(root, baseline, package.replace(".", "/"), module_file))

    variants = Variants(checks=dict(spider_cls.item_checks))
    variants.register_package(package)  # includes the candidate if it is in the package
    try:
        module = importlib.import_module(args.candidate)
        candidates = [c for c in variants.all() if c.__module__ == module.__name__]
        if not candidates:
            raise ValueError("defines no page object")
    except Exception as exc:
        checks.append(Check("import", False, f"{type(exc).__name__}: {exc}",
                            [f"{type(exc).__name__}: {exc}"]))
        return checks
    checks.append(Check("import", True, ", ".join(c.__qualname__ for c in candidates)))

    checks.append(check_regression(root, f"{pkg_root}/fixtures"))
    checks.append(check_routing(candidates, variants, root / pkg_root / "fixtures"))

    item_types = {get_fq_class_name(get_item_cls(c)) for c in candidates}
    pages = [p for p in load_held(Path(args.held)) if p.item_type in item_types]
    accepted, problems = run_held(candidates, variants, pages)
    # Untested code doesn't load: a class no held page reaches has never been
    # run on this site. Pages of that kind get held (and repaired) later.
    used = {cls for _, cls, _ in accepted}
    problems += [f"{c.__qualname__} accepts none of the held pages (untested)"
                 for c in candidates if c not in used]
    checks.append(Check(
        "coverage", bool(pages) and not problems,
        f"{len(accepted)}/{len(pages)} held pages accepted (extraction + item check)",
        problems or ([] if pages else ["no held pages of the candidate's item type"]),
    ))
    checks.append(check_variation(accepted))
    for item_cls in {get_item_cls(c) for c in candidates}:
        mine = [a for a in accepted if get_item_cls(a[1]) is item_cls]
        # Navigation pages differ in shape by design (home, listing, scroll
        # fragment, empty end probe), so no field profile fits them all; their
        # completeness is guarded by the navigation item check, the progress
        # check and last-page proofs instead.
        if mine and not issubclass(item_cls, ProductNavigation):
            absent = getattr(importlib.import_module(args.candidate), "ABSENT_FIELDS", {})
            checks.append(check_fields(mine, root / pkg_root / "fixtures", item_cls, absent))

    if args.save_fixtures and all(c.ok for c in checks):
        for page, cls, item in accepted:
            save_fixture(args.save_fixtures, cls, page.response, item,
                         name=f"held-{page.path.stem}")
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m selfheal.gate")
    parser.add_argument("--spider", required=True)
    parser.add_argument("--candidate", required=True, help="module, e.g. pkg.variants.product_v2")
    parser.add_argument("--held", required=True, help="directory of held pages")
    parser.add_argument("--baseline", help="file hashes at repair start (scope check)")
    parser.add_argument("--json", help="write the result here")
    parser.add_argument("--save-fixtures", help="on success, save held pages as fixtures here")
    args = parser.parse_args(argv)
    sys.path.insert(0, str(Path.cwd()))
    checks = run_gate(args)
    ok = all(c.ok for c in checks)
    for c in checks:
        print(f"{'PASS' if c.ok else 'FAIL'} {c.name}: {c.detail}")
        for p in c.problems[:20]:
            print(f"     - {p}")
    print("GATE PASSED" if ok else "GATE FAILED")
    if args.json:
        Path(args.json).write_text(json.dumps(
            {"ok": ok, "checks": [asdict(c) for c in checks]}, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
