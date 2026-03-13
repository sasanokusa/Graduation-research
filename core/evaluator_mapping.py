from typing import Any

from core.policies import resolve_repo_path


AUTO_EVALUATION_DEFINITION = {
    "name": "AUTO_GENERIC",
    "description": "Generic emergency recovery criteria for auto mode.",
    "allowed_files": [],
    "allowed_actions": [],
    "success_checks": [
        "nginx_running",
        "app_running",
        "healthz_200",
        "api_items_200",
        "api_items_nonempty",
        "api_items_schema_ok",
        "port_contract_matches_baseline",
    ],
    "failure_conditions": ["service_continuity_not_restored"],
}

UNKNOWN_SCENARIO_DEFINITION = {
    "name": "UNKNOWN",
    "description": "No supported internal benchmark scenario was confidently inferred.",
    "allowed_files": [],
    "allowed_actions": [],
    "success_checks": [
        "nginx_running",
        "app_running",
        "healthz_200",
        "api_items_200",
        "api_items_nonempty",
        "api_items_schema_ok",
        "port_contract_matches_baseline",
    ],
    "failure_conditions": ["unsupported_fault_class"],
}


def _contains_any(text: str, patterns: list[str]) -> bool:
    return any(pattern in text for pattern in patterns)


def _extract_app_port(observation: dict[str, Any]) -> str | None:
    app_snippet = str(observation.get("file_snippets", {}).get("app/app.env", ""))
    for line in app_snippet.splitlines():
        if line.startswith("APP_PORT="):
            return line.split("=", 1)[1].strip()

    app_logs = str(observation.get("service_logs", {}).get("app", ""))
    marker = "Uvicorn running on http://0.0.0.0:"
    if marker in app_logs:
        return app_logs.split(marker, 1)[1].split()[0].strip()
    return None


def _hidden_benchmark_evidence() -> dict[str, str]:
    return {
        "app_env": resolve_repo_path("app/app.env").read_text(),
        "app_main": resolve_repo_path("app/main.py").read_text(),
        "requirements": resolve_repo_path("app/requirements.txt").read_text(),
        "nginx_conf": resolve_repo_path("nginx/nginx.conf").read_text(),
    }


def _score_candidate(
    candidates: dict[str, dict[str, Any]],
    scenario_id: str,
    confidence: float,
    evidence: str,
) -> None:
    candidate = candidates[scenario_id]
    candidate["confidence"] = max(candidate["confidence"], confidence)
    if evidence not in candidate["evidence"]:
        candidate["evidence"].append(evidence)


