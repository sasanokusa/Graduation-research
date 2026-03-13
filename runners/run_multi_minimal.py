import argparse
import hashlib
import os
import time
from typing import Literal

from langgraph.graph import END, START, StateGraph

from agents.mock_worker import mock_planner_node
from agents.reviewer import mock_reviewer_node, reviewer_node
from agents.sensor import additional_observation_node, sensor_node
from agents.worker import planner_node
from core.prompts import PROMPT_REGISTRY, get_prompt_spec
from core.state import SingleAgentState
from core.verifier import run_postcheck
from runners.run_single import (
    additional_observation_gate,
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
    return _env_int("MULTI_AGENT_MAX_TURNS", 3)


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
    return {
        **state,
        "planner_history": [*state.get("planner_history", []), planner_history_entry],
        "last_turn_success": last_turn_success,
        "multi_agent_stop_reason": stop_reason,
        "final_status": "success" if last_turn_success else "failure",
    }


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


def reviewer_stop_node(state: SingleAgentState) -> SingleAgentState:
    _section("🛑 [MULTI] REVIEWER STOP")
    print(state.get("review_feedback") or "Reviewer requested stop.")
    print()
    return _terminal_failure_cleanup(state, stop_reason="reviewer_stop")


def prepare_replan_node(state: SingleAgentState) -> SingleAgentState:
    next_turn = state.get("planner_turn", 1) + 1
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
    builder.add_node("sensor_node", sensor_node)
    builder.add_node("triage_node", triage_node)
    builder.add_node("additional_observation_node", additional_observation_node)
    builder.add_node("already_healthy_node", already_healthy_node)
    builder.add_node("healthy_end_node", healthy_end_node)
    builder.add_node("planner_node", mock_planner_node if worker_mode == "mock" else planner_node)
    builder.add_node("precheck_node", precheck_node)
    builder.add_node("precheck_failure_node", precheck_failure_node)
    builder.add_node("executor_node", executor_node)
    builder.add_node("postcheck_node", postcheck_node)
    builder.add_node("rollback_node", rollback_node)
    builder.add_node("turn_summary_node", turn_summary_node)
    builder.add_node("reviewer_node", mock_reviewer_node if worker_mode == "mock" else reviewer_node)
    builder.add_node("success_end_node", success_end_node)
    builder.add_node("max_turns_end_node", max_turns_end_node)
    builder.add_node("reviewer_stop_node", reviewer_stop_node)
    builder.add_node("prepare_replan_node", prepare_replan_node)

    builder.add_edge(START, "sensor_node")
    builder.add_edge("sensor_node", "triage_node")
    builder.add_conditional_edges(
        "triage_node",
        additional_observation_gate,
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
    builder.add_conditional_edges(
        "reviewer_node",
        after_review_gate,
        {"retry": "prepare_replan_node", "stop": "reviewer_stop_node"},
    )
    builder.add_edge("reviewer_stop_node", END)
    builder.add_edge("prepare_replan_node", "sensor_node")
    return builder.compile()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the minimal multi-agent recovery loop.")
    parser.add_argument(
        "--scenario",
        choices=["auto", "a", "b", "c", "d", "e", "f", "g", "h", "i", "i2", "k", "l", "m", "n", "o", "p", "q", "r"],
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
    args = parser.parse_args(argv)

    prompt_spec = get_prompt_spec(args.prompt_mode)
    system_prompt_hash = hashlib.sha256(prompt_spec["system_prompt"].encode("utf-8")).hexdigest()[:16]
    app = build_app(args.worker)
    state: SingleAgentState = {
        "execution_mode": "multi_agent_minimal",
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
        "scenario": args.scenario if args.scenario != "auto" else "unknown",
        "scenario_definition": {},
        "internal_scenario_definition": {},
        "observation": {},
        "observed_symptoms": [],
        "stage_progression": [],
        "surfaced_failure_sequence": [],
        "initial_postcheck_result": {},
        "additional_observation_used": False,
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
        "reviewer_provider": "",
        "reviewer_model": "",
        "replan_count": 0,
        "agent_role_trace": ["multi_agent_minimal"],
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
