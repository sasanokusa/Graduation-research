import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from agents.judge import parse_judge_output
from agents.reviewer import parse_reviewer_text
from runners.run_multi_minimal import after_review_gate, after_turn_gate, build_app as build_multi_app
from runners.run_self_critique import build_app as build_self_critique_app
from runners.run_single import build_app as build_single_app


ROOT_DIR = Path(__file__).resolve().parents[1]


def _docker_available() -> bool:
    compose_result = subprocess.run(
        ["docker", "compose", "version"],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if compose_result.returncode != 0:
        return False
    daemon_result = subprocess.run(
        ["docker", "info"],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return daemon_result.returncode == 0


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
    assert review["escalate_planner"] is False


def test_parse_reviewer_text_accepts_planner_escalation_request() -> None:
    payload = json.dumps(
        {
            "decision": "retry",
            "summary": "retry with stronger planner",
            "failure_analysis": "the prior planner produced an empty plan despite actionable evidence",
            "feedback_for_planner": "use the visible app/main.py snippet",
            "suspected_remaining_domains": ["query_or_code_bug"],
            "recommended_scope_adjustment": {
                "editable_files": ["app/main.py"],
                "services": ["app"],
                "allowed_actions": ["edit_file", "rebuild_compose_service"],
            },
            "recommended_next_observations": [],
            "escalate_planner": True,
            "escalation_reason": "empty plan after reviewer identified a bounded repair scope",
        }
    )

    review, errors = parse_reviewer_text(payload)

    assert errors == []
    assert review["escalate_planner"] is True
    assert "bounded repair scope" in review["escalation_reason"]


def test_parse_judge_output_accepts_planner_escalation_request() -> None:
    payload = json.dumps(
        {
            "decision": "retry",
            "override": False,
            "reasoning": "reviewer has a justified retry and the next planner should be stronger",
            "escalate_planner": "true",
            "escalation_reason": "unsafe action was blocked; use a higher reasoning planner for the retry",
        }
    )

    judge, errors = parse_judge_output(payload)

    assert errors == []
    assert judge["decision"] == "retry"
    assert judge["escalate_planner"] is True
    assert "higher reasoning planner" in judge["escalation_reason"]


def test_parse_reviewer_text_accepts_fenced_json() -> None:
    payload = """```json
{
  "decision": "retry",
  "summary": "retry once more",
  "failure_analysis": "secondary fault remains",
  "feedback_for_planner": "focus on app/main.py",
  "suspected_remaining_domains": ["query_or_code_bug"],
  "recommended_scope_adjustment": {
    "editable_files": ["app/main.py"],
    "services": ["app"],
    "allowed_actions": ["edit_file", "rebuild_compose_service"]
  },
  "recommended_next_observations": ["expand app snippet"]
}
```"""

    review, errors = parse_reviewer_text(payload)

    assert errors == []
    assert review["decision"] == "retry"
    assert review["feedback_for_planner"] == "focus on app/main.py"
    assert review["recommended_scope_adjustment"]["services"] == ["app"]


def test_parse_reviewer_text_accepts_apostrophe_escape_from_model_output() -> None:
    payload = """```json
{
  "decision": "retry",
  "summary": "Table appdb.itemz doesn\\'t exist",
  "failure_analysis": "The previous fix exposed a query bug.",
  "feedback_for_planner": "Repair app/main.py.",
  "suspected_remaining_domains": ["query_or_code_bug"],
  "recommended_scope_adjustment": {
    "editable_files": ["app/main.py"],
    "services": ["app"],
    "allowed_actions": ["edit_file", "rebuild_compose_service"]
  },
  "recommended_next_observations": []
}
```"""

    review, errors = parse_reviewer_text(payload)

    assert errors == []
    assert review["decision"] == "retry"
    assert review["summary"] == "Table appdb.itemz doesn't exist"


def test_after_review_gate_stops_on_stop_decision() -> None:
    decision = after_review_gate({"review_decision": "stop", "planner_turn": 1})
    assert decision == "stop"


def test_after_turn_gate_respects_max_turns(monkeypatch) -> None:
    monkeypatch.setenv("MULTI_AGENT_MAX_TURNS", "2")
    gate = after_turn_gate({"last_turn_success": False, "planner_turn": 2})
    assert gate == "max_turns"


def test_single_agent_app_still_builds() -> None:
    assert build_single_app("mock") is not None


def test_self_critique_app_builds() -> None:
    assert build_self_critique_app("mock") is not None


def test_multi_agent_app_builds_without_judge(monkeypatch) -> None:
    monkeypatch.setenv("MULTI_AGENT_JUDGE_MODE", "disabled")
    assert build_multi_app("mock") is not None


def _run_mock_multi_scenario(scenario: str) -> dict:
    subprocess.run(["bash", "./reset.sh"], cwd=ROOT_DIR, check=True, timeout=180)
    subprocess.run(["bash", "./break.sh", scenario], cwd=ROOT_DIR, check=True, timeout=180)
    try:
        env = {
            **os.environ,
            "POSTCHECK_RETRY_ATTEMPTS": "45",
            "POSTCHECK_RETRY_INTERVAL_SECONDS": "1",
            "MULTI_AGENT_MAX_TURNS": "3",
            "MULTI_AGENT_MAX_ADDITIONAL_OBSERVATIONS": "3",
        }
        result = subprocess.run(
            [str(ROOT_DIR / ".venv" / "bin" / "python"), "multi_agent.py", "--scenario", scenario, "--worker", "mock", "--prompt-mode", "blind"],
            cwd=ROOT_DIR,
            capture_output=True,
            text=True,
            env=env,
            timeout=900,
        )
        assert result.returncode == 0, result.stdout + "\n" + result.stderr
        match = re.search(r"result_path:\s*(.+)", result.stdout)
        assert match, result.stdout
        result_path = Path(match.group(1).strip())
        assert result_path.exists()
        return json.loads(result_path.read_text())
    finally:
        subprocess.run(["bash", "./reset.sh"], cwd=ROOT_DIR, check=True, timeout=180)


@pytest.mark.integration
@pytest.mark.skipif(not _docker_available(), reason="docker compose is not available")
def test_mock_multi_i2_two_turn_success() -> None:
    payload = _run_mock_multi_scenario("i2")
    assert payload["final_status"] == "success"
    assert payload["planner_turn"] == 2
    assert payload["replan_count"] == 1
    assert len(payload["planner_history"]) == 2
    assert len(payload["reviewer_history"]) == 1
    assert payload["multi_agent_stop_reason"] == "success"
    assert payload["incident_blackboard"]["agent_roles"][0]["role"] == "observer_agent"
    assert payload["incident_blackboard"]["repair_candidates"]
    assert payload["incident_blackboard"]["reviewer_guidance"]


@pytest.mark.integration
@pytest.mark.skipif(not _docker_available(), reason="docker compose is not available")
def test_mock_multi_n_two_turn_success() -> None:
    payload = _run_mock_multi_scenario("n")
    assert payload["final_status"] == "success"
    assert payload["planner_turn"] == 2
    assert payload["replan_count"] == 1
    assert len(payload["planner_history"]) == 2
    assert len(payload["reviewer_history"]) == 1
    assert payload["multi_agent_stop_reason"] == "success"
    assert payload["reviewer_suspected_remaining_domains"] == ["query_or_code_bug"]


@pytest.mark.integration
@pytest.mark.skipif(not _docker_available(), reason="docker compose is not available")
@pytest.mark.parametrize(
    ("scenario", "expected_turns", "expected_replans"),
    [
        ("m", 3, 2),
        ("o", 2, 1),
        ("r", 3, 2),
        ("u", 2, 1),
    ],
)
def test_mock_multi_hard_scenarios_complete_with_blackboard(
    scenario: str,
    expected_turns: int,
    expected_replans: int,
) -> None:
    payload = _run_mock_multi_scenario(scenario)
    assert payload["final_status"] == "success"
    assert payload["planner_turn"] == expected_turns
    assert payload["replan_count"] == expected_replans
    assert len(payload["planner_history"]) == expected_turns
    assert len(payload["reviewer_history"]) == expected_replans
    assert len(payload["judge_history"]) == expected_replans
    assert payload["multi_agent_stop_reason"] == "success"

    blackboard = payload["incident_blackboard"]
    assert {role["role"] for role in blackboard["agent_roles"]} == {
        "observer_agent",
        "triage_agent",
        "repair_planner_agent",
        "verification_reviewer_agent",
        "safety_judge_agent",
    }
    assert len(blackboard["repair_candidates"]) == expected_turns
    assert len(blackboard["reviewer_guidance"]) == expected_replans
    assert len(blackboard["failure_history"]) == expected_replans
