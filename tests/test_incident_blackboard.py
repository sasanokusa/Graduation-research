from core.incident_blackboard import (
    AGENT_ROLES,
    initial_incident_blackboard,
    merge_reviewer_guidance_into_triage,
    record_review,
)


def test_initial_blackboard_declares_phase1_roles() -> None:
    blackboard = initial_incident_blackboard()
    assert [role["role"] for role in blackboard["agent_roles"]] == [
        "observer_agent",
        "triage_agent",
        "repair_planner_agent",
        "verification_reviewer_agent",
        "safety_judge_agent",
    ]
    assert blackboard["observations"] == []
    assert blackboard["failure_history"] == []
    assert AGENT_ROLES[0]["role"] == "observer_agent"


def test_record_review_updates_active_blackboard_guidance() -> None:
    state = {
        "planner_turn": 1,
        "incident_blackboard": initial_incident_blackboard(),
        "review_decision": "retry",
        "review_feedback": "repair app/main.py next",
        "reviewer_suspected_remaining_domains": ["query_or_code_bug"],
        "reviewer_recommended_scope": {
            "editable_files": ["app/main.py"],
            "services": ["app"],
            "allowed_actions": ["edit_file", "rebuild_compose_service"],
        },
        "reviewer_recommended_next_observations": ["extract narrower relevant snippet from app/main.py"],
        "agent_role_trace": [],
    }
    updated = record_review(state)
    blackboard = updated["incident_blackboard"]
    assert blackboard["active_remaining_domains"] == ["query_or_code_bug"]
    assert blackboard["active_scope"]["editable_files"] == ["app/main.py"]
    assert blackboard["reviewer_guidance"][0]["decision"] == "retry"


def test_reviewer_guidance_narrows_next_triage_scope() -> None:
    state = {
        "execution_mode": "multi_agent",
        "review_decision": "retry",
        "reviewer_suspected_remaining_domains": ["query_or_code_bug"],
        "reviewer_recommended_scope": {
            "editable_files": ["app/main.py"],
            "services": ["app"],
            "allowed_actions": ["edit_file", "rebuild_compose_service"],
        },
        "reviewer_recommended_next_observations": ["extract narrower relevant snippet from app/main.py"],
        "candidate_scope": {
            "files": ["nginx/nginx.conf", "app/app.env", "app/main.py"],
            "services": ["nginx", "app"],
            "allowed_actions": ["edit_file", "restart_compose_service", "rebuild_compose_service"],
        },
        "suspected_domains": [
            {"domain": "ambiguous_service_disagreement", "confidence": 0.6, "evidence": ["broad"]}
        ],
        "recommended_next_observations": ["expand app log excerpt"],
        "triage_summary": "broad triage",
        "detected_fault_class": "ambiguous_service_disagreement",
        "detection_confidence": 0.6,
        "detection_evidence": ["broad"],
    }
    updated = merge_reviewer_guidance_into_triage(state)
    assert updated["candidate_scope"]["files"] == ["app/main.py"]
    assert updated["candidate_scope"]["services"] == ["app"]
    assert updated["candidate_scope"]["allowed_actions"] == ["edit_file", "rebuild_compose_service"]
    assert updated["suspected_domains"][0]["domain"] == "query_or_code_bug"
    assert updated["detected_fault_class"] == "query_or_code_bug"
    assert updated["recommended_next_observations"][0] == "extract narrower relevant snippet from app/main.py"
