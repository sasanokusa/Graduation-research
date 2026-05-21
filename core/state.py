from typing import Any, TypedDict


class SingleAgentState(TypedDict):
    execution_mode: str
    requested_scenario: str
    scenario_source: str
    worker_mode: str
    prompt_mode: str
    system_prompt_name: str
    system_prompt_hash: str
    worker_context_mode: str
    worker_context_mode_hash: str
    worker_visible_context: dict[str, Any]
    internal_scenario_id: str
    detected_fault_class: str
    detection_confidence: float
    detection_evidence: list[str]
    suspected_domains: list[dict[str, Any]]
    candidate_scope: dict[str, Any]
    missing_evidence: list[str]
    recommended_next_observations: list[str]
    ambiguity_level: str
    triage_summary: str
    triage_iterations: list[dict[str, Any]]
    incident_blackboard: dict[str, Any]
    scenario: str
    scenario_definition: dict[str, Any]
    internal_scenario_definition: dict[str, Any]
    observation: dict[str, Any]
    observed_symptoms: list[str]
    stage_progression: list[str]
    surfaced_failure_sequence: list[str]
    initial_postcheck_result: dict[str, Any]
    additional_observation_used: bool
    additional_observation_count: int
    additional_observation_history: list[dict[str, Any]]
    planner_input_scope: dict[str, Any]
    planner_error_type: str
    planner_error_stage: str
    planner_retry_count: int
    planner_timeout_seconds: int
    planner_attempts: list[dict[str, Any]]
    planner_transport_failure: bool
    planner_reasoning_failure: bool
    planner_fallback_used: bool
    planner_fallback_reason: str
    planner_fallback_type: str
    planner_escalation_requested: bool
    planner_escalation_source: str
    planner_escalation_reason: str
    planner_escalation_used: bool
    planner_escalation_history: list[dict[str, Any]]
    planner_output_raw: str
    planner_summary: str
    planner_provider: str
    planner_model: str
    normalized_actions: list[dict[str, Any]]
    proposed_actions: list[dict[str, Any]]
    auto_appended_actions: list[dict[str, Any]]
    precheck_input_actions: list[dict[str, Any]]
    verifier_precheck_result: dict[str, Any]
    execution_result: dict[str, Any]
    verifier_postcheck_result: dict[str, Any]
    rollback_result: dict[str, Any]
    rollback_used: bool
    restore_from_base_used: bool
    restore_from_base_blocked: bool
    restore_from_base_block_reason: str
    minimal_patch_used: bool
    planner_turn: int
    planner_history: list[dict[str, Any]]
    reviewer_history: list[dict[str, Any]]
    review_feedback: str
    review_decision: str
    reviewer_output_raw: str
    reviewer_recommended_scope: dict[str, Any]
    reviewer_recommended_next_observations: list[str]
    reviewer_suspected_remaining_domains: list[str]
    reviewer_provider: str
    reviewer_model: str
    reviewer_token_usage: dict[str, Any]
    reviewer_invocation_failed: bool
    reviewer_invocation_retry_count: int
    reviewer_invocation_error: str
    triage_mode: str
    triage_provider: str
    triage_model: str
    triage_llm_fallback: bool
    hypothesis_log: list[dict[str, Any]]
    hypothesis_metrics: dict[str, Any]
    baseline_condition: str
    self_critique_history: list[dict[str, Any]]
    judge_decision: str
    judge_output_raw: str
    judge_reasoning: str
    judge_override: bool
    judge_provider: str
    judge_model: str
    judge_token_usage: dict[str, Any]
    judge_invocation_failed: bool
    judge_invocation_retry_count: int
    judge_history: list[dict[str, Any]]
    replan_count: int
    agent_role_trace: list[str]
    role_model_trace: list[dict[str, str]]
    last_turn_success: bool
    multi_agent_stop_reason: str
    final_status: str
    result_path: str
    start_time: float
