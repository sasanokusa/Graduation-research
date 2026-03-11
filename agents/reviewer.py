from __future__ import annotations

import json
import time
from typing import Any

from core.agent_factory import build_chat_model_binding
from core.agent_roles import AgentRole
from core.state import SingleAgentState


REVIEWER_SYSTEM_PROMPT_BLIND = (
    "You are an SRE reviewer analyzing the outcome of a recovery attempt. "
    "Do not propose shell commands. "
    "Return JSON only with the shape "
    '{"decision":"retry|stop","summary":"...","failure_analysis":"...","feedback_for_planner":"...",'
    '"suspected_remaining_domains":[...],"recommended_scope_adjustment":{"editable_files":[...],"services":[...],"allowed_actions":[...]},'
    '"recommended_next_observations":[...]}. '
    "Reason only from the provided evidence and prior turn outcomes. "
    "Do not assume hidden benchmark labels. "
    "Prioritize current-state evidence over historical noise. "
    "If a first-stage repair appears correct but a new downstream fault is now exposed, return decision=retry and explain the remaining fault. "
    "If the previous plan was unsafe, redundant, or there is no evidence-backed next step, return decision=stop."
)

REVIEWER_SYSTEM_PROMPT_HINTED = (
    REVIEWER_SYSTEM_PROMPT_BLIND
    + "Common remaining-fault patterns include downstream query bugs after startup or connectivity issues are repaired, "
    "and newly exposed database authentication errors after proxy reachability is restored."
)


def _section(title: str) -> None:
    divider = "=" * 50
    print(divider)
    print(title)
    print(divider)


def parse_reviewer_text(text: str) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    normalized = {
        "decision": "stop",
        "summary": "",
        "failure_analysis": "",
        "feedback_for_planner": "",
        "suspected_remaining_domains": [],
        "recommended_scope_adjustment": {
            "editable_files": [],
            "services": [],
            "allowed_actions": [],
        },
        "recommended_next_observations": [],
    }
    try:
        payload = json.loads(text)
    except Exception as exc:
        errors.append(f"reviewer output is not valid JSON: {exc}")
        return normalized, errors

    if not isinstance(payload, dict):
        errors.append("reviewer output is not a JSON object")
        return normalized, errors

    decision = str(payload.get("decision", "stop")).strip().lower()
    if decision not in {"retry", "stop"}:
        errors.append(f"unsupported reviewer decision: {decision}")
        decision = "stop"
    normalized["decision"] = decision
    for key in ["summary", "failure_analysis", "feedback_for_planner"]:
        normalized[key] = str(payload.get(key, "")).strip()

    remaining = payload.get("suspected_remaining_domains", [])
    if isinstance(remaining, list):
        normalized["suspected_remaining_domains"] = [str(item).strip() for item in remaining if str(item).strip()]
    else:
        errors.append("suspected_remaining_domains must be a list")

    scope = payload.get("recommended_scope_adjustment", {})
    if isinstance(scope, dict):
        normalized["recommended_scope_adjustment"] = {
            "editable_files": [str(item).strip() for item in scope.get("editable_files", []) if str(item).strip()],
            "services": [str(item).strip() for item in scope.get("services", []) if str(item).strip()],
            "allowed_actions": [str(item).strip() for item in scope.get("allowed_actions", []) if str(item).strip()],
        }
    else:
        errors.append("recommended_scope_adjustment must be an object")

    next_obs = payload.get("recommended_next_observations", [])
    if isinstance(next_obs, list):
        normalized["recommended_next_observations"] = [str(item).strip() for item in next_obs if str(item).strip()]
    else:
        errors.append("recommended_next_observations must be a list")

    return normalized, errors


def _reviewer_prompt(state: SingleAgentState) -> str:
    context = {
        "turn": state.get("planner_turn", 1),
        "suspected_domains": state.get("suspected_domains", []),
        "candidate_scope": state.get("candidate_scope", {}),
        "ambiguity_level": state.get("ambiguity_level", ""),
        "triage_summary": state.get("triage_summary", ""),
        "current_state_evidence": state.get("observation", {}).get("current_state_evidence", []),
        "historical_evidence": state.get("observation", {}).get("historical_evidence", []),
        "proposed_actions": state.get("proposed_actions", []),
        "validated_actions": state.get("verifier_precheck_result", {}).get("validated_actions", []),
        "precheck_summary": {
            "ok": state.get("verifier_precheck_result", {}).get("ok", False),
            "errors": state.get("verifier_precheck_result", {}).get("errors", []),
            "scope_validation_errors": state.get("verifier_precheck_result", {}).get("scope_validation_errors", []),
        },
        "action_results": state.get("execution_result", {}).get("action_results", []),
        "postcheck_summary": {
            "ok": state.get("verifier_postcheck_result", {}).get("ok", False),
            "checks": state.get("verifier_postcheck_result", {}).get("checks", {}),
            "warnings": state.get("verifier_postcheck_result", {}).get("warnings", []),
            "healthz": state.get("verifier_postcheck_result", {}).get("healthz", {}),
            "api_items": state.get("verifier_postcheck_result", {}).get("api_items", {}),
        },
        "rollback_used": state.get("rollback_used", False),
        "rollback_result": state.get("rollback_result", {}),
        "previous_planner_history": state.get("planner_history", []),
        "previous_reviewer_history": state.get("reviewer_history", []),
    }
    return f"Review this recovery attempt and decide whether another planning turn is justified.\n{context}"


