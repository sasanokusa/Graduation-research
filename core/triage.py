from typing import Any

from core.verifier import run_postcheck


UNKNOWN_SCENARIO_DEFINITION = {
    "name": "UNKNOWN",
    "description": "No supported fault class was confidently detected from the observation payload.",
    "allowed_files": [],
    "allowed_actions": [],
    "success_checks": [],
    "failure_conditions": ["unsupported_fault_class"],
}


def _contains_any(text: str, patterns: list[str]) -> bool:
    return any(pattern in text for pattern in patterns)


def _generic_health_result(observation: dict[str, Any]) -> dict[str, Any]:
    healthz = observation.get("health_checks", {}).get("healthz", {})
    api_items = observation.get("health_checks", {}).get("api_items", {})
    checks = {
        "healthz_200": healthz.get("status") == 200,
        "api_items_200": api_items.get("status") == 200,
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
        "validated_success_checks": list(checks.keys()),
        "success_check_validation_errors": [],
        "compose_ps": observation.get("compose_ps", {}),
        "healthz": healthz,
        "api_items": api_items,
        "recent_logs": observation.get("service_logs", {}),
        "suspicious_hits": observation.get("suspicious_patterns", {}),
        "warnings": [],
        "failure_conditions": [],
        "readiness_wait_used": False,
        "readiness_attempts": 1,
        "first_success_time_seconds": 0.0 if all(checks.values()) else None,
    }


def _scope_from_definition(scenario_definition: dict[str, Any]) -> dict[str, Any]:
    return {
        "editable_files": list(scenario_definition.get("allowed_files", [])),
        "allowed_actions": list(scenario_definition.get("allowed_actions", [])),
    }


def _rank_candidates(observation: dict[str, Any]) -> list[dict[str, Any]]:
    file_snippets = observation.get("file_snippets", {})
    suspicious_patterns = observation.get("suspicious_patterns", {})
    http_error_evidence = observation.get("http_error_evidence", {})

    nginx_snippet = str(file_snippets.get("nginx/nginx.conf", ""))
    app_env_snippet = str(file_snippets.get("app/app.env", ""))
    app_patterns = suspicious_patterns.get("app", [])
    nginx_patterns = suspicious_patterns.get("nginx", [])
    http_evidence_text = "\n".join(str(value) for value in http_error_evidence.values())

    candidates = {
        "a": {"fault_class": "a", "confidence": 0.0, "evidence": []},
        "b": {"fault_class": "b", "confidence": 0.0, "evidence": []},
        "c": {"fault_class": "c", "confidence": 0.0, "evidence": []},
    }

    if "server app:8001;" in nginx_snippet:
        candidates["a"]["confidence"] = max(candidates["a"]["confidence"], 0.95)
        candidates["a"]["evidence"].append("nginx config snippet shows an upstream/backend port mismatch")
    if any(pattern in nginx_patterns for pattern in ["connect() failed", "502 Bad Gateway"]):
        candidates["a"]["confidence"] = max(candidates["a"]["confidence"], 0.8)
        candidates["a"]["evidence"].append("nginx logs indicate upstream connection failure")

    if any(
        pattern in app_patterns
        for pattern in ["ModuleNotFoundError", "No module named", "uvicorn: not found", "Error loading ASGI app"]
    ):
        candidates["b"]["confidence"] = max(candidates["b"]["confidence"], 0.95)
        candidates["b"]["evidence"].append("app logs indicate dependency or startup failure")

    if _contains_any(http_evidence_text, ["Access denied", "database error", "OperationalError"]):
        candidates["c"]["confidence"] = max(candidates["c"]["confidence"], 0.95)
        candidates["c"]["evidence"].append(
            "HTTP error evidence indicates database authentication or query failure"
        )
    if "DB_PASSWORD=" in app_env_snippet and candidates["c"]["confidence"] > 0:
        candidates["c"]["evidence"].append("editable app env snippet exposes the current DB_PASSWORD value")

    ranked = sorted(
        (candidate for candidate in candidates.values() if candidate["confidence"] > 0),
        key=lambda candidate: candidate["confidence"],
        reverse=True,
    )
    if not ranked:
        return [
            {
                "fault_class": "unknown",
                "confidence": 0.2,
                "evidence": ["no supported fault class matched the current observation"],
            }
        ]
    return ranked


def build_triage_result(
    *,
    requested_scenario: str,
    scenario_definitions: dict[str, dict[str, Any]],
    observation: dict[str, Any],
) -> dict[str, Any]:
    if requested_scenario != "auto":
        scenario_definition = scenario_definitions[requested_scenario]
        proposed_scope = _scope_from_definition(scenario_definition)
        evidence = [f"fault class was forced by CLI: {requested_scenario}"]
        initial_postcheck_result = run_postcheck(scenario_definition)
        return {
            "scenario": requested_scenario,
            "scenario_definition": scenario_definition,
            "internal_scenario_id": requested_scenario,
            "scenario_source": "forced",
            "suspected_fault_class": requested_scenario,
            "confidence": 1.0,
            "evidence": evidence,
            "proposed_scope": proposed_scope,
            "alternatives": [],
            "initial_postcheck_result": initial_postcheck_result,
        }

    ranked_candidates = _rank_candidates(observation)
    primary = ranked_candidates[0]
    suspected_fault_class = primary["fault_class"] if primary["confidence"] >= 0.6 else "unknown"
    scenario_definition = scenario_definitions.get(suspected_fault_class, UNKNOWN_SCENARIO_DEFINITION)
    proposed_scope = _scope_from_definition(scenario_definition)
    if suspected_fault_class in scenario_definitions:
        initial_postcheck_result = run_postcheck(scenario_definition)
    else:
        initial_postcheck_result = _generic_health_result(observation)

    return {
        "scenario": suspected_fault_class,
        "scenario_definition": scenario_definition,
        "internal_scenario_id": suspected_fault_class,
        "scenario_source": "auto",
        "suspected_fault_class": suspected_fault_class,
        "confidence": primary["confidence"],
        "evidence": primary["evidence"],
        "proposed_scope": proposed_scope,
        "alternatives": ranked_candidates[1:] if suspected_fault_class != "unknown" else ranked_candidates,
        "initial_postcheck_result": initial_postcheck_result,
    }
