from __future__ import annotations

import argparse
import hashlib
import time
from typing import Literal

from langgraph.graph import END, START, StateGraph

from agents.mock_worker import mock_planner_node
from agents.self_critic import mock_self_critique_node, self_critique_node
from agents.sensor import additional_observation_node, sensor_node
from agents.worker import worker_node
from core.incident_blackboard import (
    AGENT_ROLES,
    initial_incident_blackboard,
    merge_reviewer_guidance_into_triage,
    record_execution,
    record_observation,
    record_postcheck,
    record_precheck,
    record_repair_plan,
    record_triage,
)
from core.prompts import PROMPT_REGISTRY, get_prompt_spec
from core.state import SingleAgentState
from runners.run_multi_minimal import (
    after_turn_gate,
    healthy_end_node,
    max_turns_end_node,
    multi_additional_observation_gate,
    multi_agent_max_turns,
    prepare_replan_node,
    precheck_failure_node,
    precheck_route,
    turn_summary_node,
)
from runners.run_single import executor_node, postcheck_node, precheck_node, save_result, triage_node


def _section(title: str) -> None:
    divider = "=" * 50
    print(divider)
    print(title)
    print(divider)


def self_critique_gate(state: SingleAgentState) -> Literal["retry", "stop"]:
    if state.get("review_decision") == "retry" and state.get("planner_turn", 1) < multi_agent_max_turns():
        return "retry"
    return "stop"


def self_critique_stop_node(state: SingleAgentState) -> SingleAgentState:
    _section("[SELF-CRITIQUE] STOP")
    print(state.get("review_feedback") or "Self-critique requested stop.")
    print()
    return {
        **state,
        "multi_agent_stop_reason": "self_critique_stop",
        "final_status": "failure",
    }


def observer_node(state: SingleAgentState) -> SingleAgentState:
    return record_observation(sensor_node(state), source="sensor")


def additional_observer_node(state: SingleAgentState) -> SingleAgentState:
    return record_observation(additional_observation_node(state), source="additional_observation")


def triage_with_memory_node(state: SingleAgentState) -> SingleAgentState:
    return record_triage(merge_reviewer_guidance_into_triage(triage_node(state)))


def build_app(worker_mode: str):
    builder = StateGraph(SingleAgentState)
    planner_impl = mock_planner_node if worker_mode == "mock" else worker_node
    critic_impl = mock_self_critique_node if worker_mode == "mock" else self_critique_node

    builder.add_node("sensor_node", observer_node)
    builder.add_node("triage_node", triage_with_memory_node)
    builder.add_node("additional_observation_node", additional_observer_node)
    builder.add_node("already_healthy_node", healthy_end_node)
    builder.add_node("planner_node", lambda state: record_repair_plan(planner_impl(state)))
    builder.add_node("precheck_node", lambda state: record_precheck(precheck_node(state)))
    builder.add_node("precheck_failure_node", precheck_failure_node)
    builder.add_node("executor_node", lambda state: record_execution(executor_node(state)))
    builder.add_node("postcheck_node", lambda state: record_postcheck(postcheck_node(state)))
    builder.add_node("turn_summary_node", turn_summary_node)
    builder.add_node("self_critique_node", critic_impl)
    builder.add_node("prepare_replan_node", prepare_replan_node)
    builder.add_node("self_critique_stop_node", self_critique_stop_node)
    builder.add_node("max_turns_end_node", max_turns_end_node)

    builder.add_edge(START, "sensor_node")
    builder.add_edge("sensor_node", "triage_node")
    builder.add_conditional_edges(
        "triage_node",
        multi_additional_observation_gate,
        {"healthy": "already_healthy_node", "observe": "additional_observation_node", "plan": "planner_node"},
    )
    builder.add_edge("additional_observation_node", "triage_node")
    builder.add_edge("already_healthy_node", END)
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
        {"success": END, "review": "self_critique_node", "max_turns": "max_turns_end_node"},
    )
    builder.add_conditional_edges(
        "self_critique_node",
        self_critique_gate,
        {"retry": "prepare_replan_node", "stop": "self_critique_stop_node"},
    )
    builder.add_edge("prepare_replan_node", "sensor_node")
    builder.add_edge("self_critique_stop_node", END)
    builder.add_edge("max_turns_end_node", END)
    return builder.compile()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the iterative single-agent self-critique baseline.")
    parser.add_argument(
        "--scenario",
        choices=["auto", "a", "b", "c", "d", "e", "f", "g", "h", "i", "i2", "k", "l", "m", "n", "o", "p", "q", "r", "s", "t", "u", "v", "w", "x"],
        default="auto",
        help="Internal benchmark scenario for forced-mode debugging, or auto for open-world triage.",
    )
    parser.add_argument("--worker", choices=["llm", "mock"], default="llm")
    parser.add_argument("--prompt-mode", choices=sorted(PROMPT_REGISTRY.keys()), default="blind")
    parser.add_argument("--triage-mode", choices=["rule", "llm"], default="rule")
    args = parser.parse_args(argv)

    prompt_spec = get_prompt_spec(args.prompt_mode)
    system_prompt_hash = hashlib.sha256(prompt_spec["system_prompt"].encode("utf-8")).hexdigest()[:16]
    app = build_app(args.worker)
    state: SingleAgentState = {
        "execution_mode": "single_agent_self_critique",
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
        "baseline_condition": "single_agent_iterative_self_critique",
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
        "agent_role_trace": ["single_agent_self_critique", *[role["role"] for role in AGENT_ROLES[:3]]],
        "role_model_trace": [],
        "last_turn_success": False,
        "multi_agent_stop_reason": "",
        "final_status": "running",
        "result_path": "",
        "start_time": time.time(),
    }

    final_state = app.invoke(state)
    result_path = save_result(final_state)
    _section("[SELF-CRITIQUE COMPLETE]")
    print(f"final_status: {final_state['final_status']}")
    print(f"stop_reason: {final_state.get('multi_agent_stop_reason', '')}")
    print(f"result_path: {result_path}")
    print()
    return 0 if final_state["final_status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
