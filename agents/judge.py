"""Judge agent that evaluates Reviewer decisions and optionally overrides them."""

from __future__ import annotations

import json
import os
import time
from typing import Any

from core.agent_factory import build_chat_model_binding
from core.agent_roles import AgentRole
from core.escalation import planner_escalation_request_from_judge
from core.history_compaction import (
    compact_incident_blackboard,
    compact_planner_history,
    compact_reviewer_history,
)
from core.hypothesis import annotate_latest_hypothesis
from core.llm_usage import extract_token_usage
from core.state import SingleAgentState

JUDGE_SYSTEM_PROMPT = (
    "You are a meta-reviewer (judge) that evaluates whether the reviewer's decision is correct. "
    "You receive the reviewer output, planner history, and postcheck results. "
    "Your job is to decide whether to accept or override the reviewer's decision.\n\n"
    "Override criteria:\n"
    "- retry->stop: Override if the reviewer wants to retry but there is no evidence-backed next step, "
    "the planner has already failed on the same fault twice, or the remaining fault is outside the allowed scope.\n"
    "- stop->retry: Override if the reviewer wants to stop but the postcheck clearly shows a new downstream fault "
    "that was previously masked and is now repairable with the available scope, or if a canonical additional observation can expose the exact editable line for an in-scope fault. "
    "A reviewer stop is too early when it also lists recommended_next_observations that could localize an in-scope repair.\n\n"
    "Planner escalation criteria:\n"
    "- Set escalate_planner=true only when decision=retry and the retry has a bounded, evidence-backed repair scope, "
    "but the previous planner returned an empty plan, repeated an unsafe or precheck-blocked action, or failed to use the reviewer-provided scope.\n"
    "- A retry after a partial env/config repair is evidence-backed only when additional observation or visible snippets expose the remaining exact editable lines.\n"
    "- Do not recommend restore_from_base; it restores hidden baseline answers and is blocked in controlled experiments.\n"
    "- Keep escalate_planner=false when the blocker is missing evidence; prefer additional observation rather than a stronger planner.\n\n"
    "Return JSON only with the shape:\n"
    '{"decision":"retry|stop","override":true|false,"reasoning":"...",'
    '"escalate_planner":true|false,"escalation_reason":"..."}\n\n'
    "If override is false, decision must match the reviewer's decision.\n"
    "If override is true, decision must differ from the reviewer's decision.\n"
    "Return ONLY the JSON, no surrounding text."
)


def parse_judge_output(text: str) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    normalized = {
        "decision": "stop",
        "override": False,
        "reasoning": "",
        "escalate_planner": False,
        "escalation_reason": "",
    }
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        start = 1 if lines[0].startswith("```") else 0
        end = len(lines)
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].strip() == "```":
                end = i
                break
        text = "\n".join(lines[start:end])

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        errors.append(f"judge output is not valid JSON: {exc}")
        return normalized, errors

    if not isinstance(payload, dict):
        errors.append("judge output is not a JSON object")
        return normalized, errors

    decision = str(payload.get("decision", "stop")).strip().lower()
    if decision not in {"retry", "stop"}:
        errors.append(f"unsupported judge decision: {decision}")
        decision = "stop"
    normalized["decision"] = decision

    override = payload.get("override", False)
    if isinstance(override, bool):
        normalized["override"] = override
    elif isinstance(override, str):
        normalized["override"] = override.lower() in ("true", "yes", "1")
    else:
        normalized["override"] = bool(override)

    normalized["reasoning"] = str(payload.get("reasoning", "")).strip()
    escalate = payload.get("escalate_planner", False)
    if isinstance(escalate, bool):
        normalized["escalate_planner"] = escalate
    elif isinstance(escalate, str):
        normalized["escalate_planner"] = escalate.strip().lower() in {"true", "yes", "1"}
    else:
        normalized["escalate_planner"] = bool(escalate)
    normalized["escalation_reason"] = str(payload.get("escalation_reason", "")).strip()
    return normalized, errors


