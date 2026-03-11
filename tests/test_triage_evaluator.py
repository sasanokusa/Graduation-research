from core.evaluator_mapping import resolve_internal_scenario
from core.triage import build_triage_result


def _minimal_observation() -> dict:
    return {
        "file_snippets": {},
        "suspicious_patterns": {"app": [], "nginx": [], "http": []},
        "http_error_evidence": {},
        "health_checks": {"healthz": {"status": 200}, "api_items": {"status": 200}},
        "service_logs": {"app": "", "nginx": "", "db": ""},
        "relevant_log_excerpts": {},
        "current_state_evidence": [],
        "historical_evidence": [],
    }


def test_build_triage_result_is_open_world_only() -> None:
    result = build_triage_result(_minimal_observation())
    assert "internal_scenario_id" not in result
    assert "scenario" not in result
    assert "suspected_domains" in result
    assert "candidate_scope" in result


def test_resolve_internal_scenario_is_evaluator_only() -> None:
    mapping = resolve_internal_scenario(
        requested_scenario="a",
        scenario_definitions={"a": {"name": "A", "success_checks": [], "failure_conditions": []}},
        observation=_minimal_observation(),
    )
    assert mapping["internal_scenario_id"] == "a"
    assert mapping["scenario_source"] == "forced"
