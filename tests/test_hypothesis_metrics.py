from core.hypothesis import (
    append_hypothesis_log,
    categorize_reviewer_feedback,
    compute_hypothesis_metrics,
    normalize_hypothesis_label,
)


def test_normalize_hypothesis_label_maps_common_faults() -> None:
    assert normalize_hypothesis_label("reverse_proxy_or_upstream_mismatch") == "nginx_upstream_mismatch"
    assert normalize_hypothesis_label("database auth failed") == "db_auth_failure"
    assert normalize_hypothesis_label("DB_HOST=127.0.0.1 topology fault") == "db_host_topology_mismatch"
    assert normalize_hypothesis_label("table itemz does not exist") == "query_bug"


def test_append_hypothesis_log_detects_top1_change() -> None:
    state = {
        "planner_turn": 1,
        "suspected_domains": [{"domain": "reverse_proxy_or_upstream_mismatch", "confidence": 0.8}],
        "detection_confidence": 0.8,
        "observation": {"current_state_evidence": ["nginx points to wrong upstream"]},
        "verifier_postcheck_result": {"front_most_failure": "nginx_front"},
        "normalized_actions": [{"type": "edit_file", "path": "nginx/nginx.conf"}],
        "last_turn_success": False,
        "hypothesis_log": [],
    }
    state = append_hypothesis_log(state)
    state = append_hypothesis_log(
        {
            **state,
            "planner_turn": 2,
            "suspected_domains": [{"domain": "query_or_code_bug", "confidence": 0.9}],
            "observation": {"current_state_evidence": ["itemz query failure"]},
            "verifier_postcheck_result": {"front_most_failure": "query_bug_front"},
            "normalized_actions": [{"type": "edit_file", "path": "app/main.py"}],
        }
    )

    assert state["hypothesis_log"][1]["hypothesis_changed"] is True
    metrics = compute_hypothesis_metrics(state["hypothesis_log"])
    assert metrics["top1_hypothesis_changes"] == 1
    assert metrics["wrong_hypothesis_stickiness"] == 1


def test_reviewer_feedback_category_identifies_masked_failure() -> None:
    category = categorize_reviewer_feedback(
        {
            "decision": "retry",
            "summary": "A downstream query bug is now exposed.",
            "failure_analysis": "The first repair revealed a remaining fault.",
            "feedback_for_planner": "Repair app/main.py.",
            "suspected_remaining_domains": ["query_or_code_bug"],
        }
    )

    assert category == "masked_failure_exposed"
