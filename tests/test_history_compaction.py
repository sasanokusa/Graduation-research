import pytest

from agents.judge import _judge_prompt
from agents.reviewer import _reviewer_prompt
from core.history_compaction import (
    compact_planner_history,
    compact_reviewer_history,
    history_tail,
)


def _planner_entries(count: int) -> list[dict]:
    return [
        {
            "turn": turn,
            "summary": f"summary turn {turn}",
            "proposed_actions": [{"type": "edit_file", "path": "app/app.env"}],
            "validated_actions": [{"type": "edit_file", "path": "app/app.env"}],
            "planner_attempts": [{"raw_output": f"long raw planner output {turn}"}],
            "precheck_ok": True,
            "execution_ok": True,
            "postcheck_ok": False,
            "rollback_used": False,
            "planner_escalation_used": False,
        }
        for turn in range(1, count + 1)
    ]


def _reviewer_entries(count: int) -> list[dict]:
    return [
        {
            "turn": turn,
            "decision": "retry",
            "summary": f"reviewer summary {turn}",
            "failure_analysis": f"long failure analysis {turn}",
            "feedback_for_planner": f"feedback {turn}",
            "recommended_scope_adjustment": {"editable_files": ["app/app.env"]},
        }
        for turn in range(1, count + 1)
    ]


def test_history_tail_defaults_to_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MULTI_AGENT_HISTORY_TAIL", raising=False)
    assert history_tail() == 0


def test_history_tail_rejects_invalid_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MULTI_AGENT_HISTORY_TAIL", "abc")
    assert history_tail() == 0
    monkeypatch.setenv("MULTI_AGENT_HISTORY_TAIL", "-2")
    assert history_tail() == 0


def test_compaction_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MULTI_AGENT_HISTORY_TAIL", raising=False)
    entries = _planner_entries(4)
    assert compact_planner_history(entries) is entries
    reviewer_entries = _reviewer_entries(4)
    assert compact_reviewer_history(reviewer_entries) is reviewer_entries


def test_planner_history_tail_keeps_newest_verbatim(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MULTI_AGENT_HISTORY_TAIL", "1")
    entries = _planner_entries(3)
    compacted = compact_planner_history(entries)
    assert len(compacted) == 3
    assert compacted[-1] == entries[-1]
    for digest in compacted[:-1]:
        assert digest["compacted"] is True
        assert "planner_attempts" not in digest
        assert "proposed_actions" not in digest
        assert digest["proposed_action_count"] == 1
        assert digest["summary"].startswith("summary turn")


def test_reviewer_history_tail_keeps_newest_verbatim(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MULTI_AGENT_HISTORY_TAIL", "2")
    entries = _reviewer_entries(4)
    compacted = compact_reviewer_history(entries)
    assert compacted[-2:] == entries[-2:]
    for digest in compacted[:-2]:
        assert digest["compacted"] is True
        assert "failure_analysis" not in digest
        assert digest["feedback_for_planner"].startswith("feedback")


def test_tail_larger_than_history_is_a_no_op(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MULTI_AGENT_HISTORY_TAIL", "5")
    entries = _planner_entries(3)
    assert compact_planner_history(entries) is entries


def _multi_turn_state() -> dict:
    return {
        "planner_turn": 4,
        "planner_history": _planner_entries(3),
        "reviewer_history": _reviewer_entries(3),
        "incident_blackboard": {},
        "observation": {},
    }


def test_reviewer_prompt_respects_history_tail(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _multi_turn_state()
    monkeypatch.delenv("MULTI_AGENT_HISTORY_TAIL", raising=False)
    full_prompt = _reviewer_prompt(state)
    monkeypatch.setenv("MULTI_AGENT_HISTORY_TAIL", "1")
    compact_prompt = _reviewer_prompt(state)
    assert len(compact_prompt) < len(full_prompt)
    assert "long raw planner output 1" not in compact_prompt
    assert "long raw planner output 3" in compact_prompt


def test_judge_prompt_respects_history_tail(monkeypatch: pytest.MonkeyPatch) -> None:
    state = _multi_turn_state()
    monkeypatch.delenv("MULTI_AGENT_HISTORY_TAIL", raising=False)
    full_prompt = _judge_prompt(state)
    monkeypatch.setenv("MULTI_AGENT_HISTORY_TAIL", "1")
    compact_prompt = _judge_prompt(state)
    assert len(compact_prompt) < len(full_prompt)
    assert "long failure analysis 1" not in compact_prompt
    assert "feedback 1" in compact_prompt
