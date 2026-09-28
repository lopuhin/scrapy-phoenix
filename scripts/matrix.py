"""Breakage matrix: crawl the sandbox under every layout preset (no healer).

Usage: python scripts/matrix.py [--spider sandbox_store] [presets...]

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
    parser.add_argument("--spider", default="sandbox_store")
    parser.add_argument("--base", default="http://127.0.0.1:8765")
    args = parser.parse_args()
    OUT.mkdir(exist_ok=True)
    rows = []
    try:
        for preset in args.presets:
            apply(args.base, PRESETS["default"] | PRESETS[preset])
            items, stats = OUT / f"{preset}.jsonl", OUT / f"{preset}.stats.json"
            subprocess.run(
                [sys.executable, "-m", "scrapy", "crawl", args.spider, "-O", str(items),
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
            rows.append((preset, s.get("item_scraped_count", 0), score, used, refused, evidence))
            print(f"{preset}: {rows[-1][1:5]}", file=sys.stderr)
    finally:
        apply(args.base, PRESETS["default"])
    lines = ["| preset | items | fully correct | variants used | refused | first refusal |",
             "|---|---|---|---|---|---|"]
    for preset, n, score, used, refused, evidence in rows:
        fmt = lambda d: ", ".join(f"{k} {v}" for k, v in sorted(d.items())) or "—"
        lines.append(f"| {preset} | {n} | {score} | {fmt(used)} | {fmt(refused)} | {evidence.replace('|', '/')} |")
    table = "\n".join(lines)
    (OUT / "matrix.md").write_text(table + "\n")
    print(table)


if __name__ == "__main__":
    main()
