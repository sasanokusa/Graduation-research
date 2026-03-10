from typing import Any, TypedDict


class SingleAgentState(TypedDict):
    requested_scenario: str
    scenario_source: str
    worker_mode: str
    prompt_mode: str
    system_prompt_name: str
    worker_context_mode: str
    worker_visible_context: dict[str, Any]
    internal_scenario_id: str
    detected_fault_class: str
    detected_scenario: str
    detection_confidence: float
    detection_evidence: list[str]
    triage_policy: dict[str, Any]
    proposed_scope: dict[str, Any]
    alternative_candidates: list[dict[str, Any]]
    scenario: str
    scenario_definition: dict[str, Any]
    observation: dict[str, Any]
    observed_symptoms: list[str]
    initial_postcheck_result: dict[str, Any]
    planner_output_raw: str
    planner_summary: str
    normalized_actions: list[dict[str, Any]]
    proposed_actions: list[dict[str, Any]]
    auto_appended_actions: list[dict[str, Any]]
    precheck_input_actions: list[dict[str, Any]]
    verifier_precheck_result: dict[str, Any]
    execution_result: dict[str, Any]
    verifier_postcheck_result: dict[str, Any]
    rollback_result: dict[str, Any]
    rollback_used: bool
    final_status: str
    result_path: str
    start_time: float
