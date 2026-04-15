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


def test_missing_uvicorn_requirements_signal_enters_dependency_scope() -> None:
    observation = {
        **_minimal_observation(),
        "file_snippets": {
            "app/requirements.txt": "fastapi==0.116.1\nPyMySQL==1.1.1\ncryptography",
        },
        "suspicious_patterns": {"app": [], "nginx": ["connect() failed"], "http": ["502 Bad Gateway"]},
        "http_error_evidence": {"healthz": "502 Bad Gateway", "api_items": "502 Bad Gateway"},
        "health_checks": {"healthz": {"status": 502}, "api_items": {"status": 502}},
    }
    result = build_triage_result(observation)
    assert result["suspected_domains"][0]["domain"] == "app_startup_or_dependency_failure"
    assert "app/requirements.txt" in result["candidate_scope"]["files"]


def test_topology_contract_signal_enters_topology_scope() -> None:
    observation = {
        **_minimal_observation(),
        "file_snippets": {
            "app/app.env": "CACHE_HOST=queue\nCACHE_EXPECTED_HOST=cache\nDEGRADED_MODE=false",
        },
        "health_checks": {
            "healthz": {"status": 200},
            "api_items": {
                "status": 200,
                "body": '{"items":[{"id":1,"name":"seed-item","description":"initial record"}]}',
            },
            "topology": {
                "status": 200,
                "body": (
                    '{"status":"degraded","checks":{"dependencies_reachable":true,'
                    '"expected_hosts_ok":false,"expected_groups_ok":true,'
                    '"degraded_mode_ok":true},"dependencies":{"cache":'
                    '{"host":"queue","expected_host":"cache","reachable":true}}}'
                ),
            },
        },
    }
    result = build_triage_result(observation)
    assert result["suspected_domains"][0]["domain"] == "failover_contract_mismatch"
    assert "app/app.env" in result["candidate_scope"]["files"]
    assert "cache" in result["candidate_scope"]["services"]


def test_resolve_internal_scenario_is_evaluator_only() -> None:
    mapping = resolve_internal_scenario(
        requested_scenario="a",
        scenario_definitions={"a": {"name": "A", "success_checks": [], "failure_conditions": []}},
        observation=_minimal_observation(),
    )
    assert mapping["internal_scenario_id"] == "a"
    assert mapping["scenario_source"] == "forced"
