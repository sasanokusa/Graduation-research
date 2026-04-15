from __future__ import annotations

from copy import deepcopy
from typing import Any


AGENT_ROLES = [
    {
        "role": "observer_agent",
        "responsibility": "Collect current service, HTTP, log, and file-snippet evidence without proposing repairs.",
    },
    {
        "role": "triage_agent",
        "responsibility": "Rank open-world fault-domain hypotheses and derive the current candidate repair scope.",
    },
    {
        "role": "repair_planner_agent",
        "responsibility": "Propose the next bounded, evidence-backed structured repair actions.",
    },
    {
        "role": "verification_reviewer_agent",
        "responsibility": "Review postcheck outcomes, identify exposed downstream faults, and recommend replan scope.",
    },
    {
        "role": "safety_judge_agent",
        "responsibility": "Accept or override reviewer retry/stop decisions based on safety and evidence.",
    },
]


def initial_incident_blackboard() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "agent_roles": deepcopy(AGENT_ROLES),
        "observations": [],
        "hypotheses": [],
        "repair_candidates": [],
        "execution_results": [],
        "verification_results": [],
        "failure_history": [],
        "reviewer_guidance": [],
        "judge_decisions": [],
        "turn_events": [],
        "active_scope": {},
        "active_remaining_domains": [],
        "additional_observation_requests": [],
    }


def ensure_incident_blackboard(state: dict[str, Any]) -> dict[str, Any]:
    blackboard = deepcopy(state.get("incident_blackboard") or initial_incident_blackboard())
    for key, default_value in initial_incident_blackboard().items():
        blackboard.setdefault(key, deepcopy(default_value))
    return blackboard


def _append_limited(items: list[dict[str, Any]], entry: dict[str, Any], *, limit: int = 80) -> list[dict[str, Any]]:
    updated = [*items, entry]
    if len(updated) > limit:
        return updated[-limit:]
    return updated


def _turn(state: dict[str, Any]) -> int:
    return int(state.get("planner_turn", 1) or 1)


def _append_role_trace(state: dict[str, Any], role_event: str) -> list[str]:
    trace = list(state.get("agent_role_trace", []))
    if not trace or trace[-1] != role_event:
        trace.append(role_event)
    return trace


def record_observation(state: dict[str, Any], *, source: str) -> dict[str, Any]:
    blackboard = ensure_incident_blackboard(state)
    observation = state.get("observation", {})
    health_checks = observation.get("health_checks", {})
    entry = {
        "turn": _turn(state),
        "source": source,
        "front_most_failure": observation.get("front_most_failure", ""),
        "healthz_status": health_checks.get("healthz", {}).get("status"),
        "api_items_status": health_checks.get("api_items", {}).get("status"),
        "topology_status": health_checks.get("topology", {}).get("status"),
        "current_state_evidence": observation.get("current_state_evidence", []),
        "historical_evidence": observation.get("historical_evidence", []),
        "additional_observation_count": state.get("additional_observation_count", 0),
    }
    if observation.get("additional_observation"):
        entry["additional_observation"] = observation.get("additional_observation", {})
    blackboard["observations"] = _append_limited(blackboard["observations"], entry)
    return {
        **state,
        "incident_blackboard": blackboard,
        "agent_role_trace": _append_role_trace(state, f"observer_agent:{_turn(state)}"),
    }


def record_triage(state: dict[str, Any]) -> dict[str, Any]:
    blackboard = ensure_incident_blackboard(state)
    entry = {
        "turn": _turn(state),
        "detected_fault_class": state.get("detected_fault_class", ""),
        "detection_confidence": state.get("detection_confidence", 0.0),
        "suspected_domains": state.get("suspected_domains", []),
        "candidate_scope": state.get("candidate_scope", {}),
        "missing_evidence": state.get("missing_evidence", []),
        "recommended_next_observations": state.get("recommended_next_observations", []),
        "ambiguity_level": state.get("ambiguity_level", ""),
        "summary": state.get("triage_summary", ""),
    }
    blackboard["hypotheses"] = _append_limited(blackboard["hypotheses"], entry)
    blackboard["active_scope"] = state.get("candidate_scope", {})
    blackboard["active_remaining_domains"] = state.get("reviewer_suspected_remaining_domains", [])
    if state.get("recommended_next_observations"):
        blackboard["additional_observation_requests"] = _append_limited(
            blackboard["additional_observation_requests"],
            {
                "turn": _turn(state),
                "source": "triage_agent",
                "requests": state.get("recommended_next_observations", []),
            },
        )
    return {
        **state,
        "incident_blackboard": blackboard,
        "agent_role_trace": _append_role_trace(state, f"triage_agent:{_turn(state)}"),
    }


