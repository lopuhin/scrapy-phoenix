"""Run a self-healing crawl against a drifted sandbox and score the result.

Usage: python scripts/run_demo.py PRESET [--spider sandbox_store] [--reset]
                                  [-s NAME=VALUE ...]

Switches the sandbox to ``PRESET`` (see ``scripts/drift.py``), crawls with the
healer enabled, scores the items against ground truth, and exits non-zero if
the crawl closed with ``repair_failed``. Output: ``output/demo/``; repairs:
``repairs/``.

New variant modules written by earlier demo runs are untracked files in the
spider's ``variants/`` package. They would repair the crawl before it breaks,
so the script refuses to start while there are any; ``--reset`` deletes them.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from scrapy.spiderloader import SpiderLoader
from scrapy.utils.project import get_project_settings

sys.path.insert(0, str(Path(__file__).parent))
from drift import PRESETS, apply  # noqa: E402

OUT = Path("output/demo")


def untracked_variants(package_dir: str) -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", package_dir],
        check=True, capture_output=True, text=True,
    ).stdout
    return [Path(p) for p in out.split()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("preset", choices=PRESETS)
    parser.add_argument("--spider", default="sandbox_store")
    parser.add_argument("--base", default="http://127.0.0.1:8765")
    parser.add_argument("--reset", action="store_true", help="delete untracked variant modules")
    parser.add_argument("-s", dest="settings", action="append", default=[])
    args = parser.parse_args()

    spider_cls = SpiderLoader.from_settings(get_project_settings()).load(args.spider)
    variants_dir = spider_cls.variants_package.replace(".", "/")
    leftovers = untracked_variants(variants_dir)
    if leftovers and not args.reset:
        print(f"untracked variant modules from earlier runs: {leftovers}; use --reset")
        return 2
    for path in leftovers:
        path.unlink()
        print(f"removed {path}")

    apply(args.base, PRESETS["default"] | PRESETS[args.preset])
    OUT.mkdir(parents=True, exist_ok=True)
    items, stats = OUT / "items.jsonl", OUT / "stats.json"
    cmd = [
        sys.executable, "-m", "scrapy", "crawl", args.spider, "-O", str(items),
        "-s", "SELFHEAL_ENABLED=1", "-s", f"SELFHEAL_STATS_FILE={stats}",
        "-s", f"LOG_FILE={OUT / 'crawl.log'}", "-s", "LOG_FILE_APPEND=False",
    ]
    for setting in args.settings:
        cmd += ["-s", setting]
    print(" ".join(cmd))
    subprocess.run(cmd, check=False)

    result = json.loads(stats.read_text())
    keys = ("finish_reason", "item_scraped_count", "selfheal/held", "selfheal/repairs",
            "selfheal/failed", "elapsed_time_seconds")
    for key in keys:
        if key in result:
            print(f"{key:24} {result[key]}")
    for key, value in sorted(result.items()):
        if key.startswith(("selfheal/variant/", "selfheal/unrecognized/")):
            print(f"{key:48} {value}")
    if spider_cls.variants_package.startswith("sandbox"):
        subprocess.run([sys.executable, "scripts/score.py", str(items), "--base", args.base],
                       check=False)
    index = Path("repairs/index.jsonl")
    if index.exists():
        print("repairs:")
        for line in index.read_text().splitlines()[-3:]:
            row = json.loads(line)
            row.pop("usage", None)
            print(" ", json.dumps(row))
    return 1 if result.get("finish_reason") == "repair_failed" else 0


if __name__ == "__main__":
    sys.exit(main())
