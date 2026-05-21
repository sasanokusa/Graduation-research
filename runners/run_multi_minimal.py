import argparse
import hashlib
import json
import os
import time
from typing import Literal

from langgraph.graph import END, START, StateGraph

from agents.judge import judge_node, mock_judge_node
from agents.mock_worker import mock_planner_node
from agents.reviewer import mock_reviewer_node, reviewer_node
from agents.sensor import additional_observation_node, sensor_node
from agents.worker import planner_node
from core.hypothesis import append_hypothesis_log
from core.escalation import planner_escalation_on_retry_enabled
from core.incident_blackboard import (
    AGENT_ROLES,
    initial_incident_blackboard,
    merge_reviewer_guidance_into_triage,
    record_judge,
    record_execution,
    record_observation,
    record_repair_plan,
    record_postcheck,
    record_precheck,
    record_review,
    record_triage,
    record_turn_summary,
)
from core.prompts import PROMPT_REGISTRY, get_prompt_spec
from core.state import SingleAgentState
from core.verifier import run_postcheck
from runners.run_single import (
    already_healthy_node,
    executor_node,
    postcheck_node,
    precheck_node,
    rollback_node,
    save_result,
    triage_node,
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


def multi_agent_max_turns() -> int:
    return _env_int("MULTI_AGENT_MAX_TURNS", 5)


def multi_agent_max_additional_observations() -> int:
    return _env_int("MULTI_AGENT_MAX_ADDITIONAL_OBSERVATIONS", 3)


def multi_agent_judge_enabled() -> bool:
    value = os.getenv("MULTI_AGENT_JUDGE_MODE", os.getenv("MULTI_AGENT_ENABLE_JUDGE", "enabled")).strip().lower()
    return value not in {"0", "false", "no", "off", "disabled", "none"}


def healthy_end_node(state: SingleAgentState) -> SingleAgentState:
    _section("🏁 [MULTI] HEALTHY")
    print("System is already healthy. Multi-agent loop will not start.")
    print()
    return {
        **state,
        "last_turn_success": True,
        "multi_agent_stop_reason": "already_healthy",
        "final_status": "success",
    }


def _additional_observation_used_this_turn(state: SingleAgentState) -> bool:
    turn = state.get("planner_turn", 1)
    return any(
        entry.get("turn") == turn
        for entry in state.get("additional_observation_history", [])
    )


def multi_additional_observation_gate(state: SingleAgentState) -> Literal["healthy", "observe", "plan"]:
    if state["initial_postcheck_result"].get("ok"):
        return "healthy"
    if (
        state["recommended_next_observations"]
        and state.get("additional_observation_count", 0) < multi_agent_max_additional_observations()
        and not _additional_observation_used_this_turn(state)
    ):
        return "observe"
    return "plan"


def observer_agent_node(state: SingleAgentState) -> SingleAgentState:
    return record_observation(sensor_node(state), source="sensor")


def additional_observer_agent_node(state: SingleAgentState) -> SingleAgentState:
    return record_observation(additional_observation_node(state), source="additional_observation")


def triage_agent_node(state: SingleAgentState) -> SingleAgentState:
    triaged = triage_node(state)
    guided = merge_reviewer_guidance_into_triage(triaged)
    worker_context_mode_hash = hashlib.sha256(
        json.dumps(
            guided.get("worker_visible_context", {}),
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:16]
    guided = {
        **guided,
        "worker_context_mode_hash": worker_context_mode_hash,
    }
    return record_triage(guided)


def precheck_route(state: SingleAgentState) -> Literal["execute", "finalize"]:
    if state["verifier_precheck_result"].get("ok"):
        return "execute"
    return "finalize"


def precheck_failure_node(state: SingleAgentState) -> SingleAgentState:
    postcheck_stub = {
        "ok": False,
        "checks": {},
        "warnings": ["postcheck skipped because precheck failed"],
        "healthz": {},
        "api_items": {},
        "recent_logs": {},
    }
    return {
        **state,
        "execution_result": {
            "ok": False,
            "skipped": True,
            "reason": "precheck_failed",
            "action_results": [],
            "rollback_result": {"ok": True, "restored_files": [], "errors": []},
        },
        "verifier_postcheck_result": postcheck_stub,
        "final_status": "failure",
    }


def turn_summary_node(state: SingleAgentState) -> SingleAgentState:
    turn = state.get("planner_turn", 1)
    precheck_ok = bool(state.get("verifier_precheck_result", {}).get("ok"))
    execution_ok = bool(state.get("execution_result", {}).get("ok"))
    postcheck_ok = bool(state.get("verifier_postcheck_result", {}).get("ok"))
    last_turn_success = precheck_ok and execution_ok and postcheck_ok and state.get("final_status") == "success"
    planner_history_entry = {
        "turn": turn,
        "summary": state.get("planner_summary", ""),
        "proposed_actions": state.get("proposed_actions", []),
        "validated_actions": state.get("verifier_precheck_result", {}).get("validated_actions", []),
        "planner_attempts": state.get("planner_attempts", []),
        "planner_escalation_used": state.get("planner_escalation_used", False),
        "planner_escalation_source": state.get("planner_escalation_source", ""),
        "planner_escalation_reason": state.get("planner_escalation_reason", ""),
        "precheck_ok": precheck_ok,
        "execution_ok": execution_ok,
        "postcheck_ok": postcheck_ok,
        "rollback_used": state.get("rollback_used", False),
    }
    stop_reason = state.get("multi_agent_stop_reason", "")
    if last_turn_success:
        stop_reason = "success"
    elif turn >= multi_agent_max_turns():
        stop_reason = "max_turns_reached"

    _section(f"🧾 [TURN {turn}] SUMMARY")
    print(
        {
            "turn": turn,
            "precheck_ok": precheck_ok,
            "execution_ok": execution_ok,
            "postcheck_ok": postcheck_ok,
            "rollback_used": state.get("rollback_used", False),
            "last_turn_success": last_turn_success,
        }
    )
    print()
    updated_state = {
        **state,
        "planner_history": [*state.get("planner_history", []), planner_history_entry],
        "last_turn_success": last_turn_success,
        "multi_agent_stop_reason": stop_reason,
        "final_status": "success" if last_turn_success else "failure",
    }
    updated_state = append_hypothesis_log(updated_state)
    return record_turn_summary(updated_state)


def after_turn_gate(state: SingleAgentState) -> Literal["success", "review", "max_turns"]:
    if state.get("last_turn_success"):
        return "success"
    if state.get("planner_turn", 1) >= multi_agent_max_turns():
        return "max_turns"
    return "review"


def success_end_node(state: SingleAgentState) -> SingleAgentState:
    return {
        **state,
        "multi_agent_stop_reason": "success",
        "final_status": "success",
    }


def max_turns_end_node(state: SingleAgentState) -> SingleAgentState:
    _section("🛑 [MULTI] MAX TURNS")
    print(f"Reached max planner turns: {multi_agent_max_turns()}")
    print()
    return _terminal_failure_cleanup(state, stop_reason="max_turns_reached")


def after_review_gate(state: SingleAgentState) -> Literal["retry", "stop"]:
    if state.get("review_decision") == "retry" and state.get("planner_turn", 1) < multi_agent_max_turns():
        return "retry"
    return "stop"


def after_judge_gate(state: SingleAgentState) -> Literal["retry", "stop"]:
    if state.get("judge_decision") == "retry" and state.get("planner_turn", 1) < multi_agent_max_turns():
        return "retry"
    return "stop"


def reviewer_stop_node(state: SingleAgentState) -> SingleAgentState:
    _section("🛑 [MULTI] REVIEWER STOP")
    print(state.get("review_feedback") or "Reviewer requested stop.")
    print()
    return _terminal_failure_cleanup(state, stop_reason="reviewer_stop")


def judge_stop_node(state: SingleAgentState) -> SingleAgentState:
    _section("🛑 [MULTI] JUDGE STOP")
    reason = state.get("judge_reasoning") or "Judge requested stop."
    if state.get("judge_override"):
        reason = f"[OVERRIDE] {reason}"
    print(reason)
    print()
    return _terminal_failure_cleanup(state, stop_reason="judge_stop")


def prepare_replan_node(state: SingleAgentState) -> SingleAgentState:
    next_turn = state.get("planner_turn", 1) + 1
    escalation_requested = state.get("planner_escalation_requested", False)
    escalation_source = state.get("planner_escalation_source", "")
    escalation_reason = state.get("planner_escalation_reason", "")
    if planner_escalation_on_retry_enabled() and not escalation_requested:
        escalation_requested = True
        escalation_source = "judge" if state.get("judge_decision") == "retry" else "reviewer"
        escalation_reason = "planner escalation mode is on_retry and the review loop approved another planning turn"
    _section(f"🔁 [REPLAN] NEXT TURN {next_turn}")
    print(state.get("review_feedback") or "Retrying with refreshed observation.")
    print()
    return {
        **state,
        "planner_turn": next_turn,
        "replan_count": state.get("replan_count", 0) + 1,
        "final_status": "running",
        "last_turn_success": False,
        "planner_error_type": "none",
        "planner_error_stage": "none",
        "planner_retry_count": 0,
        "planner_timeout_seconds": 0,
        "planner_attempts": [],
        "planner_transport_failure": False,
        "planner_reasoning_failure": False,
        "planner_fallback_used": False,
        "planner_fallback_reason": "",
        "planner_fallback_type": "",
        "planner_escalation_requested": escalation_requested,
        "planner_escalation_source": escalation_source,
        "planner_escalation_reason": escalation_reason,
        "planner_escalation_used": False,
        "planner_escalation_history": state.get("planner_escalation_history", []),
        "planner_output_raw": "",
        "planner_summary": "",
        "normalized_actions": [],
        "proposed_actions": [],
        "auto_appended_actions": [],
        "precheck_input_actions": [],
        "verifier_precheck_result": {},
        "execution_result": {},
        "verifier_postcheck_result": {},
        "rollback_result": {},
        "rollback_used": False,
        "multi_agent_stop_reason": "",
        "reviewer_invocation_failed": False,
        "reviewer_invocation_retry_count": 0,
        "reviewer_invocation_error": "",
        "judge_decision": "",
        "judge_output_raw": "",
        "judge_reasoning": "",
        "judge_override": False,
        "judge_invocation_failed": False,
        "judge_invocation_retry_count": 0,
    }


def _terminal_failure_cleanup(state: SingleAgentState, *, stop_reason: str) -> SingleAgentState:
    backups = state.get("execution_result", {}).get("backups", {})
    if backups and not state.get("rollback_used", False):
        cleaned = rollback_node(state)
        return {
            **cleaned,
            "multi_agent_stop_reason": stop_reason,
            "final_status": "failure",
            "rollback_result": {
                **cleaned.get("rollback_result", {}),
                "rollback_postcheck_result": cleaned.get("verifier_postcheck_result", {}),
            },
        }
    rollback_postcheck_result = run_postcheck(
        state.get("scenario_definition", {}),
        readiness_wait_used=bool(state.get("execution_result", {}).get("readiness_wait_requested")),
    )
    return {
        **state,
        "multi_agent_stop_reason": stop_reason,
        "final_status": "failure",
        "rollback_postcheck_result": rollback_postcheck_result,
        "rollback_result": {
            **state.get("rollback_result", {}),
            "rollback_postcheck_result": rollback_postcheck_result,
        },
        "verifier_postcheck_result": rollback_postcheck_result,
    }


def build_app(worker_mode: str):
    builder = StateGraph(SingleAgentState)
    planner_impl = mock_planner_node if worker_mode == "mock" else planner_node
    reviewer_impl = mock_reviewer_node if worker_mode == "mock" else reviewer_node
    judge_impl = mock_judge_node if worker_mode == "mock" else judge_node

    def repair_planner_agent_node(state: SingleAgentState) -> SingleAgentState:
        return record_repair_plan(planner_impl(state))

    def safety_precheck_node(state: SingleAgentState) -> SingleAgentState:
        return record_precheck(precheck_node(state))

    def action_executor_node(state: SingleAgentState) -> SingleAgentState:
        return record_execution(executor_node(state))

    def verification_postcheck_node(state: SingleAgentState) -> SingleAgentState:
        return record_postcheck(postcheck_node(state))

    def verification_reviewer_agent_node(state: SingleAgentState) -> SingleAgentState:
        return record_review(reviewer_impl(state))

    def safety_judge_agent_node(state: SingleAgentState) -> SingleAgentState:
        return record_judge(judge_impl(state))

    builder.add_node("sensor_node", observer_agent_node)
    builder.add_node("triage_node", triage_agent_node)
    builder.add_node("additional_observation_node", additional_observer_agent_node)
    builder.add_node("already_healthy_node", already_healthy_node)
    builder.add_node("healthy_end_node", healthy_end_node)
    builder.add_node("planner_node", repair_planner_agent_node)
    builder.add_node("precheck_node", safety_precheck_node)
    builder.add_node("precheck_failure_node", precheck_failure_node)
    builder.add_node("executor_node", action_executor_node)
    builder.add_node("postcheck_node", verification_postcheck_node)
    builder.add_node("rollback_node", rollback_node)
    builder.add_node("turn_summary_node", turn_summary_node)
    builder.add_node("reviewer_node", verification_reviewer_agent_node)
    builder.add_node("judge_node", safety_judge_agent_node)
    builder.add_node("success_end_node", success_end_node)
    builder.add_node("max_turns_end_node", max_turns_end_node)
    builder.add_node("reviewer_stop_node", reviewer_stop_node)
    builder.add_node("judge_stop_node", judge_stop_node)
    builder.add_node("prepare_replan_node", prepare_replan_node)

    builder.add_edge(START, "sensor_node")
    builder.add_edge("sensor_node", "triage_node")
    builder.add_conditional_edges(
        "triage_node",
        multi_additional_observation_gate,
        {"healthy": "already_healthy_node", "observe": "additional_observation_node", "plan": "planner_node"},
    )
    builder.add_edge("additional_observation_node", "triage_node")
    builder.add_edge("already_healthy_node", "healthy_end_node")
    builder.add_edge("healthy_end_node", END)

    builder.add_edge("planner_node", "precheck_node")
    builder.add_conditional_edges(
        "precheck_node",
        precheck_route,
        {"execute": "executor_node", "finalize": "precheck_failure_node"},
    )
    builder.add_edge("precheck_failure_node", "turn_summary_node")
    builder.add_edge("executor_node", "postcheck_node")
    builder.add_edge("postcheck_node", "turn_summary_node")
    builder.add_conditional_edges(
        "turn_summary_node",
        after_turn_gate,
        {"success": "success_end_node", "review": "reviewer_node", "max_turns": "max_turns_end_node"},
    )
    builder.add_edge("success_end_node", END)
    builder.add_edge("max_turns_end_node", END)
    if multi_agent_judge_enabled():
        builder.add_edge("reviewer_node", "judge_node")
        builder.add_conditional_edges(
            "judge_node",
            after_judge_gate,
            {"retry": "prepare_replan_node", "stop": "judge_stop_node"},
        )
    else:
        builder.add_conditional_edges(
            "reviewer_node",
            after_review_gate,
            {"retry": "prepare_replan_node", "stop": "reviewer_stop_node"},
        )
    builder.add_edge("reviewer_stop_node", END)
    builder.add_edge("judge_stop_node", END)
    builder.add_edge("prepare_replan_node", "sensor_node")
    return builder.compile()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the minimal multi-agent recovery loop.")
    parser.add_argument(
        "--scenario",
        choices=["auto", "a", "b", "c", "d", "e", "f", "g", "h", "i", "i2", "k", "l", "m", "n", "o", "p", "q", "r", "s", "t", "u", "v", "w", "x"],
        default="auto",
        help="Internal benchmark scenario for forced-mode debugging, or auto for open-world triage.",
    )
    parser.add_argument(
        "--worker",
        choices=["llm", "mock"],
        default="llm",
        help="Planner/reviewer implementation to use.",
    )
    parser.add_argument(
        "--prompt-mode",
        choices=sorted(PROMPT_REGISTRY.keys()),
        default="blind",
        help="Prompt mode for the planner.",
    )
    parser.add_argument(
        "--triage-mode",
        choices=["rule", "llm"],
        default="rule",
        help="Triage mode: rule-based or LLM-based domain ranking.",
    )
    args = parser.parse_args(argv)

    prompt_spec = get_prompt_spec(args.prompt_mode)
    system_prompt_hash = hashlib.sha256(prompt_spec["system_prompt"].encode("utf-8")).hexdigest()[:16]
    app = build_app(args.worker)
    state: SingleAgentState = {
        "execution_mode": "multi_agent",
        "requested_scenario": args.scenario,
        "scenario_source": "forced" if args.scenario != "auto" else "auto",
        "worker_mode": args.worker,
        "prompt_mode": args.prompt_mode,
        "system_prompt_name": prompt_spec["name"],
        "system_prompt_hash": system_prompt_hash,
        "worker_context_mode": "",
        "worker_context_mode_hash": "",
        "worker_visible_context": {},
        "internal_scenario_id": "",
        "detected_fault_class": "unknown",
        "detection_confidence": 0.0,
        "detection_evidence": [],
        "suspected_domains": [],
        "candidate_scope": {},
        "missing_evidence": [],
        "recommended_next_observations": [],
        "ambiguity_level": "high",
        "triage_summary": "",
        "triage_iterations": [],
        "incident_blackboard": initial_incident_blackboard(),
        "scenario": args.scenario if args.scenario != "auto" else "unknown",
        "scenario_definition": {},
        "internal_scenario_definition": {},
        "observation": {},
        "observed_symptoms": [],
        "stage_progression": [],
        "surfaced_failure_sequence": [],
        "initial_postcheck_result": {},
        "additional_observation_used": False,
        "additional_observation_count": 0,
        "additional_observation_history": [],
        "planner_input_scope": {},
        "planner_error_type": "none",
        "planner_error_stage": "none",
        "planner_retry_count": 0,
        "planner_timeout_seconds": 0,
        "planner_attempts": [],
        "planner_transport_failure": False,
        "planner_reasoning_failure": False,
        "planner_fallback_used": False,
        "planner_fallback_reason": "",
        "planner_fallback_type": "",
        "planner_escalation_requested": False,
        "planner_escalation_source": "",
        "planner_escalation_reason": "",
        "planner_escalation_used": False,
        "planner_escalation_history": [],
        "planner_output_raw": "",
        "planner_summary": "",
        "planner_provider": "",
        "planner_model": "",
        "normalized_actions": [],
        "proposed_actions": [],
        "auto_appended_actions": [],
        "precheck_input_actions": [],
        "verifier_precheck_result": {},
        "execution_result": {},
        "verifier_postcheck_result": {},
        "rollback_result": {},
        "rollback_used": False,
        "restore_from_base_used": False,
        "restore_from_base_blocked": False,
        "restore_from_base_block_reason": "",
        "minimal_patch_used": False,
        "planner_turn": 1,
        "planner_history": [],
        "reviewer_history": [],
        "review_feedback": "",
        "review_decision": "",
        "reviewer_output_raw": "",
        "reviewer_recommended_scope": {},
        "reviewer_recommended_next_observations": [],
        "reviewer_suspected_remaining_domains": [],
        "reviewer_provider": "",
        "reviewer_model": "",
        "reviewer_token_usage": {},
        "reviewer_invocation_failed": False,
        "reviewer_invocation_retry_count": 0,
        "reviewer_invocation_error": "",
        "triage_mode": args.triage_mode,
        "triage_provider": "",
        "triage_model": "",
        "triage_llm_fallback": False,
        "hypothesis_log": [],
        "hypothesis_metrics": {},
        "baseline_condition": (
            "multi_agent_single_planner" if multi_agent_judge_enabled() else "multi_agent_reviewer_only"
        ),
        "self_critique_history": [],
        "judge_decision": "",
        "judge_output_raw": "",
        "judge_reasoning": "",
        "judge_override": False,
        "judge_provider": "",
        "judge_model": "",
        "judge_token_usage": {},
        "judge_invocation_failed": False,
        "judge_invocation_retry_count": 0,
        "judge_history": [],
        "replan_count": 0,
        "agent_role_trace": ["multi_agent", *[role["role"] for role in AGENT_ROLES]],
        "role_model_trace": [],
        "last_turn_success": False,
        "multi_agent_stop_reason": "",
        "final_status": "running",
        "result_path": "",
        "start_time": time.time(),
    }

    final_state = app.invoke(state)
    result_path = save_result(final_state)
    _section("🏁 [MULTI COMPLETE]")
    print(f"final_status: {final_state['final_status']}")
    print(f"multi_agent_stop_reason: {final_state.get('multi_agent_stop_reason', '')}")
    print(f"result_path: {result_path}")
    print()
    return 0 if final_state["final_status"] == "success" else 1