def _append_role_trace(
    role_model_trace: list[dict[str, str]],
    *,
    role: str,
    provider: str,
    model: str,
) -> list[dict[str, str]]:
    updated = list(role_model_trace)
    entry = {"role": role, "provider": provider, "model": model}
    if entry not in updated:
        updated.append(entry)
    return updated


def _mock_review(state: SingleAgentState) -> dict[str, Any]:
    scenario = state.get("scenario", "")
    turn = state.get("planner_turn", 1)
    if scenario == "i2" and turn == 1:
        return {
            "decision": "retry",
            "summary": "The first-stage port repair appears correct, but an app-level fault remains.",
            "failure_analysis": "After restoring reachability, the remaining failure moved to /api/items with the app running.",
            "feedback_for_planner": "Focus on app/main.py. A downstream query bug is now exposed and should be repaired with a minimal patch.",
            "suspected_remaining_domains": ["query_or_code_bug"],
            "recommended_scope_adjustment": {
                "editable_files": ["app/main.py"],
                "services": ["app"],
                "allowed_actions": ["edit_file", "rebuild_compose_service"],
            },
            "recommended_next_observations": [],
        }
    if scenario == "n" and turn == 1:
        return {
            "decision": "retry",
            "summary": "The dependency/startup repair was necessary, but a downstream app query fault remains.",
            "failure_analysis": "The app now starts, yet /api/items still fails, indicating a newly exposed query bug.",
            "feedback_for_planner": "Do not touch requirements again. Repair the visible app/main.py query fault and rebuild the app service.",
            "suspected_remaining_domains": ["query_or_code_bug"],
            "recommended_scope_adjustment": {
                "editable_files": ["app/main.py"],
                "services": ["app"],
                "allowed_actions": ["edit_file", "rebuild_compose_service"],
            },
            "recommended_next_observations": [],
        }
    if scenario == "m" and turn == 1:
        return {
            "decision": "retry",
            "summary": "The upstream mismatch was repaired, but a second-layer app/database fault remains.",
            "failure_analysis": "The remaining failure is now inside the app/database path rather than nginx reachability.",
            "feedback_for_planner": "Repair the app env credential drift before attempting any code fix.",
            "suspected_remaining_domains": ["database_auth_or_connectivity_issue"],
            "recommended_scope_adjustment": {
                "editable_files": ["app/app.env"],
                "services": ["app"],
                "allowed_actions": ["edit_file", "rebuild_compose_service"],
            },
            "recommended_next_observations": [],
        }
    if scenario == "m" and turn == 2:
        return {
            "decision": "retry",
            "summary": "The database credential drift was repaired, but a third-layer query bug remains.",
            "failure_analysis": "Health checks improved, but /api/items still fails from an app-level query issue.",
            "feedback_for_planner": "Repair the visible app/main.py query bug with a minimal patch and rebuild the app.",
            "suspected_remaining_domains": ["query_or_code_bug"],
            "recommended_scope_adjustment": {
                "editable_files": ["app/main.py"],
                "services": ["app"],
                "allowed_actions": ["edit_file", "rebuild_compose_service"],
            },
            "recommended_next_observations": [],
        }
    if scenario == "o" and turn == 1:
        return {
            "decision": "retry",
            "summary": "The credential drift was repaired, but stale nginx evidence is not the current blocker.",
            "failure_analysis": "The remaining failure is now the app query path, while nginx errors are only historical noise.",
            "feedback_for_planner": "Ignore stale nginx history. Repair the visible app/main.py query bug.",
            "suspected_remaining_domains": ["query_or_code_bug"],
            "recommended_scope_adjustment": {
                "editable_files": ["app/main.py"],
                "services": ["app"],
                "allowed_actions": ["edit_file", "rebuild_compose_service"],
            },
            "recommended_next_observations": [],
        }
    return {
        "decision": "stop",
        "summary": "No further safe next step is justified.",
        "failure_analysis": "The current evidence does not support another deterministic repair step.",
        "feedback_for_planner": "",
        "suspected_remaining_domains": [],
        "recommended_scope_adjustment": {
            "editable_files": [],
            "services": [],
            "allowed_actions": [],
        },
        "recommended_next_observations": [],
    }


