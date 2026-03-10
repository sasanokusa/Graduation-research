import argparse
import json
import time
from datetime import datetime, timezone
from typing import Literal

import yaml
from langgraph.graph import END, START, StateGraph

from agents.mock_worker import mock_worker_node
from agents.sensor import additional_observation_node, sensor_node
from agents.worker import worker_node
from core.executor import execute_plan, rollback_files
from core.policies import RESULTS_DIR, SCENARIO_DEFINITIONS_PATH
from core.prompts import PROMPT_REGISTRY, get_prompt_spec
from core.scenario_context import build_worker_visible_context, get_worker_context_mode_name
from core.state import SingleAgentState
from core.triage import build_triage_result
from core.verifier import run_postcheck, run_precheck


def _section(title: str) -> None:
    divider = "=" * 50
    print(divider)
    print(title)
    print(divider)


def load_scenario_definitions() -> dict[str, dict]:
    definitions = yaml.safe_load(SCENARIO_DEFINITIONS_PATH.read_text())
    return definitions.get("scenarios", {})


def triage_node(state: SingleAgentState) -> SingleAgentState:
    triage = build_triage_result(
        requested_scenario=state["requested_scenario"],
        scenario_definitions=load_scenario_definitions(),
        observation=state["observation"],
    )
    worker_visible_context = build_worker_visible_context(
        triage,
        state["observation"],
        state["prompt_mode"],
    )
    triage_snapshot = {
        "iteration": len(state.get("triage_iterations", [])) + 1,
        "additional_observation_used": state["additional_observation_used"],
        "detected_fault_class": triage["detected_fault_class"],
        "detection_confidence": triage["detection_confidence"],
        "detection_evidence": triage["detection_evidence"],
        "suspected_domains": triage["suspected_domains"],
        "candidate_scope": triage["candidate_scope"],
        "missing_evidence": triage["missing_evidence"],
        "recommended_next_observations": triage["recommended_next_observations"],
        "ambiguity_level": triage["ambiguity_level"],
        "triage_summary": triage["triage_summary"],
    }
    _section("🧭 [PHASE 2] TRIAGE")
    print(
        json.dumps(
            {
                "scenario_source": triage["scenario_source"],
                "suspected_domains": triage["suspected_domains"],
                "candidate_scope": triage["candidate_scope"],
                "missing_evidence": triage["missing_evidence"],
                "recommended_next_observations": triage["recommended_next_observations"],
                "ambiguity_level": triage["ambiguity_level"],
                "triage_summary": triage["triage_summary"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print()
    return {
        **state,
        "scenario": triage["scenario"],
        "scenario_definition": triage["scenario_definition"],
        "internal_scenario_id": triage["internal_scenario_id"],
        "detected_fault_class": triage["detected_fault_class"],
        "detection_confidence": triage["detection_confidence"],
        "detection_evidence": triage["detection_evidence"],
        "suspected_domains": triage["suspected_domains"],
        "candidate_scope": triage["candidate_scope"],
        "missing_evidence": triage["missing_evidence"],
        "recommended_next_observations": triage["recommended_next_observations"],
        "ambiguity_level": triage["ambiguity_level"],
        "triage_summary": triage["triage_summary"],
        "triage_iterations": [*state.get("triage_iterations", []), triage_snapshot],
        "scenario_source": triage["scenario_source"],
        "planner_input_scope": triage["candidate_scope"],
        "initial_postcheck_result": triage["initial_postcheck_result"],
        "worker_context_mode": get_worker_context_mode_name(state["prompt_mode"]),
        "worker_visible_context": worker_visible_context,
    }


def additional_observation_gate(state: SingleAgentState) -> Literal["healthy", "observe", "plan"]:
    if state["initial_postcheck_result"].get("ok"):
        return "healthy"
    if state["recommended_next_observations"] and not state["additional_observation_used"]:
        return "observe"
    return "plan"


def already_healthy_node(state: SingleAgentState) -> SingleAgentState:
    _section("✅ [PHASE 3] SKIP WORKER")
    print("Generic service-continuity checks are already satisfied. Skipping planning and execution.")
    print()
    return {
        **state,
        "planner_error_type": "none",
        "planner_retry_count": 0,
        "planner_timeout_seconds": 0,
        "planner_output_raw": '{"summary":"service continuity already restored; no recovery action required","actions":[]}',
        "planner_summary": "service continuity already restored; no recovery action required",
        "verifier_postcheck_result": state["initial_postcheck_result"],
        "final_status": "success",
    }


def precheck_node(state: SingleAgentState) -> SingleAgentState:
    plan = {
        "summary": state["planner_summary"],
        "actions": state["normalized_actions"],
    }
    precheck = run_precheck(
        plan,
        state["scenario_definition"],
        state["observation"],
        scope_policy=state["candidate_scope"],
        planner_error_type=state["planner_error_type"],
    )
    planner_errors = state["verifier_precheck_result"].get("planner_errors", [])
    if planner_errors:
        precheck["ok"] = False
        precheck["worker_normalization_errors"] = planner_errors
    else:
        precheck["worker_normalization_errors"] = []
    _section("🛡️ [PHASE 4] PRECHECK")
    print(json.dumps(precheck, ensure_ascii=False, indent=2))
    print()

    if not precheck["ok"]:
        return {
            **state,
            "verifier_precheck_result": precheck,
            "auto_appended_actions": precheck.get("auto_appended_actions", []),
            "precheck_input_actions": precheck.get("precheck_input_actions", []),
            "final_status": "failure",
        }

    return {
        **state,
        "verifier_precheck_result": precheck,
        "auto_appended_actions": precheck.get("auto_appended_actions", []),
        "precheck_input_actions": precheck.get("precheck_input_actions", []),
    }


def should_execute(state: SingleAgentState) -> Literal["execute", "end"]:
    if state["verifier_precheck_result"].get("ok"):
        return "execute"
    return "end"


def executor_node(state: SingleAgentState) -> SingleAgentState:
    timestamp_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    execution_result = execute_plan(
        {"summary": state["planner_summary"], "actions": state["normalized_actions"]},
        run_id=f"{timestamp_id}_{state['scenario']}",
    )
    _section("⚙️ [PHASE 5] EXECUTOR")
    print(json.dumps(execution_result, ensure_ascii=False, indent=2))
    print()

    final_status = "running"
    if not execution_result["ok"]:
        final_status = "failure"

    return {
        **state,
        "execution_result": execution_result,
        "rollback_result": execution_result.get("rollback_result", state["rollback_result"]),
        "rollback_used": bool(execution_result.get("rollback_used")),
        "final_status": final_status,
    }


def postcheck_node(state: SingleAgentState) -> SingleAgentState:
    postcheck = run_postcheck(
        state["scenario_definition"],
        readiness_wait_used=bool(state["execution_result"].get("readiness_wait_requested")),
    )
    _section("🔎 [PHASE 6] POSTCHECK")
    print(json.dumps(postcheck, ensure_ascii=False, indent=2))
    print()

    final_status = state["final_status"]
    if state["execution_result"].get("ok") and postcheck["ok"]:
        final_status = "success"
    elif final_status != "failure":
        final_status = "failure"

    return {
        **state,
        "verifier_postcheck_result": postcheck,
        "final_status": final_status,
    }


def should_rollback(state: SingleAgentState) -> Literal["rollback", "end"]:
    if state["final_status"] == "failure" and state["execution_result"].get("backups") and not state["rollback_used"]:
        return "rollback"
    return "end"


def rollback_node(state: SingleAgentState) -> SingleAgentState:
    rollback_result = rollback_files(state["execution_result"].get("backups", {}))
    _section("↩️ [PHASE 7] ROLLBACK")
    print(json.dumps(rollback_result, ensure_ascii=False, indent=2))
    print()
    return {
        **state,
        "rollback_result": rollback_result,
        "rollback_used": True,
    }


def save_result(state: SingleAgentState) -> str:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    result_path = RESULTS_DIR / f"{timestamp}_{state['scenario']}.json"
    elapsed_seconds = round(time.time() - state["start_time"], 3)
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "scenario": state["scenario"],
        "requested_scenario": state["requested_scenario"],
        "scenario_source": state["scenario_source"],
        "internal_scenario_id": state["internal_scenario_id"],
        "internal_scenario_role": "evaluator_only",
        "detected_fault_class": state["detected_fault_class"],
        "detection_confidence": state["detection_confidence"],
        "detection_evidence": state["detection_evidence"],
        "triage_summary": state["triage_summary"],
        "triage_iterations": state["triage_iterations"],
        "suspected_domains": state["suspected_domains"],
        "candidate_scope": state["candidate_scope"],
        "missing_evidence": state["missing_evidence"],
        "recommended_next_observations": state["recommended_next_observations"],
        "ambiguity_level": state["ambiguity_level"],
        "additional_observation_used": state["additional_observation_used"],
        "planner_input_scope": state["planner_input_scope"],
        "worker_mode": state["worker_mode"],
        "prompt_mode": state["prompt_mode"],
        "system_prompt_name": state["system_prompt_name"],
        "planner_error_type": state["planner_error_type"],
        "planner_error_stage": state["planner_error_stage"],
        "planner_retry_count": state["planner_retry_count"],
        "planner_timeout_seconds": state["planner_timeout_seconds"],
        "planner_attempts": state["planner_attempts"],
        "planner_transport_failure": state["planner_transport_failure"],
        "planner_reasoning_failure": state["planner_reasoning_failure"],
        "planner_fallback_used": state["planner_fallback_used"],
        "planner_fallback_reason": state["planner_fallback_reason"],
        "planner_fallback_type": state["planner_fallback_type"],
        "worker_context_mode": state["worker_context_mode"],
        "worker_visible_context": state["worker_visible_context"],
        "worker_visible_file_snippets": state["worker_visible_context"].get("observation", {}).get(
            "file_snippets", {}
        ),
        "worker_visible_log_excerpts": state["worker_visible_context"].get("observation", {}).get(
            "relevant_log_excerpts", {}
        ),
        "worker_visible_http_error_evidence": state["worker_visible_context"]
        .get("observation", {})
        .get("http_error_evidence", {}),
        "current_state_evidence": state["observation"].get("current_state_evidence", []),
        "historical_evidence": state["observation"].get("historical_evidence", []),
        "triage_before_additional_observation": state["triage_iterations"][0] if state["triage_iterations"] else {},
        "triage_after_additional_observation": (
            state["triage_iterations"][-1]
            if state["additional_observation_used"] and state["triage_iterations"]
            else {}
        ),
        "observed_symptoms": state["observed_symptoms"],
        "observation_additional": state["observation"].get("additional_observation", {}),
        "initial_postcheck_result": state["initial_postcheck_result"],
        "worker_raw_output": state["planner_output_raw"],
        "normalized_actions": state["normalized_actions"],
        "auto_appended_actions": state["auto_appended_actions"],
        "precheck_input_actions": state["precheck_input_actions"],
        "validated_actions": state["verifier_precheck_result"].get("validated_actions", []),
        "validated_success_checks": state["verifier_precheck_result"].get("validated_success_checks", []),
        "action_validation_errors": state["verifier_precheck_result"].get("action_validation_errors", []),
        "scope_validation_errors": state["verifier_precheck_result"].get("scope_validation_errors", []),
        "success_check_validation_errors": state["verifier_precheck_result"].get(
            "success_check_validation_errors", []
        ),
        "validated_scope": state["verifier_precheck_result"].get("validated_scope", {}),
        "worker_normalization_errors": state["verifier_precheck_result"].get(
            "worker_normalization_errors", []
        ),
        "proposed_actions": state["normalized_actions"],
        "action_results": state["execution_result"].get("action_results", []),
        "readiness_wait_used": state["verifier_postcheck_result"].get("readiness_wait_used", False),
        "readiness_attempts": state["verifier_postcheck_result"].get("readiness_attempts", 0),
        "first_success_time_seconds": state["verifier_postcheck_result"].get(
            "first_success_time_seconds"
        ),
        "verifier_precheck_result": state["verifier_precheck_result"],
        "execution_result": state["execution_result"],
        "verifier_postcheck_result": state["verifier_postcheck_result"],
        "rollback_used": state["rollback_used"],
        "rollback_result": state["rollback_result"],
        "final_status": state["final_status"],
        "elapsed_seconds": elapsed_seconds,
        "planner_summary": state["planner_summary"],
        "planner_output_raw": state["planner_output_raw"],
    }
    result_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    return str(result_path)


def build_app(worker_mode: str):
    builder = StateGraph(SingleAgentState)
    builder.add_node("sensor_node", sensor_node)
    builder.add_node("triage_node", triage_node)
    builder.add_node("additional_observation_node", additional_observation_node)
    builder.add_node("already_healthy_node", already_healthy_node)
    builder.add_node(
        "worker_node",
        mock_worker_node if worker_mode == "mock" else worker_node,
    )
    builder.add_node("precheck_node", precheck_node)
    builder.add_node("executor_node", executor_node)
    builder.add_node("postcheck_node", postcheck_node)
    builder.add_node("rollback_node", rollback_node)
    builder.add_edge(START, "sensor_node")
    builder.add_edge("sensor_node", "triage_node")
    builder.add_conditional_edges(
        "triage_node",
        additional_observation_gate,
        {"healthy": "already_healthy_node", "observe": "additional_observation_node", "plan": "worker_node"},
    )
    builder.add_edge("additional_observation_node", "triage_node")
    builder.add_edge("already_healthy_node", END)
    builder.add_edge("worker_node", "precheck_node")
    builder.add_conditional_edges(
        "precheck_node",
        should_execute,
        {"execute": "executor_node", "end": END},
    )
    builder.add_edge("executor_node", "postcheck_node")
    builder.add_conditional_edges(
        "postcheck_node",
        should_rollback,
        {"rollback": "rollback_node", "end": END},
    )
    builder.add_edge("rollback_node", END)
    return builder.compile()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the safe single-agent recovery baseline.")
    parser.add_argument(
        "--scenario",
        choices=["auto", "a", "b", "c", "d", "e", "f", "g", "h", "i", "k", "l"],
        default="auto",
        help="Internal benchmark scenario for forced-mode debugging, or auto for open-world triage.",
    )
    parser.add_argument(
        "--worker",
        choices=["llm", "mock"],
        default="llm",
        help="Worker implementation to use.",
    )
    parser.add_argument(
        "--prompt-mode",
        choices=sorted(PROMPT_REGISTRY.keys()),
        default="blind",
        help="System prompt mode for the LLM worker.",
    )
    args = parser.parse_args(argv)

    prompt_spec = get_prompt_spec(args.prompt_mode)
    app = build_app(args.worker)
    state: SingleAgentState = {
        "requested_scenario": args.scenario,
        "scenario_source": "forced" if args.scenario != "auto" else "auto",
        "worker_mode": args.worker,
        "prompt_mode": args.prompt_mode,
        "system_prompt_name": prompt_spec["name"],
        "worker_context_mode": "",
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
        "observation": {},
        "observed_symptoms": [],
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
        "normalized_actions": [],
        "proposed_actions": [],
        "auto_appended_actions": [],
        "precheck_input_actions": [],
        "verifier_precheck_result": {},
        "execution_result": {},
        "verifier_postcheck_result": {},
        "rollback_result": {},
        "rollback_used": False,
        "final_status": "running",
        "result_path": "",
        "start_time": time.time(),
    }

    final_state = app.invoke(state)
    result_path = save_result(final_state)
    _section("🏁 [COMPLETE]")
    print(f"final_status: {final_state['final_status']}")
    print(f"result_path: {result_path}")
    print()
    return 0 if final_state["final_status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
