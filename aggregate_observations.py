#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
aggregate_observations.py

observe_runs.sh が出力した summary.csv を集計するスクリプト。

主な機能:
- シナリオ別 / worker別 / prompt_mode別 などで集計
- 成功率、平均所要時間、追加観測率を計算
- open-world 向けの scenario->abstract domain 一致率を確認
- planner transport failure / reasoning failure / validation failure / postcheck failure を分けて確認

使い方例:
  python aggregate_observations.py observations/20260310T120000Z/summary.csv
  python aggregate_observations.py observations/20260310T120000Z/summary.csv --group-by scenario
  python aggregate_observations.py observations/20260310T120000Z/summary.csv --group-by scenario worker
  python aggregate_observations.py observations/20260310T120000Z/summary.csv --group-by scenario_mode prompt_mode
"""

from __future__ import annotations

import argparse
import csv
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Tuple, Any


DEFAULT_GROUP_BY = ["scenario"]
EXPECTED_DOMAINS_BY_SCENARIO = {
    "a": {"reverse_proxy_or_upstream_mismatch"},
    "b": {"app_startup_or_dependency_failure"},
    "c": {"database_auth_or_connectivity_issue"},
    "d": {"query_or_code_bug"},
    "e": {"ambiguous_service_disagreement"},
    "f": {"schema_drift"},
    "g": {"healthcheck_only_failure"},
    "h": {"reverse_proxy_or_upstream_mismatch"},
    "i": {"ambiguous_service_disagreement", "app_config_or_env_mismatch", "database_auth_or_connectivity_issue"},
    "i2": {"ambiguous_service_disagreement", "app_config_or_env_mismatch", "reverse_proxy_or_upstream_mismatch"},
    "k": {"query_or_code_bug", "schema_drift"},
    "l": {"query_or_code_bug"},
    "m": {"reverse_proxy_or_upstream_mismatch"},
    "n": {"app_startup_or_dependency_failure"},
    "o": {"database_auth_or_connectivity_issue", "query_or_code_bug"},
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="observe_runs.sh の summary.csv を集計する")
    p.add_argument("summary_csv", help="summary.csv のパス")
    p.add_argument(
        "--group-by",
        nargs="+",
        default=DEFAULT_GROUP_BY,
        help="集計キー。例: --group-by scenario worker",
    )
    p.add_argument(
        "--sort-by",
        default="group",
        choices=[
            "group",
            "runs",
            "success_rate",
            "avg_elapsed_all",
            "avg_elapsed_success",
            "additional_obs_rate",
            "avg_planner_retries",
            "transport_failure_rate",
            "rollback_recovery_rate",
            "retry_assisted_recovery_count",
            "fallback_recovery_count",
            "minimal_patch_ratio",
            "domain_match_rate",
            "legacy_detection_match_rate",
        ],
        help="並び順",
    )
    p.add_argument(
        "--desc",
        action="store_true",
        help="降順で表示",
    )
    p.add_argument(
        "--show-overall",
        action="store_true",
        help="全体集計も表示",
    )
    p.add_argument(
        "--show-failure-breakdown",
        action="store_true",
        help="失敗理由の簡易内訳も表示",
    )
    return p.parse_args()


def to_bool(s: str) -> bool:
    return str(s).strip().lower() in {"1", "true", "yes", "y"}


def to_float_or_none(s: str):
    s = str(s).strip()
    if s == "":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def normalize_text(s: str) -> str:
    return " ".join(str(s).strip().split())


def infer_failure_bucket(row: Dict[str, str]) -> str:
    """
    summary.csv の planner_summary と agent_exit_code などから
    ごく雑に失敗カテゴリを推定する。
    """
    final_status = normalize_text(row.get("final_status", ""))
    planner_summary = normalize_text(row.get("planner_summary", "")).lower()
    planner_error_type = normalize_text(row.get("planner_error_type", "")).lower()
    planner_transport_failure = to_bool(row.get("planner_transport_failure", ""))
    planner_reasoning_failure = to_bool(row.get("planner_reasoning_failure", ""))
    precheck_ok = normalize_text(row.get("precheck_ok", "")).lower()
    postcheck_ok = normalize_text(row.get("postcheck_ok", "")).lower()
    agent_exit_code = normalize_text(row.get("agent_exit_code", ""))
    break_ok = normalize_text(row.get("break_ok", "")).lower()

    if break_ok not in {"true", "1", "yes", "y"}:
        return "break_failure"

    if final_status == "success":
        return "success"

    if planner_error_type == "planner_timeout" or "timed out" in planner_summary or "read timeout" in planner_summary or "timeout" in planner_summary:
        return "planner_timeout"

    if planner_error_type in {"api_key_missing", "planner_auth_error"} or "api_key is not set" in planner_summary or "api key is not set" in planner_summary:
        return "missing_api_key"

    if planner_error_type == "planner_model_error":
        return "planner_model_error"

    if planner_transport_failure or planner_error_type == "planner_transport_error":
        return "planner_transport_failure"

    if planner_reasoning_failure or planner_error_type in {"empty_plan", "planner_parse_error"}:
        return "planner_reasoning_failure"

    if "no recovery action required" in planner_summary:
        return "already_healthy_or_noop"

    if precheck_ok in {"false", "0", "no"}:
        return "validation_failure"

    if postcheck_ok in {"false", "0", "no"}:
        return "postcheck_failure"

    if "planner invocation failed" in planner_summary:
        return "planner_invocation_failure"

    if agent_exit_code not in {"0", "", "reset_failed", "break_failed"}:
        return "agent_nonzero_exit"

    return "postcheck_or_validation_failure"


def load_rows(summary_csv: Path) -> List[Dict[str, str]]:
    with summary_csv.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader)


def group_rows(rows: List[Dict[str, str]], group_by: List[str]) -> Dict[Tuple[str, ...], List[Dict[str, str]]]:
    grouped: Dict[Tuple[str, ...], List[Dict[str, str]]] = defaultdict(list)
    for row in rows:
        key = tuple(normalize_text(row.get(k, "")) for k in group_by)
        grouped[key].append(row)
    return grouped


def compute_metrics(rows: List[Dict[str, str]]) -> Dict[str, Any]:
    runs = len(rows)
    success_rows = [r for r in rows if normalize_text(r.get("final_status", "")) == "success"]
    success = len(success_rows)

    elapsed_all = [x for x in (to_float_or_none(r.get("elapsed_seconds", "")) for r in rows) if x is not None]
    elapsed_success = [x for x in (to_float_or_none(r.get("elapsed_seconds", "")) for r in success_rows) if x is not None]
    planner_retry_values = [x for x in (to_float_or_none(r.get("planner_retry_count", "")) for r in rows) if x is not None]

    add_obs_true = sum(1 for r in rows if to_bool(r.get("additional_observation_used", "")))
    transport_failure_count = sum(1 for r in rows if to_bool(r.get("planner_transport_failure", "")))
    rollback_used_count = sum(1 for r in rows if to_bool(r.get("rollback_used", "")))
    rollback_recovered_count = sum(
        1 for r in rows if to_bool(r.get("rollback_used", "")) and to_bool(r.get("rollback_postcheck_ok", ""))
    )
    retry_assisted_recovery_count = sum(
        1
        for r in rows
        if normalize_text(r.get("final_status", "")) == "success"
        and to_bool(r.get("postcheck_used_retry_window", ""))
    )
    fallback_recovery_count = sum(
        1
        for r in rows
        if normalize_text(r.get("final_status", "")) == "success"
        and to_bool(r.get("planner_fallback_used", ""))
    )
    minimal_patch_count = sum(1 for r in rows if to_bool(r.get("minimal_patch_used", "")))
    restore_used_count = sum(1 for r in rows if to_bool(r.get("restore_from_base_used", "")))
    domain_match = sum(
        1
        for r in rows
        if normalize_text(r.get("scenario", "")) != ""
        and normalize_text(r.get("detected_fault_class", "")) != ""
        and normalize_text(r.get("detected_fault_class", ""))
        in EXPECTED_DOMAINS_BY_SCENARIO.get(normalize_text(r.get("scenario", "")), set())
    )
    legacy_detection_match = sum(
        1
        for r in rows
        if normalize_text(r.get("scenario", "")) != ""
        and normalize_text(r.get("detected_fault_class", "")) != ""
        and normalize_text(r.get("scenario", "")) == normalize_text(r.get("detected_fault_class", ""))
    )

    failure_counter = Counter(infer_failure_bucket(r) for r in rows if normalize_text(r.get("final_status", "")) != "success")

    return {
        "runs": runs,
        "success": success,
        "success_rate": (success / runs * 100.0) if runs else 0.0,
        "avg_elapsed_all": statistics.mean(elapsed_all) if elapsed_all else None,
        "avg_elapsed_success": statistics.mean(elapsed_success) if elapsed_success else None,
        "additional_obs_used": add_obs_true,
        "additional_obs_rate": (add_obs_true / runs * 100.0) if runs else 0.0,
        "avg_planner_retries": statistics.mean(planner_retry_values) if planner_retry_values else None,
        "transport_failure_count": transport_failure_count,
        "transport_failure_rate": (transport_failure_count / runs * 100.0) if runs else 0.0,
        "rollback_recovery_rate": (rollback_recovered_count / rollback_used_count * 100.0)
        if rollback_used_count
        else 0.0,
        "retry_assisted_recovery_count": retry_assisted_recovery_count,
        "fallback_recovery_count": fallback_recovery_count,
        "minimal_patch_ratio": (minimal_patch_count / max(1, restore_used_count))
        if minimal_patch_count or restore_used_count
        else 0.0,
        "domain_match": domain_match,
        "domain_match_rate": (domain_match / runs * 100.0) if runs else 0.0,
        "legacy_detection_match": legacy_detection_match,
        "legacy_detection_match_rate": (legacy_detection_match / runs * 100.0) if runs else 0.0,
        "failure_counter": failure_counter,
    }


def fmt_num(x: Any, digits: int = 2) -> str:
    if x is None:
        return "-"
    if isinstance(x, float):
        if math.isnan(x):
            return "-"
        return f"{x:.{digits}f}"
    return str(x)


def table(rows: List[List[str]], headers: List[str]) -> str:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def render_row(cells: List[str]) -> str:
        return " | ".join(cell.ljust(widths[i]) for i, cell in enumerate(cells))

    sep = "-+-".join("-" * w for w in widths)
    out = [render_row(headers), sep]
    out.extend(render_row(r) for r in rows)
    return "\n".join(out)


def sort_group_items(
    items: List[Tuple[Tuple[str, ...], Dict[str, Any]]],
    sort_by: str,
    desc: bool,
) -> List[Tuple[Tuple[str, ...], Dict[str, Any]]]:
    if sort_by == "group":
        return sorted(items, key=lambda x: x[0], reverse=desc)
    return sorted(
        items,
        key=lambda x: (
            -1e18 if x[1].get(sort_by) is None else x[1].get(sort_by)
        ),
        reverse=desc,
    )


def render_group_name(key: Tuple[str, ...], group_by: List[str]) -> str:
    if not group_by:
        return "overall"
    parts = [f"{k}={v}" for k, v in zip(group_by, key)]
    return ", ".join(parts)


def main() -> None:
    args = parse_args()
    summary_csv = Path(args.summary_csv)

    if not summary_csv.exists():
        raise SystemExit(f"summary.csv が見つかりません: {summary_csv}")

    rows = load_rows(summary_csv)
    if not rows:
        raise SystemExit("summary.csv にデータがありません")

    grouped = group_rows(rows, args.group_by)
    metrics_by_group = {k: compute_metrics(v) for k, v in grouped.items()}
    items = list(metrics_by_group.items())
    items = sort_group_items(items, args.sort_by, args.desc)

    display_rows: List[List[str]] = []
    for key, m in items:
        display_rows.append(
            [
                render_group_name(key, args.group_by),
                fmt_num(m["runs"], 0),
                fmt_num(m["success"], 0),
                fmt_num(m["success_rate"]),
                fmt_num(m["avg_elapsed_all"]),
                fmt_num(m["avg_elapsed_success"]),
                fmt_num(m["additional_obs_used"], 0),
                fmt_num(m["additional_obs_rate"]),
                fmt_num(m["avg_planner_retries"]),
                fmt_num(m["transport_failure_rate"]),
                fmt_num(m["rollback_recovery_rate"]),
                fmt_num(m["retry_assisted_recovery_count"], 0),
                fmt_num(m["fallback_recovery_count"], 0),
                fmt_num(m["minimal_patch_ratio"]),
                fmt_num(m["domain_match"], 0),
                fmt_num(m["domain_match_rate"]),
                fmt_num(m["legacy_detection_match"], 0),
                fmt_num(m["legacy_detection_match_rate"]),
            ]
        )

    headers = [
        "group",
        "runs",
        "success",
        "success_rate(%)",
        "avg_elapsed_all(s)",
        "avg_elapsed_success(s)",
        "add_obs_used",
        "add_obs_rate(%)",
        "avg_planner_retries",
        "transport_failure_rate(%)",
        "rollback_recovery_rate(%)",
        "retry_assisted_recovery_count",
        "fallback_recovery_count",
        "minimal_patch_ratio",
        "domain_match",
        "domain_match_rate(%)",
        "legacy_detect_match",
        "legacy_detect_match_rate(%)",
    ]

    print()
    print(f"[aggregate] source: {summary_csv}")
    print(f"[aggregate] group_by: {', '.join(args.group_by)}")
    print()
    print(table(display_rows, headers))

    if args.show_overall:
        overall = compute_metrics(rows)
        print()
        print("[aggregate] overall")
        print(
            table(
                [[
                    "overall",
                    fmt_num(overall["runs"], 0),
                    fmt_num(overall["success"], 0),
                    fmt_num(overall["success_rate"]),
                    fmt_num(overall["avg_elapsed_all"]),
                    fmt_num(overall["avg_elapsed_success"]),
                    fmt_num(overall["additional_obs_used"], 0),
                    fmt_num(overall["additional_obs_rate"]),
                    fmt_num(overall["avg_planner_retries"]),
                    fmt_num(overall["transport_failure_rate"]),
                    fmt_num(overall["rollback_recovery_rate"]),
                    fmt_num(overall["retry_assisted_recovery_count"], 0),
                    fmt_num(overall["fallback_recovery_count"], 0),
                    fmt_num(overall["minimal_patch_ratio"]),
                    fmt_num(overall["domain_match"], 0),
                    fmt_num(overall["domain_match_rate"]),
                    fmt_num(overall["legacy_detection_match"], 0),
                    fmt_num(overall["legacy_detection_match_rate"]),
                ]],
                headers,
            )
        )

    if args.show_failure_breakdown:
        print()
        print("[aggregate] failure breakdown")
        breakdown_rows: List[List[str]] = []
        for key, m in items:
            fc: Counter = m["failure_counter"]
            if not fc:
                continue
            top = ", ".join(f"{k}:{v}" for k, v in fc.most_common())
            breakdown_rows.append([render_group_name(key, args.group_by), top])

        if breakdown_rows:
            print(table(breakdown_rows, ["group", "failure_buckets"]))
        else:
            print("失敗ケースなし")

    print()


if __name__ == "__main__":
    main()
