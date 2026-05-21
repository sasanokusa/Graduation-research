import csv
import json
from pathlib import Path

import aggregate_observations


def _write_summary(tmp_path: Path, rows: list[dict[str, str]]) -> Path:
    path = tmp_path / "summary.csv"
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_compute_metrics_counts_pip_startup_failure_as_adjusted_success(tmp_path: Path) -> None:
    result_path = tmp_path / "result.json"
    result_path.write_text(
        json.dumps(
            {
                "action_results": [
                    {"ok": True, "action": {"type": "edit_file", "path": "app/requirements.txt"}},
                    {"ok": True, "action": {"type": "rebuild_compose_service", "service": "app"}},
                ],
                "verifier_postcheck_result": {
                    "ok": False,
                    "compose_ps": {"raw": {"stdout": "app Up 37 seconds (health: starting)"}},
                    "healthz": {"status": 502, "body": "Bad Gateway"},
                    "api_items": {"status": 502, "body": "Bad Gateway"},
                    "recent_logs": {
                        "app": "Collecting fastapi\nDownloading uvicorn-0.35.0-py3-none-any.whl",
                        "nginx": "connect() failed (111: Connection refused)",
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    summary = _write_summary(
        tmp_path,
        [
            {
                "scenario": "n",
                "final_status": "failure",
                "result_json": str(result_path),
                "elapsed_seconds": "10",
            }
        ],
    )

    rows = aggregate_observations.load_rows(summary)
    metrics = aggregate_observations.compute_metrics(rows)

    assert metrics["success"] == 0
    assert metrics["adjusted_success"] == 1
    assert metrics["env_pip_startup_failure"] == 1


def test_compute_metrics_does_not_adjust_unresolved_topology_contract(tmp_path: Path) -> None:
    result_path = tmp_path / "result.json"
    result_path.write_text(
        json.dumps(
            {
                "action_results": [
                    {"ok": True, "action": {"type": "edit_file", "path": "app/app.env"}},
                    {"ok": True, "action": {"type": "rebuild_compose_service", "service": "app"}},
                ],
                "verifier_postcheck_result": {
                    "ok": False,
                    "healthz": {"status": 200},
                    "api_items": {"status": 200},
                    "recent_logs": {"app": "Downloading uvicorn-0.35.0-py3-none-any.whl"},
                    "checks": {
                        "healthz_200": True,
                        "api_items_200": True,
                        "dc_topology_contract_ok": False,
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    summary = _write_summary(
        tmp_path,
        [{"scenario": "x", "final_status": "failure", "result_json": str(result_path)}],
    )

    metrics = aggregate_observations.compute_metrics(aggregate_observations.load_rows(summary))

    assert metrics["adjusted_success"] == 0
    assert metrics["env_pip_startup_failure"] == 0


def test_compute_metrics_counts_safety_and_judge_events(tmp_path: Path) -> None:
    result_path = tmp_path / "result.json"
    result_path.write_text(
        json.dumps(
            {
                "planner_error_type": "empty_plan",
                "action_validation_errors": ["planner returned no executable actions"],
                "judge_history": [
                    {"decision": "retry", "override": False},
                    {"decision": "stop", "override": True},
                ],
                "reviewer_history": [
                    {
                        "summary": (
                            "The provided snippet remains truncated and does not expose "
                            "the exact line needed for replace_text."
                        )
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    summary = _write_summary(
        tmp_path,
        [{"scenario": "x", "final_status": "failure", "result_json": str(result_path)}],
    )

    metrics = aggregate_observations.compute_metrics(aggregate_observations.load_rows(summary))

    assert metrics["safe_empty_plan"] == 1
    assert metrics["unsafe_action_blocked"] == 1
    assert metrics["judge_retry"] == 1
    assert metrics["judge_stop"] == 1
    assert metrics["observability_bottleneck"] == 1