def mock_reviewer_node(state: SingleAgentState) -> SingleAgentState:
    turn = state.get("planner_turn", 1)
    review = _mock_review(state)
    raw_output = json.dumps(review, ensure_ascii=False)
    _section(f"🧪 [PHASE 8] REVIEWER (TURN {turn})")
    print(raw_output)
    print()
    history_entry = {
        "turn": turn,
        "decision": review["decision"],
        "summary": review["summary"],
        "failure_analysis": review["failure_analysis"],
        "feedback_for_planner": review["feedback_for_planner"],
        "suspected_remaining_domains": review["suspected_remaining_domains"],
        "recommended_scope_adjustment": review["recommended_scope_adjustment"],
        "recommended_next_observations": review["recommended_next_observations"],
    }
    return {
        **state,
        "review_feedback": review["feedback_for_planner"],
        "review_decision": review["decision"],
        "reviewer_output_raw": raw_output,
        "reviewer_recommended_scope": review["recommended_scope_adjustment"],
        "reviewer_recommended_next_observations": review["recommended_next_observations"],
        "reviewer_provider": "mock",
        "reviewer_model": "mock-reviewer",
        "reviewer_history": [*state.get("reviewer_history", []), history_entry],
        "agent_role_trace": [*state.get("agent_role_trace", []), f"reviewer:{turn}"],
        "role_model_trace": _append_role_trace(
            state.get("role_model_trace", []),
            role="reviewer",
            provider="mock",
            model="mock-reviewer",
        ),
    }


def reviewer_node(state: SingleAgentState) -> SingleAgentState:
    prompt_mode = state.get("prompt_mode", "blind")
    system_prompt = (
        REVIEWER_SYSTEM_PROMPT_HINTED if prompt_mode == "hinted" else REVIEWER_SYSTEM_PROMPT_BLIND
    )
    binding = build_chat_model_binding(AgentRole.REVIEWER)
    settings = binding.settings
    turn = state.get("planner_turn", 1)
    role_model_trace = _append_role_trace(
        state.get("role_model_trace", []),
        role="reviewer",
        provider=settings.provider,
        model=settings.model,
    )
    agent_role_trace = [*state.get("agent_role_trace", []), f"reviewer:{turn}"]

    if binding.client is None:
        review = {
            "decision": "stop",
            "summary": binding.initialization_error_message,
            "failure_analysis": "Reviewer initialization failed.",
            "feedback_for_planner": "",
            "suspected_remaining_domains": [],
            "recommended_scope_adjustment": {
                "editable_files": [],
                "services": [],
                "allowed_actions": [],
            },
            "recommended_next_observations": [],
        }
        raw_output = json.dumps(review, ensure_ascii=False)
    else:
        raw_output = ""
        review = None
        last_error = ""
        for attempt in range(1, settings.max_attempts + 1):
            attempt_started_at = time.time()
            try:
                print(
                    f"[reviewer] invoking {settings.provider}/{settings.model} "
                    f"attempt={attempt}/{settings.max_attempts} timeout={settings.timeout_seconds}s"
                )
                response = binding.client.invoke(
                    [
                        ("system", system_prompt),
                        ("human", _reviewer_prompt(state)),
                    ]
                )
                raw_output = response.content if isinstance(response.content, str) else str(response.content)
                review, parse_errors = parse_reviewer_text(raw_output)
                if parse_errors:
                    last_error = "; ".join(parse_errors)
                    review["decision"] = "stop"
                    review["failure_analysis"] = (review["failure_analysis"] + " " + last_error).strip()
                break
            except Exception as exc:
                last_error = str(exc)
                if attempt == settings.max_attempts:
                    review = {
                        "decision": "stop",
                        "summary": f"Reviewer invocation failed after {attempt} attempts.",
                        "failure_analysis": last_error,
                        "feedback_for_planner": "",
                        "suspected_remaining_domains": [],
                        "recommended_scope_adjustment": {
                            "editable_files": [],
                            "services": [],
                            "allowed_actions": [],
                        },
                        "recommended_next_observations": [],
                    }
                    raw_output = json.dumps(review, ensure_ascii=False)
                    break
                time.sleep(min(settings.backoff_cap_seconds, settings.backoff_base_seconds * attempt))
        assert review is not None

    _section(f"🧪 [PHASE 8] REVIEWER (TURN {turn})")
    print(raw_output)
    print()
    history_entry = {
        "turn": turn,
        "decision": review["decision"],
        "summary": review["summary"],
        "failure_analysis": review["failure_analysis"],
        "feedback_for_planner": review["feedback_for_planner"],
        "suspected_remaining_domains": review["suspected_remaining_domains"],
        "recommended_scope_adjustment": review["recommended_scope_adjustment"],
        "recommended_next_observations": review["recommended_next_observations"],
    }
    return {
        **state,
        "review_feedback": review["feedback_for_planner"],
        "review_decision": review["decision"],
        "reviewer_output_raw": raw_output,
        "reviewer_recommended_scope": review["recommended_scope_adjustment"],
        "reviewer_recommended_next_observations": review["recommended_next_observations"],
        "reviewer_provider": settings.provider,
        "reviewer_model": settings.model,
        "reviewer_history": [*state.get("reviewer_history", []), history_entry],
        "agent_role_trace": agent_role_trace,
        "role_model_trace": role_model_trace,
    }