def _judge_prompt(state: SingleAgentState) -> str:
    context = {
        "turn": state.get("planner_turn", 1),
        "reviewer_decision": state.get("review_decision", ""),
        "reviewer_feedback": state.get("review_feedback", ""),
        "reviewer_recommended_scope": state.get("reviewer_recommended_scope", {}),
        "postcheck_summary": {
            "ok": state.get("verifier_postcheck_result", {}).get("ok", False),
            "checks": state.get("verifier_postcheck_result", {}).get("checks", {}),
            "warnings": state.get("verifier_postcheck_result", {}).get("warnings", []),
        },
        "planner_history": compact_planner_history(state.get("planner_history", [])),
        "reviewer_history": compact_reviewer_history(state.get("reviewer_history", [])),
        "candidate_scope": state.get("candidate_scope", {}),
        "ambiguity_level": state.get("ambiguity_level", ""),
        "incident_blackboard": compact_incident_blackboard(state.get("incident_blackboard", {})),
    }
    return (
        "Evaluate the reviewer's decision and decide whether to accept or override it.\n"
        + json.dumps(context, ensure_ascii=False, indent=2)
    )


def _section(title: str) -> None:
    divider = "=" * 50
    print(divider)
    print(title)
    print(divider)


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return int(float(value))
    except ValueError:
        return default


def judge_invocation_failure_retries() -> int:
    role_value = os.getenv("JUDGE_INVOCATION_FAILURE_RETRIES", "").strip()
    if role_value:
        return max(0, _env_int("JUDGE_INVOCATION_FAILURE_RETRIES", 2))
    return max(0, _env_int("LLM_INVOCATION_FAILURE_RETRIES", 2))


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


def mock_judge_node(state: SingleAgentState) -> SingleAgentState:
    """Pass through the reviewer's decision without modification."""
    turn = state.get("planner_turn", 1)
    reviewer_decision = state.get("review_decision", "stop")
    judge_result = {
        "decision": reviewer_decision,
        "override": False,
        "reasoning": "Mock judge: accepting reviewer decision without override.",
    }
    raw_output = json.dumps(judge_result, ensure_ascii=False)
    _section(f"[PHASE 9] JUDGE (TURN {turn})")
    print(raw_output)
    print()
    history_entry = {
        "turn": turn,
        "decision": judge_result["decision"],
        "override": judge_result["override"],
        "reasoning": judge_result["reasoning"],
        "escalate_planner": judge_result.get("escalate_planner", False),
        "escalation_reason": judge_result.get("escalation_reason", ""),
    }
    escalate_planner, escalation_reason = planner_escalation_request_from_judge(judge_result)
    updated = {
        **state,
        "judge_decision": judge_result["decision"],
        "judge_output_raw": raw_output,
        "judge_reasoning": judge_result["reasoning"],
        "judge_override": judge_result["override"],
        "planner_escalation_requested": escalate_planner or state.get("planner_escalation_requested", False),
        "planner_escalation_source": "judge" if escalate_planner else state.get("planner_escalation_source", ""),
        "planner_escalation_reason": escalation_reason if escalate_planner else state.get("planner_escalation_reason", ""),
        "judge_provider": "mock",
        "judge_model": "mock-judge",
        "judge_history": [*state.get("judge_history", []), history_entry],
        "agent_role_trace": [*state.get("agent_role_trace", []), f"judge:{turn}"],
        "role_model_trace": _append_role_trace(
            state.get("role_model_trace", []),
            role="judge",
            provider="mock",
            model="mock-judge",
        ),
    }
    return annotate_latest_hypothesis(updated, judge_decision=judge_result["decision"])


