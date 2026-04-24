from __future__ import annotations

from typing import Any


KNOWN_HYPOTHESIS_LABELS = {
    "nginx_upstream_mismatch",
    "db_auth_failure",
    "db_host_topology_mismatch",
    "dependency_missing",
    "query_bug",
    "stale_evidence_mislead",
    "topology_contract_mismatch",
    "degraded_mode_leak",
    "unknown",
    "recovered",
}

REVIEWER_FEEDBACK_CATEGORIES = {
    "insufficient_evidence",
    "masked_failure_exposed",
    "wrong_scope",
    "unsafe_action",
    "retry_needed",
    "stop_due_to_no_progress",
    "self_critique_retry",
    "none",
    "unknown",
}


def normalize_hypothesis_label(value: Any, evidence: Any = "") -> str:
    value_text = str(value).lower()
    text = f"{value} {evidence}".lower()
    if "recovered" in value_text or value_text in {"success", "ok"}:
        return "recovered"
    if "topology" in text or "service_discovery" in text or "cache_host" in text or "queue_host" in text:
        if "degraded" in text:
            return "degraded_mode_leak"
        if "db_host" in text or "127.0.0.1" in text:
            return "db_host_topology_mismatch"
        return "topology_contract_mismatch"
    if "reverse_proxy" in text or "upstream" in text or "nginx" in text or "proxy" in text:
        return "nginx_upstream_mismatch"
    if "auth" in text or "credential" in text or "access denied" in text or "db_user" in text:
        return "db_auth_failure"
    if "dependency" in text or "requirements" in text or "module" in text or "import" in text:
        return "dependency_missing"
    if "query" in text or "schema" in text or "itemz" in text or "unknown column" in text or "api_items" in text:
        return "query_bug"
    if "stale" in text or "historical" in text or "old log" in text:
        return "stale_evidence_mislead"
    return "unknown"


def categorize_reviewer_feedback(feedback: dict[str, Any] | str, *, self_critique: bool = False) -> str:
    if isinstance(feedback, dict):
        decision = str(feedback.get("decision", "")).lower()
        text = " ".join(
            str(feedback.get(key, ""))
            for key in ["summary", "failure_analysis", "feedback_for_planner", "reasoning"]
        ).lower()
        remaining = " ".join(str(item) for item in feedback.get("suspected_remaining_domains", [])).lower()
        text = f"{decision} {text} {remaining}"
    else:
        text = str(feedback).lower()
        decision = ""

    if self_critique and "retry" in text:
        return "self_critique_retry"
    if "unsafe" in text or "blocked" in text or "outside allowed" in text:
        return "unsafe_action"
    if "wrong scope" in text or "scope" in text and "wrong" in text:
        return "wrong_scope"
    if "insufficient" in text or "not enough evidence" in text or "no evidence" in text:
        return "insufficient_evidence"
    if "downstream" in text or "masked" in text or "exposed" in text or "remaining fault" in text:
        return "masked_failure_exposed"
    if decision == "retry" or "retry" in text:
        return "retry_needed"
    if decision == "stop" or "no progress" in text or "same fault" in text:
        return "stop_due_to_no_progress"
    if not text.strip():
        return "none"
    return "unknown"


def build_hypothesis_log_entry(state: dict[str, Any]) -> dict[str, Any]:
    domains = state.get("suspected_domains", []) or []
    top_domain = domains[0] if domains else {}
    postcheck = state.get("verifier_postcheck_result", {}) or {}
    evidence_items = [
        *state.get("observation", {}).get("current_state_evidence", [])[:3],
        postcheck.get("front_most_failure", ""),
        state.get("planner_summary", ""),
    ]
    evidence_summary = " | ".join(str(item) for item in evidence_items if item)
    primary_source = top_domain.get("domain") or state.get("detected_fault_class") or postcheck.get("front_most_failure")
    primary = normalize_hypothesis_label(primary_source, evidence_summary)
    secondary = []
    for domain in domains[1:4]:
        label = normalize_hypothesis_label(domain.get("domain", ""), domain.get("evidence", ""))
        if label != primary and label not in secondary:
            secondary.append(label)

    previous = (state.get("hypothesis_log") or [])[-1:] or []
    previous_entry = previous[0] if previous else {}
    hypothesis_set = [primary, *secondary]
    previous_set = [
        previous_entry.get("primary_hypothesis", ""),
        *previous_entry.get("secondary_hypotheses", []),
    ]

    return {
        "turn": state.get("planner_turn", 1),
        "primary_hypothesis": primary,
        "secondary_hypotheses": secondary,
        "confidence": float(top_domain.get("confidence", state.get("detection_confidence", 0.0)) or 0.0),
        "evidence_summary": evidence_summary,
        "proposed_action": _summarize_actions(state.get("normalized_actions", [])),
        "reviewer_feedback_category": "none",
        "judge_decision": state.get("judge_decision", ""),
        "hypothesis_changed": bool(previous_entry) and previous_entry.get("primary_hypothesis") != primary,
        "hypothesis_set_changed": bool(previous_entry) and set(previous_set) != set(hypothesis_set),
        "changed_after_critique": False,
        "turn_success": bool(state.get("last_turn_success")),
        "front_most_failure": postcheck.get("front_most_failure", ""),
        "additional_observation_count": state.get("additional_observation_count", 0),
    }


