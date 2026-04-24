#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

from core.hypothesis import compute_hypothesis_metrics


FIELDNAMES = [
    "result_json",
    "baseline_condition",
    "execution_mode",
    "scenario",
    "final_status",
    "turn_count",
    "top1_hypothesis_changes",
    "hypothesis_set_updates",
    "critique_count",
    "changed_after_critique_count",
    "critique_change_rate",
    "wrong_hypothesis_stickiness",
    "first_fix_success",
    "full_recovery",
    "reobservation_count",
    "reobservation_effect_count",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aggregate Phase 4.5 hypothesis transition metrics from result JSON files.")
    parser.add_argument("paths", nargs="+", help="Result JSON files, directories, or observation summary.csv files.")
    parser.add_argument("--output", "-o", default="", help="Optional CSV output path.")
    return parser.parse_args()


def iter_result_paths(paths: list[str]) -> list[Path]:
    results: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            results.extend(sorted(path.glob("*.json")))
            continue
        if path.suffix == ".csv":
            results.extend(_paths_from_summary(path))
            continue
        results.append(path)
    return [path for path in results if path.exists() and path.suffix == ".json"]


def _paths_from_summary(path: Path) -> list[Path]:
    rows: list[Path] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            raw_path = row.get("result_path", "")
            if raw_path:
                rows.append(Path(raw_path))
    return rows


def row_for_result(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    log = data.get("hypothesis_log", [])
    metrics = data.get("hypothesis_metrics") or compute_hypothesis_metrics(log)
    return {
        "result_json": str(path),
        "baseline_condition": data.get("baseline_condition", data.get("execution_mode", "")),
        "execution_mode": data.get("execution_mode", ""),
        "scenario": data.get("scenario", ""),
        "final_status": data.get("final_status", ""),
        **{key: metrics.get(key, "") for key in FIELDNAMES if key not in {"result_json", "baseline_condition", "execution_mode", "scenario", "final_status"}},
    }


def main() -> int:
    args = parse_args()
    result_paths = iter_result_paths(args.paths)
    rows = [row_for_result(path) for path in result_paths]
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writeheader()
            writer.writerows(rows)
        print(f"wrote {output}")
    else:
        writer = csv.DictWriter(sys.stdout, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
