from core.escalation import should_use_requested_planner_escalation


def test_planner_escalation_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("PLANNER_ESCALATION_MODE", raising=False)

    use_escalation, reason = should_use_requested_planner_escalation(
        {
            "planner_escalation_requested": True,
            "planner_escalation_reason": "reviewer requested stronger planner",
            "planner_escalation_history": [],
        },
        source="reviewer",
    )

    assert use_escalation is False
    assert "disabled" in reason


def test_planner_escalation_honors_source_trigger_and_budget(monkeypatch) -> None:
    monkeypatch.setenv("PLANNER_ESCALATION_MODE", "enabled")
    monkeypatch.setenv("PLANNER_ESCALATION_TRIGGERS", "judge_request")
    monkeypatch.setenv("PLANNER_ESCALATION_MAX_PER_RUN", "1")

    use_escalation, reason = should_use_requested_planner_escalation(
        {
            "planner_escalation_requested": True,
            "planner_escalation_reason": "judge requested stronger planner",
            "planner_escalation_history": [],
        },
        source="judge",
    )

    assert use_escalation is True
    assert reason == "judge requested stronger planner"

    use_escalation, reason = should_use_requested_planner_escalation(
        {
            "planner_escalation_requested": True,
            "planner_escalation_reason": "judge requested stronger planner again",
            "planner_escalation_history": [{"turn": 2}],
        },
        source="judge",
    )

    assert use_escalation is False
    assert "budget" in reason