def append_hypothesis_log(state: dict[str, Any]) -> dict[str, Any]:
    entry = build_hypothesis_log_entry(state)
    return {
        **state,
        "hypothesis_log": [*state.get("hypothesis_log", []), entry],
    }


def annotate_latest_hypothesis(
    state: dict[str, Any],
    *,
    reviewer_feedback_category: str | None = None,
    judge_decision: str | None = None,
    changed_after_critique: bool | None = None,
) -> dict[str, Any]:
    log = list(state.get("hypothesis_log", []))
    if not log:
        return state
    latest = dict(log[-1])
    if reviewer_feedback_category is not None:
        latest["reviewer_feedback_category"] = (
            reviewer_feedback_category
            if reviewer_feedback_category in REVIEWER_FEEDBACK_CATEGORIES
            else "unknown"
        )
    if judge_decision is not None:
        latest["judge_decision"] = judge_decision
    if changed_after_critique is not None:
        latest["changed_after_critique"] = bool(changed_after_critique)
    log[-1] = latest
    return {**state, "hypothesis_log": log}


def reviewer_changed_hypothesis(state: dict[str, Any], review: dict[str, Any]) -> bool:
    log = state.get("hypothesis_log", [])
    if not log:
        return False
    current = log[-1].get("primary_hypothesis", "")
    reviewer_labels = {
        normalize_hypothesis_label(domain)
        for domain in review.get("suspected_remaining_domains", [])
    }
    return bool(reviewer_labels and current not in reviewer_labels)


def compute_hypothesis_metrics(log: list[dict[str, Any]]) -> dict[str, Any]:
    if not log:
        return {
            "turn_count": 0,
            "top1_hypothesis_changes": 0,
            "hypothesis_set_updates": 0,
            "critique_count": 0,
            "changed_after_critique_count": 0,
            "critique_change_rate": 0.0,
            "wrong_hypothesis_stickiness": 0,
            "first_fix_success": False,
            "full_recovery": False,
            "reobservation_count": 0,
            "reobservation_effect_count": 0,
        }

    top1_changes = sum(1 for item in log[1:] if item.get("hypothesis_changed"))
    set_updates = sum(1 for item in log[1:] if item.get("hypothesis_set_changed"))
    critique_entries = [
        item
        for item in log
        if item.get("reviewer_feedback_category") not in {"", "none", None}
    ]
    changed_after_critique = sum(1 for item in critique_entries if item.get("changed_after_critique"))
    reobservation_effect_count = 0
    reobservation_count = 0
    for previous, current in zip(log, log[1:]):
        if current.get("additional_observation_count", 0) > previous.get("additional_observation_count", 0):
            reobservation_count += 1
            if current.get("hypothesis_changed") or current.get("hypothesis_set_changed"):
                reobservation_effect_count += 1

    return {
        "turn_count": len(log),
        "top1_hypothesis_changes": top1_changes,
        "hypothesis_set_updates": set_updates,
        "critique_count": len(critique_entries),
        "changed_after_critique_count": changed_after_critique,
        "critique_change_rate": round(changed_after_critique / len(critique_entries), 3)
        if critique_entries
        else 0.0,
        "wrong_hypothesis_stickiness": _max_non_recovered_run(log),
        "first_fix_success": bool(log[0].get("turn_success")),
        "full_recovery": bool(log[-1].get("turn_success")),
        "reobservation_count": reobservation_count,
        "reobservation_effect_count": reobservation_effect_count,
    }


def _max_non_recovered_run(log: list[dict[str, Any]]) -> int:
    longest = 0
    current_label = ""
    current_length = 0
    for item in log:
        label = item.get("primary_hypothesis", "unknown")
        if label == "recovered":
            current_label = ""
            current_length = 0
            continue
        if label == current_label:
            current_length += 1
        else:
            current_label = label
            current_length = 1
        longest = max(longest, current_length)
    return longest


def _summarize_actions(actions: list[dict[str, Any]]) -> str:
    parts = []
    for action in actions[:4]:
        action_type = action.get("type", "")
        target = action.get("path") or action.get("service") or action.get("target") or ""
        parts.append(":".join(str(item) for item in [action_type, target] if item))
    return ", ".join(parts)