def record_repair_plan(state: dict[str, Any]) -> dict[str, Any]:
    blackboard = ensure_incident_blackboard(state)
    entry = {
        "turn": _turn(state),
        "summary": state.get("planner_summary", ""),
        "actions": state.get("proposed_actions", []),
        "planner_error_type": state.get("planner_error_type", ""),
        "planner_provider": state.get("planner_provider", ""),
        "planner_model": state.get("planner_model", ""),
    }
    blackboard["repair_candidates"] = _append_limited(blackboard["repair_candidates"], entry)
    return {
        **state,
        "incident_blackboard": blackboard,
        "agent_role_trace": _append_role_trace(state, f"repair_planner_agent:{_turn(state)}"),
    }


def record_precheck(state: dict[str, Any]) -> dict[str, Any]:
    blackboard = ensure_incident_blackboard(state)
    precheck = state.get("verifier_precheck_result", {})
    entry = {
        "turn": _turn(state),
        "stage": "precheck",
        "ok": bool(precheck.get("ok")),
        "validated_actions": precheck.get("validated_actions", []),
        "action_validation_errors": precheck.get("action_validation_errors", []),
        "scope_validation_errors": precheck.get("scope_validation_errors", []),
        "success_check_validation_errors": precheck.get("success_check_validation_errors", []),
    }
    blackboard["verification_results"] = _append_limited(blackboard["verification_results"], entry)
    return {**state, "incident_blackboard": blackboard}


def record_execution(state: dict[str, Any]) -> dict[str, Any]:
    blackboard = ensure_incident_blackboard(state)
    execution = state.get("execution_result", {})
    entry = {
        "turn": _turn(state),
        "ok": bool(execution.get("ok")),
        "action_results": execution.get("action_results", []),
        "rollback_used": bool(execution.get("rollback_used")),
        "readiness_wait_requested": bool(execution.get("readiness_wait_requested")),
    }
    blackboard["execution_results"] = _append_limited(blackboard["execution_results"], entry)
    return {**state, "incident_blackboard": blackboard}


def record_postcheck(state: dict[str, Any]) -> dict[str, Any]:
    blackboard = ensure_incident_blackboard(state)
    postcheck = state.get("verifier_postcheck_result", {})
    entry = {
        "turn": _turn(state),
        "stage": "postcheck",
        "ok": bool(postcheck.get("ok")),
        "front_most_failure": postcheck.get("front_most_failure", ""),
        "checks": postcheck.get("checks", {}),
        "warnings": postcheck.get("warnings", []),
    }
    blackboard["verification_results"] = _append_limited(blackboard["verification_results"], entry)
    return {**state, "incident_blackboard": blackboard}


def record_turn_summary(state: dict[str, Any]) -> dict[str, Any]:
    blackboard = ensure_incident_blackboard(state)
    event = {
        "turn": _turn(state),
        "last_turn_success": bool(state.get("last_turn_success")),
        "stop_reason": state.get("multi_agent_stop_reason", ""),
        "front_most_failure": state.get("verifier_postcheck_result", {}).get("front_most_failure", ""),
    }
    blackboard["turn_events"] = _append_limited(blackboard["turn_events"], event)
    if not state.get("last_turn_success"):
        blackboard["failure_history"] = _append_limited(blackboard["failure_history"], event)
    return {**state, "incident_blackboard": blackboard}


def record_review(state: dict[str, Any]) -> dict[str, Any]:
    blackboard = ensure_incident_blackboard(state)
    entry = {
        "turn": _turn(state),
        "decision": state.get("review_decision", ""),
        "feedback_for_planner": state.get("review_feedback", ""),
        "suspected_remaining_domains": state.get("reviewer_suspected_remaining_domains", []),
        "recommended_scope": state.get("reviewer_recommended_scope", {}),
        "recommended_next_observations": state.get("reviewer_recommended_next_observations", []),
    }
    blackboard["reviewer_guidance"] = _append_limited(blackboard["reviewer_guidance"], entry)
    blackboard["active_remaining_domains"] = state.get("reviewer_suspected_remaining_domains", [])
    if state.get("reviewer_recommended_scope"):
        blackboard["active_scope"] = state.get("reviewer_recommended_scope", {})
    if state.get("reviewer_recommended_next_observations"):
        blackboard["additional_observation_requests"] = _append_limited(
            blackboard["additional_observation_requests"],
            {
                "turn": _turn(state),
                "source": "verification_reviewer_agent",
                "requests": state.get("reviewer_recommended_next_observations", []),
            },
        )
    return {
        **state,
        "incident_blackboard": blackboard,
        "agent_role_trace": _append_role_trace(state, f"verification_reviewer_agent:{_turn(state)}"),
    }


