from __future__ import annotations

import json
import time
from typing import Any

from agents.reviewer import parse_reviewer_text
from core.agent_factory import build_chat_model_binding
from core.agent_roles import AgentRole
from core.hypothesis import annotate_latest_hypothesis, categorize_reviewer_feedback, reviewer_changed_hypothesis
from core.llm_usage import extract_token_usage
from core.state import SingleAgentState


SELF_CRITIQUE_SYSTEM_PROMPT = (
    "You are the same single-agent repair planner reviewing your previous repair attempt. "
    "Do not introduce a separate reviewer persona. "
    "Return JSON only with the shape "
    '{"decision":"retry|stop","summary":"...","failure_analysis":"...","feedback_for_planner":"...",'
    '"suspected_remaining_domains":[...],"recommended_scope_adjustment":{"editable_files":[...],"services":[...],"allowed_actions":[...]},'
    '"recommended_next_observations":[...]}. '
    "Use only current evidence, the prior plan, and postcheck results. "
    "If a newly exposed downstream fault is repairable within scope, return retry. "
    "If there is no evidence-backed next step or the prior action repeated without progress, return stop."
)


def _section(title: str) -> None:
    divider = "=" * 50
    print(divider)
    print(title)
    print(divider)


def _self_critique_prompt(state: SingleAgentState) -> str:
    context = {
        "turn": state.get("planner_turn", 1),
        "suspected_domains": state.get("suspected_domains", []),
        "candidate_scope": state.get("candidate_scope", {}),
        "current_state_evidence": state.get("observation", {}).get("current_state_evidence", []),
        "historical_evidence": state.get("observation", {}).get("historical_evidence", []),
        "previous_plans": state.get("planner_history", []),
        "latest_actions": state.get("proposed_actions", []),
        "precheck": state.get("verifier_precheck_result", {}),
        "execution": state.get("execution_result", {}),
        "postcheck": state.get("verifier_postcheck_result", {}),
        "hypothesis_log": state.get("hypothesis_log", []),
    }
    return "Self-critique the latest single-agent repair turn and decide whether to replan.\n" + json.dumps(
        context,
        ensure_ascii=False,
        indent=2,
    )


def mock_self_critique_node(state: SingleAgentState) -> SingleAgentState:
    review = {
        "decision": "retry" if state.get("planner_turn", 1) < 3 else "stop",
        "summary": "Mock self-critique: retry while turn budget remains.",
        "failure_analysis": "The previous single-agent repair did not fully recover the scenario.",
        "feedback_for_planner": "Use the latest postcheck failure as the next hypothesis and avoid repeating the same action.",
        "suspected_remaining_domains": [],
        "recommended_scope_adjustment": {},
        "recommended_next_observations": [],
    }
    raw_output = json.dumps(review, ensure_ascii=False)
    return _apply_self_critique_result(state, review, raw_output, provider="mock", model="mock-self-critic")


def self_critique_node(state: SingleAgentState) -> SingleAgentState:
    binding = build_chat_model_binding(AgentRole.SINGLE_AGENT)
    settings = binding.settings
    if binding.client is None:
        review = {
            "decision": "stop",
            "summary": binding.initialization_error_message,
            "failure_analysis": "Self-critique initialization failed.",
            "feedback_for_planner": "",
            "suspected_remaining_domains": [],
            "recommended_scope_adjustment": {},
            "recommended_next_observations": [],
        }
        raw_output = json.dumps(review, ensure_ascii=False)
        return _apply_self_critique_result(state, review, raw_output, provider=settings.provider, model=settings.model)

    raw_output = ""
    review: dict[str, Any] | None = None
    token_usage: dict[str, Any] = {}
    last_error = ""
    for attempt in range(1, settings.max_attempts + 1):
        try:
            print(
                f"[self-critique] invoking {settings.provider}/{settings.model} "
                f"attempt={attempt}/{settings.max_attempts} timeout={settings.timeout_seconds}s"
            )
            response = binding.client.invoke(
                [
                    ("system", SELF_CRITIQUE_SYSTEM_PROMPT),
                    ("human", _self_critique_prompt(state)),
                ]
            )
            raw_output = response.content if isinstance(response.content, str) else str(response.content)
            token_usage = extract_token_usage(response)
            review, parse_errors = parse_reviewer_text(raw_output)
            if parse_errors:
                review["decision"] = "stop"
                review["failure_analysis"] = (review["failure_analysis"] + " " + "; ".join(parse_errors)).strip()
            break
        except Exception as exc:
            last_error = str(exc)
            if attempt == settings.max_attempts:
                review = {
                    "decision": "stop",
                    "summary": f"Self-critique invocation failed after {attempt} attempts.",
                    "failure_analysis": last_error,
                    "feedback_for_planner": "",
                    "suspected_remaining_domains": [],
                    "recommended_scope_adjustment": {},
                    "recommended_next_observations": [],
                }
                raw_output = json.dumps(review, ensure_ascii=False)
                break
            time.sleep(min(settings.backoff_cap_seconds, settings.backoff_base_seconds * attempt))

    assert review is not None
    updated = _apply_self_critique_result(state, review, raw_output, provider=settings.provider, model=settings.model)
    latest_history = [*updated.get("self_critique_history", [])]
    if latest_history:
        latest_history[-1]["token_usage"] = token_usage
        latest_history[-1]["error"] = last_error
    return {**updated, "self_critique_history": latest_history}


def _apply_self_critique_result(
    state: SingleAgentState,
    review: dict[str, Any],
    raw_output: str,
    *,
    provider: str,
    model: str,
) -> SingleAgentState:
    turn = state.get("planner_turn", 1)
    _section(f"[SELF-CRITIQUE] TURN {turn}")
    print(raw_output)
    print()
    history_entry = {
        "turn": turn,
        "decision": review["decision"],
        "summary": review["summary"],
        "failure_analysis": review["failure_analysis"],
        "feedback_for_planner": review["feedback_for_planner"],
        "suspected_remaining_domains": review.get("suspected_remaining_domains", []),
        "recommended_scope_adjustment": review.get("recommended_scope_adjustment", {}),
        "recommended_next_observations": review.get("recommended_next_observations", []),
        "provider": provider,
        "model": model,
    }
    updated = {
        **state,
        "review_feedback": review["feedback_for_planner"],
        "review_decision": review["decision"],
        "reviewer_output_raw": raw_output,
        "reviewer_recommended_scope": review.get("recommended_scope_adjustment", {}),
        "reviewer_recommended_next_observations": review.get("recommended_next_observations", []),
        "reviewer_suspected_remaining_domains": review.get("suspected_remaining_domains", []),
        "reviewer_provider": provider,
        "reviewer_model": model,
        "reviewer_history": [*state.get("reviewer_history", []), {**history_entry, "critic_role": "self"}],
        "self_critique_history": [*state.get("self_critique_history", []), history_entry],
        "agent_role_trace": [*state.get("agent_role_trace", []), f"self_critique:{turn}"],
    }
    return annotate_latest_hypothesis(
        updated,
        reviewer_feedback_category=categorize_reviewer_feedback(review, self_critique=True),
        changed_after_critique=reviewer_changed_hypothesis(updated, review),
    )