def judge_node(state: SingleAgentState) -> SingleAgentState:
    binding = build_chat_model_binding(AgentRole.JUDGE)
    settings = binding.settings
    turn = state.get("planner_turn", 1)
    reviewer_decision = state.get("review_decision", "stop")
    role_model_trace = _append_role_trace(
        state.get("role_model_trace", []),
        role="judge",
        provider=settings.provider,
        model=settings.model,
    )
    agent_role_trace = [*state.get("agent_role_trace", []), f"judge:{turn}"]

    if binding.client is None:
        judge_result = {
            "decision": reviewer_decision,
            "override": False,
            "reasoning": f"Judge initialization failed: {binding.initialization_error_message}. Accepting reviewer decision.",
        }
        raw_output = json.dumps(judge_result, ensure_ascii=False)
        token_usage = {}
        invocation_retry_count = 0
        invocation_failed = True
    else:
        raw_output = ""
        judge_result = None
        last_error = ""
        token_usage = {}
        invocation_retry_count = 0
        invocation_failed = False
        max_invocation_attempts = settings.max_attempts + judge_invocation_failure_retries()
        for attempt in range(1, max_invocation_attempts + 1):
            try:
                print(
                    f"[judge] invoking {settings.provider}/{settings.model} "
                    f"attempt={attempt}/{max_invocation_attempts} timeout={settings.timeout_seconds}s"
                )
                response = binding.client.invoke([
                    ("system", JUDGE_SYSTEM_PROMPT),
                    ("human", _judge_prompt(state)),
                ])
                raw_output = response.content if isinstance(response.content, str) else str(response.content)
                token_usage = extract_token_usage(response)
                judge_result, parse_errors = parse_judge_output(raw_output)
                if parse_errors:
                    last_error = "; ".join(parse_errors)
                    judge_result["decision"] = reviewer_decision
                    judge_result["override"] = False
                    judge_result["reasoning"] = (
                        judge_result["reasoning"] + " " + last_error
                    ).strip()
                break
            except Exception as exc:
                last_error = str(exc)
                invocation_retry_count = attempt
                if attempt == max_invocation_attempts:
                    invocation_failed = True
                    judge_result = {
                        "decision": reviewer_decision,
                        "override": False,
                        "reasoning": f"Judge invocation failed after {attempt} attempts: {last_error}. Accepting reviewer decision.",
                    }
                    raw_output = json.dumps(judge_result, ensure_ascii=False)
                    break
                time.sleep(min(settings.backoff_cap_seconds, settings.backoff_base_seconds * attempt))
        assert judge_result is not None

    _section(f"[PHASE 9] JUDGE (TURN {turn})")
    print(raw_output)
    print()
    history_entry = {
        "turn": turn,
        "decision": judge_result["decision"],
        "override": judge_result["override"],
        "reasoning": judge_result["reasoning"],
        "escalate_planner": judge_result.get("escalate_planner", False),
        "escalation_reason": judge_result.get("escalation_reason", ""),
        "token_usage": token_usage,
        "invocation_failed": invocation_failed,
        "invocation_retry_count": invocation_retry_count,
    }
    escalate_planner, escalation_reason = planner_escalation_request_from_judge(judge_result)
    updated = {
        **state,
        "judge_decision": judge_result["decision"],
        "judge_output_raw": raw_output,
        "judge_reasoning": judge_result["reasoning"],
        "judge_override": judge_result["override"],
        "planner_escalation_requested": escalate_planner or state.get("planner_escalation_requested", False),
        "planner_escalation_source": "judge" if escalate_planner else state.get("planner_escalation_source", ""),
        "planner_escalation_reason": escalation_reason if escalate_planner else state.get("planner_escalation_reason", ""),
        "judge_token_usage": token_usage,
        "judge_invocation_failed": invocation_failed,
        "judge_invocation_retry_count": invocation_retry_count,
        "judge_provider": settings.provider,
        "judge_model": settings.model,
        "judge_history": [*state.get("judge_history", []), history_entry],
        "agent_role_trace": agent_role_trace,
        "role_model_trace": role_model_trace,
    }
    return annotate_latest_hypothesis(updated, judge_decision=judge_result["decision"])