def record_judge(state: dict[str, Any]) -> dict[str, Any]:
    blackboard = ensure_incident_blackboard(state)
    entry = {
        "turn": _turn(state),
        "decision": state.get("judge_decision", ""),
        "override": bool(state.get("judge_override")),
        "reasoning": state.get("judge_reasoning", ""),
    }
    blackboard["judge_decisions"] = _append_limited(blackboard["judge_decisions"], entry)
    return {
        **state,
        "incident_blackboard": blackboard,
        "agent_role_trace": _append_role_trace(state, f"safety_judge_agent:{_turn(state)}"),
    }


def merge_reviewer_guidance_into_triage(state: dict[str, Any]) -> dict[str, Any]:
    if state.get("execution_mode") != "multi_agent" or state.get("review_decision") != "retry":
        return state

    candidate_scope = deepcopy(state.get("candidate_scope", {}))
    reviewer_scope = state.get("reviewer_recommended_scope", {}) or {}
    scope_key_map = {
        "files": "editable_files",
        "services": "services",
        "allowed_actions": "allowed_actions",
    }
    for candidate_key, reviewer_key in scope_key_map.items():
        values = [str(item).strip() for item in reviewer_scope.get(reviewer_key, []) if str(item).strip()]
        if values:
            candidate_scope[candidate_key] = values

    original_domains = deepcopy(state.get("suspected_domains", []))
    reviewer_domains = [
        str(domain).strip()
        for domain in state.get("reviewer_suspected_remaining_domains", [])
        if str(domain).strip()
    ]
    if reviewer_domains:
        merged_domains = [
            {
                "domain": domain,
                "confidence": 0.99,
                "evidence": [f"verification reviewer identified remaining domain: {domain}"],
            }
            for domain in reviewer_domains
        ]
        seen = set(reviewer_domains)
        merged_domains.extend(
            domain for domain in original_domains if str(domain.get("domain", "")) not in seen
        )
    else:
        merged_domains = original_domains

    reviewer_observations = [
        str(item).strip()
        for item in state.get("reviewer_recommended_next_observations", [])
        if str(item).strip()
    ]
    recommended_next = list(
        dict.fromkeys([*reviewer_observations, *state.get("recommended_next_observations", [])])
    )
    triage_summary = state.get("triage_summary", "")
    if reviewer_domains or reviewer_scope or reviewer_observations:
        triage_summary = (
            f"{triage_summary} Reviewer guidance from the previous turn was applied to narrow the next planner scope."
        ).strip()

    detected_fault_class = state.get("detected_fault_class", "")
    detection_confidence = state.get("detection_confidence", 0.0)
    detection_evidence = state.get("detection_evidence", [])
    if merged_domains:
        detected_fault_class = merged_domains[0]["domain"]
        detection_confidence = merged_domains[0].get("confidence", detection_confidence)
        detection_evidence = merged_domains[0].get("evidence", detection_evidence)

    worker_visible_context = deepcopy(state.get("worker_visible_context", {}))
    if worker_visible_context:
        candidate_files = set(candidate_scope.get("files", []))
        all_file_snippets = state.get("observation", {}).get("file_snippets", {})
        worker_visible_context["suspected_domains"] = merged_domains
        worker_visible_context["candidate_scope"] = candidate_scope
        worker_visible_context["recommended_next_observations"] = recommended_next
        worker_visible_context["triage_summary"] = triage_summary
        worker_visible_context.setdefault("observation", {})
        worker_visible_context["observation"]["file_snippets"] = {
            path_value: snippet
            for path_value, snippet in all_file_snippets.items()
            if path_value in candidate_files
        }
    triage_iterations = deepcopy(state.get("triage_iterations", []))
    if triage_iterations:
        triage_iterations[-1] = {
            **triage_iterations[-1],
            "detected_fault_class": detected_fault_class,
            "detection_confidence": detection_confidence,
            "detection_evidence": detection_evidence,
            "suspected_domains": merged_domains,
            "candidate_scope": candidate_scope,
            "recommended_next_observations": recommended_next,
            "triage_summary": triage_summary,
            "reviewer_guidance_applied": True,
        }

    return {
        **state,
        "candidate_scope": candidate_scope,
        "planner_input_scope": candidate_scope,
        "suspected_domains": merged_domains,
        "recommended_next_observations": recommended_next,
        "triage_summary": triage_summary,
        "detected_fault_class": detected_fault_class,
        "detection_confidence": detection_confidence,
        "detection_evidence": detection_evidence,
        "worker_visible_context": worker_visible_context,
        "triage_iterations": triage_iterations,
    }