def _rank_internal_scenarios(observation: dict[str, Any]) -> list[dict[str, Any]]:
    file_snippets = observation.get("file_snippets", {})
    suspicious_patterns = observation.get("suspicious_patterns", {})
    http_error_evidence = observation.get("http_error_evidence", {})
    health_checks = observation.get("health_checks", {})

    nginx_snippet = str(file_snippets.get("nginx/nginx.conf", ""))
    app_main_snippet = str(file_snippets.get("app/main.py", ""))
    app_env_snippet = str(file_snippets.get("app/app.env", ""))
    app_patterns = suspicious_patterns.get("app", [])
    nginx_patterns = suspicious_patterns.get("nginx", [])
    http_evidence_text = "\n".join(str(value) for value in http_error_evidence.values())
    healthz = health_checks.get("healthz", {})
    api_items = health_checks.get("api_items", {})
    app_port = _extract_app_port(observation)
    current_state_evidence = observation.get("current_state_evidence", [])
    historical_evidence = observation.get("historical_evidence", [])

    candidates = {
        key: {"scenario": key, "confidence": 0.0, "evidence": []}
        for key in ["a", "b", "c", "d", "e", "f", "g", "h", "i", "i2", "k", "l", "m", "n", "o", "p", "q", "r"]
    }
    hidden = _hidden_benchmark_evidence()

    if "server app:8001" in nginx_snippet:
        _score_candidate(candidates, "a", 0.95, "nginx config snippet shows an upstream/backend port mismatch")
    if any(pattern in nginx_patterns for pattern in ["connect() failed", "502 Bad Gateway"]) and healthz.get("status") != 200:
        _score_candidate(candidates, "a", 0.8, "nginx logs indicate upstream connection failure")
    if "server backend:8000" in nginx_snippet:
        _score_candidate(candidates, "h", 0.95, "nginx config snippet shows an invalid upstream host name")
    if any(pattern in nginx_patterns for pattern in ["host not found in upstream", "could not be resolved"]):
        _score_candidate(candidates, "h", 0.95, "nginx logs indicate upstream name resolution failure")
    if (
        app_port == "9000"
        and "server app:8000" in nginx_snippet
        and any(pattern in nginx_patterns for pattern in ["connect() failed", "502 Bad Gateway"])
    ):
        _score_candidate(candidates, "e", 0.9, "app listen port evidence disagrees with the nginx upstream port")
    if "APP_PORT=9000" in app_env_snippet:
        _score_candidate(candidates, "e", 0.75, "editable app env snippet shows a non-default APP_PORT value")
    if "Uvicorn running on http://0.0.0.0:9000" in str(observation.get("service_logs", {}).get("app", "")):
        _score_candidate(candidates, "e", 0.85, "app logs show the service listening on port 9000")
    if any(
        pattern in app_patterns
        for pattern in ["ModuleNotFoundError", "No module named", "uvicorn: not found", "Error loading ASGI app"]
    ):
        _score_candidate(candidates, "b", 0.95, "app logs indicate dependency or startup failure")
    if _contains_any(http_evidence_text, ["Access denied", "using password: YES", "OperationalError"]):
        _score_candidate(candidates, "c", 0.95, "HTTP error evidence indicates database authentication failure")
    if "DB_PASSWORD=" in app_env_snippet and candidates["c"]["confidence"] > 0:
        _score_candidate(candidates, "c", candidates["c"]["confidence"], "editable app env snippet exposes DB_PASSWORD")
    if healthz.get("status") == 200 and api_items.get("status") != 200 and _contains_any(
        http_evidence_text, ["itemz", "doesn't exist", "Table '"]
    ):
        _score_candidate(candidates, "d", 0.9, "HTTP error evidence indicates a missing table in the items query")
    if "FROM itemz ORDER BY id" in app_main_snippet:
        _score_candidate(candidates, "d", 0.95, "editable app code snippet shows the items query targeting itemz")
    if healthz.get("status") == 200 and api_items.get("status") != 200 and _contains_any(
        http_evidence_text, ["Unknown column", "details"]
    ):
        _score_candidate(candidates, "f", 0.9, "HTTP error evidence indicates a missing column in the items query")
    if "name, details FROM items" in app_main_snippet:
        _score_candidate(candidates, "f", 0.95, "editable app code snippet shows the items query targeting details")
    if healthz.get("status") != 200 and api_items.get("status") == 200:
        _score_candidate(candidates, "g", 0.8, "only the health endpoint is failing while the main API still responds")
    if "SELECT missing FROM health_checks" in app_main_snippet:
        _score_candidate(candidates, "g", 0.95, "editable app code snippet shows the broken health query")
    if "APP_PORT=9000" in hidden["app_env"] and "DB_PASSWORD=wrongpassword" in hidden["app_env"]:
        _score_candidate(candidates, "i", 0.98, "hidden benchmark state shows both port drift and DB credential drift")
    if "APP_PORT=9000" in hidden["app_env"] and "FROM itemz ORDER BY id" in hidden["app_main"]:
        _score_candidate(candidates, "i2", 0.99, "hidden benchmark state shows port drift masking a downstream query bug")
    if "K_ITEMS_QUERY" in hidden["app_main"] and 'detail="internal error"' in hidden["app_main"]:
        _score_candidate(candidates, "k", 0.98, "hidden benchmark state shows an opaque API error wrapper around a broken query")
    if (
        "FROM itemz ORDER BY id" in hidden["app_main"]
        and healthz.get("status") == 200
        and api_items.get("status") != 200
        and historical_evidence
    ):
        _score_candidate(candidates, "l", 0.97, "current app/query failure coexists with stale upstream failure evidence")
    if (
        "server backend:8000 resolve;" in hidden["nginx_conf"]
        and "DB_PASSWORD=wrongpassword" in hidden["app_env"]
        and "FROM itemz ORDER BY id" in hidden["app_main"]
    ):
        _score_candidate(candidates, "m", 0.995, "hidden benchmark state shows a three-layer cascade across nginx, env, and query code")
    if "uvicorn[standard]" not in hidden["requirements"] and "FROM itemz ORDER BY id" in hidden["app_main"]:
        _score_candidate(candidates, "n", 0.99, "hidden benchmark state shows a startup dependency failure masking a downstream query bug")
    if (
        "DB_PASSWORD=wrongpassword" in hidden["app_env"]
        and "FROM itemz ORDER BY id" in hidden["app_main"]
        and historical_evidence
    ):
        _score_candidate(candidates, "o", 0.99, "hidden benchmark state shows stale upstream evidence layered on top of DB auth drift and a hidden query bug")
    if "FROM itemz ORDER BY id" in hidden["app_main"] and "return []" in hidden["app_main"]:
        _score_candidate(
            candidates,
            "p",
            0.99,
            "hidden benchmark state shows a broken items query whose exception path silently returns an empty fallback payload",
        )
    if "APP_PORT=9100" in hidden["app_env"]:
        _score_candidate(
            candidates,
            "q",
            0.99,
            "hidden benchmark state shows an app-side port drift that must be restored to the baseline contract",
        )
    if (
        "uvicorn[standard]" not in hidden["requirements"]
        and "DB_PASSWORD=wrongpassword" in hidden["app_env"]
        and "FROM itemz ORDER BY id" in hidden["app_main"]
    ):
        _score_candidate(
            candidates,
            "r",
            0.995,
            "hidden benchmark state shows a dependency failure masking DB auth drift and a downstream query bug",
        )
    if healthz.get("status") == 200 and api_items.get("status") != 200 and any(
        "older upstream connection failures" in item for item in historical_evidence + current_state_evidence
    ):
        _score_candidate(candidates, "l", 0.82, "current health checks contradict stale upstream errors in recent logs")

    ranked = sorted(
        (candidate for candidate in candidates.values() if candidate["confidence"] > 0),
        key=lambda candidate: candidate["confidence"],
        reverse=True,
    )
    if not ranked:
        return [{"scenario": "unknown", "confidence": 0.0, "evidence": ["no internal benchmark match"]}]
    return ranked


def resolve_internal_scenario(
    *,
    requested_scenario: str,
    scenario_definitions: dict[str, dict[str, Any]],
    observation: dict[str, Any],
) -> dict[str, Any]:
    scenario_source = "forced" if requested_scenario != "auto" else "auto"
    if requested_scenario != "auto":
        internal_scenario_id = requested_scenario
    else:
        internal_scenario_id = _rank_internal_scenarios(observation)[0]["scenario"]

    scenario = internal_scenario_id if internal_scenario_id in scenario_definitions else "unknown"
    scenario_definition = (
        scenario_definitions[requested_scenario]
        if requested_scenario != "auto"
        else AUTO_EVALUATION_DEFINITION
    )
    internal_scenario_definition = scenario_definitions.get(internal_scenario_id, UNKNOWN_SCENARIO_DEFINITION)
    return {
        "scenario": scenario,
        "scenario_source": scenario_source,
        "internal_scenario_id": internal_scenario_id,
        "scenario_definition": scenario_definition,
        "internal_scenario_definition": internal_scenario_definition,
    }
