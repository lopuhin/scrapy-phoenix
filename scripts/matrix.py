"""Breakage matrix: crawl the sandbox under every layout preset (no healer).

Usage: python scripts/matrix.py [--spider NAME ...] [presets...]

For each preset: flip the sandbox, run a full crawl, and report items, how many
are fully correct against ground truth, which pages were refused, and the first
refusal's evidence. Restores the default layout at the end. Writes
output/matrix.md.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from drift import PRESETS, apply  # noqa: E402

OUT = Path("output")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("presets", nargs="*", default=list(PRESETS))
    parser.add_argument(
        "--spider", action="append",
        help="default: sandbox_store, sandbox_modern, sandbox_scroll",
    )
    parser.add_argument("--base", default="http://127.0.0.1:8765")
    args = parser.parse_args()
    spiders = args.spider or ["sandbox_store", "sandbox_modern", "sandbox_scroll"]
    OUT.mkdir(exist_ok=True)
    rows = []
    try:
        for spider, preset in ((sp, pr) for sp in spiders for pr in args.presets):
            apply(args.base, PRESETS["default"] | PRESETS[preset])
            items = OUT / f"{spider}.{preset}.jsonl"
            stats = OUT / f"{spider}.{preset}.stats.json"
            subprocess.run(
                [sys.executable, "-m", "scrapy", "crawl", spider, "-O", str(items),
                 "-s", f"SELFHEAL_STATS_FILE={stats}", "-s", "LOG_LEVEL=ERROR"],
                check=True,
            )
            s = json.loads(stats.read_text())
            score = subprocess.run(
                [sys.executable, "scripts/score.py", str(items), "--base", args.base, "--full-only"],
                capture_output=True, text=True, check=True,
            ).stdout.strip()
            refused = {k.rsplit("/", 1)[1]: v for k, v in s.items() if k.startswith("selfheal/unrecognized/")}
            used = {k.rsplit("/", 1)[1]: v for k, v in s.items() if k.startswith("selfheal/variant/")}
            first = (s.get("selfheal/first_unrecognized") or "").splitlines()
            evidence = f"{first[0]} — {first[1].strip()}" if len(first) > 1 else ""
            rows.append((spider, preset, s.get("item_scraped_count", 0),
                         s.get("downloader/request_count", 0), score, used, refused, evidence))
            print(f"{spider} {preset}: {rows[-1][2:7]}", file=sys.stderr)
    finally:
        apply(args.base, PRESETS["default"])
    lines = ["| spider | sandbox layout | requests | items | fully correct | variants used | refused | first refusal |",
             "|---|---|---|---|---|---|---|---|"]
    for spider, preset, n, reqs, score, used, refused, evidence in rows:
        fmt = lambda d: ", ".join(f"{k} {v}" for k, v in sorted(d.items())) or "—"
        lines.append(f"| {spider} | {preset} | {reqs} | {n} | {score} | {fmt(used)} | {fmt(refused)} | {evidence.replace('|', '/')} |")
    table = "\n".join(lines)
    (OUT / "matrix.md").write_text(table + "\n")
    print(table)


if __name__ == "__main__":
    main()
