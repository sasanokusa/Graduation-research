import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from agents.reviewer import parse_reviewer_text
from runners.run_multi_minimal import after_review_gate, after_turn_gate
from runners.run_single import build_app as build_single_app


ROOT_DIR = Path(__file__).resolve().parents[1]


def _docker_available() -> bool:
    result = subprocess.run(
        ["docker", "compose", "version"],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.returncode == 0


def test_parse_reviewer_text_normalizes_schema() -> None:
    payload = json.dumps(
        {
            "decision": "retry",
            "summary": "retry once more",
            "failure_analysis": "secondary fault remains",
            "feedback_for_planner": "focus on app/main.py",
            "suspected_remaining_domains": ["query_or_code_bug"],
            "recommended_scope_adjustment": {
                "editable_files": ["app/main.py"],
                "services": ["app"],
                "allowed_actions": ["edit_file", "rebuild_compose_service"],
            },
            "recommended_next_observations": ["expand app snippet"],
        }
    )
    review, errors = parse_reviewer_text(payload)
    assert errors == []
    assert review["decision"] == "retry"
    assert review["recommended_scope_adjustment"]["editable_files"] == ["app/main.py"]


def test_after_review_gate_stops_on_stop_decision() -> None:
    decision = after_review_gate({"review_decision": "stop", "planner_turn": 1})
    assert decision == "stop"


def test_after_turn_gate_respects_max_turns(monkeypatch) -> None:
    monkeypatch.setenv("MULTI_AGENT_MAX_TURNS", "2")
    gate = after_turn_gate({"last_turn_success": False, "planner_turn": 2})
    assert gate == "max_turns"


def test_single_agent_app_still_builds() -> None:
    assert build_single_app("mock") is not None


def _run_mock_multi_scenario(scenario: str) -> dict:
    subprocess.run(["bash", "./reset.sh"], cwd=ROOT_DIR, check=True, timeout=180)
    subprocess.run(["bash", "./break.sh", scenario], cwd=ROOT_DIR, check=True, timeout=180)
    try:
        env = {
            **os.environ,
            "POSTCHECK_RETRY_ATTEMPTS": "10",
            "POSTCHECK_RETRY_INTERVAL_SECONDS": "1",
            "MULTI_AGENT_MAX_TURNS": "3",
        }
        result = subprocess.run(
            [str(ROOT_DIR / ".venv" / "bin" / "python"), "multi_agent.py", "--scenario", scenario, "--worker", "mock", "--prompt-mode", "blind"],
            cwd=ROOT_DIR,
            capture_output=True,
            text=True,
            env=env,
            timeout=420,
        )
        assert result.returncode == 0, result.stdout + "\n" + result.stderr
        match = re.search(r"result_path:\s*(.+)", result.stdout)
        assert match, result.stdout
        result_path = Path(match.group(1).strip())
        assert result_path.exists()
        return json.loads(result_path.read_text())
    finally:
        subprocess.run(["bash", "./reset.sh"], cwd=ROOT_DIR, check=True, timeout=180)


@pytest.mark.skipif(not _docker_available(), reason="docker compose is not available")
def test_mock_multi_i2_two_turn_success() -> None:
    payload = _run_mock_multi_scenario("i2")
    assert payload["final_status"] == "success"
    assert payload["planner_turn"] == 2
    assert payload["replan_count"] == 1
    assert len(payload["planner_history"]) == 2
    assert len(payload["reviewer_history"]) == 1
    assert payload["multi_agent_stop_reason"] == "success"


@pytest.mark.skipif(not _docker_available(), reason="docker compose is not available")
def test_mock_multi_n_two_turn_success() -> None:
    payload = _run_mock_multi_scenario("n")
    assert payload["final_status"] == "success"
    assert payload["planner_turn"] == 2
    assert payload["replan_count"] == 1
    assert len(payload["planner_history"]) == 2
    assert len(payload["reviewer_history"]) == 1
    assert payload["multi_agent_stop_reason"] == "success"
