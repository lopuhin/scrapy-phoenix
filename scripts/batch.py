"""Reliability batch: run each case N times with the healer and tally.

Usage: python scripts/batch.py [-n 1] [--case NAME ...] [-s KEY=VALUE ...]
       python scripts/batch.py --summary

Each run is ``scripts/run_demo.py PRESET --spider SPIDER --reset``. One row per
run is appended to output/batch/results.jsonl: how the crawl finished, items
fully correct against ground truth, and per repair its outcome, whether the
gate passed on the first attempt, cost and pause. ``--summary`` (also printed
after a batch) aggregates all rows per case and model, so batches add up.
"""

import argparse
import json
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

OUT = Path("output/batch")
RESULTS = OUT / "results.jsonl"
INDEX = Path("repairs/index.jsonl")

# name: (preset, spider, expected finish reason)
CASES = {
    "A": ("product-modern", "sandbox_store", "finished"),
    "A-half": ("product-modern-half", "sandbox_store", "finished"),
    "A-repriced": ("product-modern-repriced", "sandbox_store", "finished"),
    "B": ("infinite-scroll", "sandbox_store", "finished"),
    "load-more": ("load-more", "sandbox_store", "finished"),
    "C": ("no-price", "sandbox_store", "repair_failed"),
    "modern": ("modern", "sandbox_store", "finished"),
    "scroll:A": ("scroll-modern", "sandbox_scroll", "finished"),
    "modern:B": ("scroll-modern", "sandbox_modern", "finished"),
}


def run(case: str, settings: list[str]) -> dict:
    preset, spider, expected = CASES[case]
    before = len(INDEX.read_text().splitlines()) if INDEX.exists() else 0
    log = OUT / "logs" / f"{time.strftime('%Y%m%dT%H%M%S')}-{case.replace(':', '-')}.txt"
    log.parent.mkdir(parents=True, exist_ok=True)
    cmd = [sys.executable, "scripts/run_demo.py", preset, "--spider", spider, "--reset"]
    for s in settings:
        cmd += ["-s", s]
    started = time.monotonic()
    with log.open("w") as f:
        subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, check=False)
    wall = time.monotonic() - started

    stats = json.loads(Path("output/demo/stats.json").read_text())
    score = subprocess.run(
        [sys.executable, "scripts/score.py", "output/demo/items.jsonl", "--full-only"],
        capture_output=True, text=True, check=False,
    ).stdout.strip()
    repairs = [json.loads(line) for line in INDEX.read_text().splitlines()[before:]]
    finish = stats.get("finish_reason")
    model = next((s.split("=", 1)[1] for s in settings if s.startswith("SELFHEAL_MODEL=")),
                 "default")
    return {
        "case": case, "model": model, "finish_reason": finish,
        "ok": finish == expected and (expected != "finished" or _all_correct(score)),
        "fully_correct": score, "wall_s": round(wall),
        "cost_usd": round(sum(r.get("cost_usd") or 0 for r in repairs), 4),
        "paused_s": round(sum(r.get("paused_s") or 0 for r in repairs)),
        "repairs": [{k: r.get(k) for k in ("id", "outcome", "gate_attempt_1", "cost_usd",
                                           "paused_s", "loaded", "reason")}
                    for r in repairs],
        "log": str(log),
    }


def _all_correct(score: str) -> bool:
    done, _, total = score.partition("/")
    return bool(total) and done == total and done != "0"


def summary() -> None:
    rows = [json.loads(line) for line in RESULTS.read_text().splitlines()]
    groups = defaultdict(list)
    for row in rows:
        groups[(row["case"], row["model"])].append(row)
    print(f"{'case':12} {'model':14} {'ok':>6} {'repairs':>8} {'1st-try':>8} "
          f"{'$/run':>7} {'pause s':>8}  outcomes")
    total = 0.0
    for (case, model), runs in sorted(groups.items()):
        reps = [r for run in runs for r in run["repairs"]]
        cost = sum(run["cost_usd"] for run in runs)
        total += cost
        repaired = [r for r in reps if r["outcome"] == "repaired"]
        first = sum(1 for r in repaired if r["gate_attempt_1"])
        outcomes = " ".join(run["fully_correct"] or run["finish_reason"] for run in runs)
        print(f"{case:12} {model:14} {sum(r['ok'] for r in runs):>3}/{len(runs):<2} "
              f"{len(reps) / len(runs):>8.1f} {first:>4}/{len(repaired):<3} "
              f"{cost / len(runs):>7.3f} {sum(r['paused_s'] for r in runs) / len(runs):>8.0f}"
              f"  {outcomes}")
    print(f"total reported cost: ${total:.2f} over {len(rows)} runs")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("-n", type=int, default=1, help="runs per case")
    parser.add_argument("--case", action="append", choices=list(CASES))
    parser.add_argument("-s", dest="settings", action="append", default=[])
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args()
    if not args.summary:
        OUT.mkdir(parents=True, exist_ok=True)
        for _ in range(args.n):
            for case in args.case or list(CASES):
                row = run(case, args.settings)
                with RESULTS.open("a") as f:
                    f.write(json.dumps(row) + "\n")
                print(f"{case:12} {row['finish_reason']:14} {row['fully_correct']:>9} "
                      f"${row['cost_usd']:.3f} {row['paused_s']}s paused", flush=True)
        subprocess.run([sys.executable, "scripts/drift.py", "default"], check=False,
                       capture_output=True)
    summary()


if __name__ == "__main__":
    main()
