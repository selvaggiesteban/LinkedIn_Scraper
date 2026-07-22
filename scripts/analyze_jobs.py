"""
analyze_jobs.py — Ad-hoc analysis script for saved job outputs.

Reads the most recent jobs file from data/outputs/historical/ (or accept a path
as first CLI arg) and prints keyword + location distributions and a sample.

Usage:
    python scripts/analyze_jobs.py
    python scripts/analyze_jobs.py path/to/jobs.json
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
HISTORICAL_DIR = PROJECT_ROOT / "data" / "outputs" / "historical"
OUTPUT_DIR = PROJECT_ROOT / "output"


def _find_target() -> Path:
    if len(sys.argv) > 1:
        return Path(sys.argv[1])
    candidates = sorted(HISTORICAL_DIR.glob("jobs_*.json"), reverse=True)
    if not candidates:
        candidates = sorted(OUTPUT_DIR.glob("jobs_*.json"), reverse=True)
    if not candidates:
        print("[ERR] No jobs file found in data/outputs/historical/ or output/")
        sys.exit(1)
    return candidates[0]


def main() -> int:
    target = _find_target()
    print(f"Analyzing: {target}")
    with open(target, "r", encoding="utf-8") as f:
        data = json.load(f)

    print(f"Total jobs: {len(data)}")
    print("\nBy keyword:")
    for kw, count in Counter(j.get("search_keyword", "?") for j in data).most_common():
        print(f"  {kw}: {count}")

    print("\nBy location:")
    for loc, count in Counter(j.get("location", "?") for j in data).most_common(10):
        print(f"  {loc}: {count}")

    print("\nSample jobs:")
    for j in data[:5]:
        title = j.get("title", "?")
        company = j.get("company", "?")
        location = j.get("location", "?")
        print(f"  {title} at {company} ({location})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
