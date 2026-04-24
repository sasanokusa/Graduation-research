import csv
import json
import subprocess
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


def test_aggregate_hypothesis_metrics_from_result_json(tmp_path: Path) -> None:
    result = tmp_path / "result.json"
    output = tmp_path / "metrics.csv"
    result.write_text(
        json.dumps(
            {
                "execution_mode": "single_agent_self_critique",
                "baseline_condition": "single_agent_iterative_self_critique",
                "scenario": "m",
                "final_status": "success",
                "hypothesis_log": [
                    {
                        "primary_hypothesis": "nginx_upstream_mismatch",
                        "secondary_hypotheses": [],
                        "reviewer_feedback_category": "masked_failure_exposed",
                        "changed_after_critique": True,
                        "turn_success": False,
                    },
                    {
                        "primary_hypothesis": "query_bug",
                        "secondary_hypotheses": [],
                        "hypothesis_changed": True,
                        "reviewer_feedback_category": "none",
                        "turn_success": True,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    subprocess.run(
        [
            str(ROOT_DIR / ".venv" / "bin" / "python"),
            "aggregate_hypothesis_metrics.py",
            str(result),
            "--output",
            str(output),
        ],
        cwd=ROOT_DIR,
        check=True,
    )

    rows = list(csv.DictReader(output.open(encoding="utf-8")))
    assert rows[0]["baseline_condition"] == "single_agent_iterative_self_critique"
    assert rows[0]["top1_hypothesis_changes"] == "1"
    assert rows[0]["changed_after_critique_count"] == "1"
