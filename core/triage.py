from typing import Any

from core.healthchecks import (
    evaluate_api_items_nonempty,
    evaluate_api_items_schema_ok,
)
from core.verifier import run_postcheck

DOMAIN_POLICY_MAP = {
    "reverse_proxy_or_upstream_mismatch": {
        "files": ["nginx/nginx.conf", "app/app.env"],
        "services": ["nginx", "app"],
        "allowed_actions": [
            "edit_file",
            "run_config_test",
            "restart_compose_service",
            "rebuild_compose_service",
        ],
    },
    "app_startup_or_dependency_failure": {
        "files": ["app/requirements.txt", "app/main.py", "app/app.env"],
        "services": ["app"],
        "allowed_actions": ["edit_file", "rebuild_compose_service"],
    },
    "app_config_or_env_mismatch": {
        "files": ["app/app.env", "app/main.py", "nginx/nginx.conf"],
        "services": ["app", "nginx"],
        "allowed_actions": [
            "edit_file",
            "rebuild_compose_service",
            "restart_compose_service",
            "run_config_test",
        ],
    },
    "database_auth_or_connectivity_issue": {
        "files": ["app/app.env", "app/main.py"],
        "services": ["app", "db"],
        "allowed_actions": ["edit_file", "rebuild_compose_service"],
    },
    "query_or_code_bug": {
        "files": ["app/main.py", "app/app.env"],
        "services": ["app"],
        "allowed_actions": ["edit_file", "rebuild_compose_service"],
    },
    "schema_drift": {
        "files": ["app/main.py", "app/app.env"],
        "services": ["app"],
        "allowed_actions": ["edit_file", "rebuild_compose_service"],
    },
    "healthcheck_only_failure": {
        "files": ["app/main.py"],
        "services": ["app"],
        "allowed_actions": ["edit_file", "rebuild_compose_service"],
    },
    "ambiguous_service_disagreement": {
        "files": ["nginx/nginx.conf", "app/main.py", "app/app.env"],
        "services": ["nginx", "app"],
        "allowed_actions": [
            "edit_file",
            "run_config_test",
            "restart_compose_service",
            "rebuild_compose_service",
        ],
    },
    "unknown": {
        "files": ["nginx/nginx.conf", "app/main.py", "app/requirements.txt", "app/app.env"],
        "services": ["nginx", "app"],
        "allowed_actions": [
            "edit_file",
            "run_config_test",
            "restart_compose_service",
            "rebuild_compose_service",
        ],
    },
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


def _score_domain(
    domains: dict[str, dict[str, Any]],
    domain: str,
    confidence: float,
    evidence: str,
) -> None:
    candidate = domains[domain]
    candidate["confidence"] = max(candidate["confidence"], confidence)
    if evidence not in candidate["evidence"]:
        candidate["evidence"].append(evidence)


def _rank_domains(observation: dict[str, Any]) -> list[dict[str, Any]]:
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
    baseline_app_port = str(observation.get("static_observations", {}).get("baseline_app_port", "")).strip()
    historical_evidence = observation.get("historical_evidence", [])
    api_nonempty = evaluate_api_items_nonempty(api_items)
    api_schema_ok = evaluate_api_items_schema_ok(api_items)

    domains = {
        key: {"domain": key, "confidence": 0.0, "evidence": []}
        for key in DOMAIN_POLICY_MAP
    }

    if "server app:8001" in nginx_snippet:
        _score_domain(
            domains,
            "reverse_proxy_or_upstream_mismatch",
            0.92,
            "nginx configuration snippet shows an upstream port mismatch",
        )
    if "server backend:8000" in nginx_snippet:
        _score_domain(
            domains,
            "reverse_proxy_or_upstream_mismatch",
            0.9,
            "nginx configuration snippet shows an upstream host mismatch",
        )
    if any(pattern in nginx_patterns for pattern in ["host not found in upstream", "could not be resolved"]) and healthz.get("status") != 200:
        _score_domain(
            domains,
            "reverse_proxy_or_upstream_mismatch",
            0.94,
            "nginx logs show upstream name resolution failure",
        )
    if any(pattern in nginx_patterns for pattern in ["connect() failed", "502 Bad Gateway", "no live upstreams"]) and healthz.get("status") != 200:
        _score_domain(
            domains,
            "reverse_proxy_or_upstream_mismatch",
            0.72,
            "nginx logs show upstream connection failure",
        )
    elif any(pattern in nginx_patterns for pattern in ["connect() failed", "no live upstreams"]) and healthz.get("status") == 200:
        _score_domain(
            domains,
            "ambiguous_service_disagreement",
            0.28,
            "recent nginx logs still contain older upstream failures that do not match the current healthy /healthz state",
        )
    if any(
        pattern in app_patterns
        for pattern in ["ModuleNotFoundError", "No module named", "uvicorn: not found", "Error loading ASGI app"]
    ):
        _score_domain(
            domains,
            "app_startup_or_dependency_failure",
            0.95,
            "app logs show startup or dependency failure",
        )
    if _contains_any(http_evidence_text, ["Access denied", "using password: YES", "OperationalError"]):
        _score_domain(
            domains,
            "database_auth_or_connectivity_issue",
            0.95,
            "HTTP error evidence indicates a database authentication or connectivity issue",
        )
    if "DB_PASSWORD=" in app_env_snippet and domains["database_auth_or_connectivity_issue"]["confidence"] > 0:
        _score_domain(
            domains,
            "app_config_or_env_mismatch",
            0.72,
            "editable app env snippet exposes a database credential setting",
        )
    if app_port and baseline_app_port and app_port != baseline_app_port:
        _score_domain(
            domains,
            "app_config_or_env_mismatch",
            0.82,
            "editable app env or log evidence shows a non-baseline application listen port",
        )
    if (
        "Uvicorn running on http://0.0.0.0:" in str(observation.get("service_logs", {}).get("app", ""))
        and app_port
        and baseline_app_port
        and app_port != baseline_app_port
    ):
        _score_domain(
            domains,
            "app_config_or_env_mismatch",
            0.86,
            f"app logs show the service listening on port {app_port} instead of the baseline port",
        )
    if (
        app_port
        and baseline_app_port
        and app_port != baseline_app_port
        and f"server app:{baseline_app_port}" in nginx_snippet
        and any(pattern in nginx_patterns for pattern in ["connect() failed", "502 Bad Gateway"])
    ):
        _score_domain(
            domains,
            "ambiguous_service_disagreement",
            0.9,
            "app listen-port evidence disagrees with the nginx upstream configuration",
        )
        _score_domain(
            domains,
            "reverse_proxy_or_upstream_mismatch",
            0.68,
            "reverse proxy symptoms may be downstream of an app-side listen-port drift",
        )
    if healthz.get("status") == 200 and api_items.get("status") != 200 and "internal error" in http_evidence_text:
        _score_domain(
            domains,
            "query_or_code_bug",
            0.48,
            "the API fails while the app is otherwise reachable, but the current HTTP evidence is opaque",
        )
    if "opaque_items_failure" in app_patterns:
        _score_domain(
            domains,
            "query_or_code_bug",
            0.56,
            "app logs show an opaque API failure marker without exposing the exact root cause",
        )
    if "K_ITEMS_QUERY" in app_main_snippet:
        _score_domain(
            domains,
            "query_or_code_bug",
            0.58,
            "visible app code snippet routes the failing API query through an indirect constant that needs narrower inspection",
        )
    if healthz.get("status") == 200 and api_items.get("status") == 200 and not api_nonempty["ok"]:
        _score_domain(
            domains,
            "query_or_code_bug",
            0.86,
            "the items API returns HTTP 200 but the payload is empty, which suggests a hidden query or fallback-code path",
        )
    if healthz.get("status") == 200 and api_items.get("status") == 200 and api_nonempty["ok"] and not api_schema_ok["ok"]:
        _score_domain(
            domains,
            "query_or_code_bug",
            0.82,
            "the items API returns HTTP 200 but the payload schema is degraded",
        )
    if healthz.get("status") == 200 and api_items.get("status") != 200 and _contains_any(
        http_evidence_text, ["itemz", "doesn't exist", "Table '"]
    ):
        _score_domain(
            domains,
            "query_or_code_bug",
            0.9,
            "the API fails while the app is running and the error points to a missing table",
        )
    if "FROM itemz ORDER BY id" in app_main_snippet:
        _score_domain(
            domains,
            "query_or_code_bug",
            0.95,
            "editable app code snippet shows the query targeting a non-existent table",
        )
    if "return []" in app_main_snippet and "itemz" in app_main_snippet:
        _score_domain(
            domains,
            "query_or_code_bug",
            0.97,
            "editable app code snippet shows a broken query whose exception path silently returns an empty fallback payload",
        )
    if healthz.get("status") == 200 and api_items.get("status") != 200 and _contains_any(
        http_evidence_text, ["Unknown column", "details"]
    ):
        _score_domain(
            domains,
            "schema_drift",
            0.92,
            "the API fails while the app is running and the error points to a missing column",
        )
    if "name, details FROM items" in app_main_snippet:
        _score_domain(
            domains,
            "schema_drift",
            0.95,
            "editable app code snippet shows the query targeting a non-existent column",
        )
    if (
        historical_evidence
        and healthz.get("status") == 200
        and api_items.get("status") != 200
        and any(marker in app_main_snippet for marker in ["itemz", "details"])
    ):
        _score_domain(
            domains,
            "query_or_code_bug",
            0.74,
            "current app-level query evidence is stronger than stale reverse-proxy failures remaining in recent logs",
        )
    if healthz.get("status") != 200 and api_items.get("status") == 200:
        _score_domain(
            domains,
            "healthcheck_only_failure",
            0.88,
            "the health endpoint fails while the main API still succeeds",
        )
    if "SELECT missing FROM health_checks" in app_main_snippet:
        _score_domain(
            domains,
            "healthcheck_only_failure",
            0.95,
            "editable app code snippet shows a broken health check query",
        )

    ranked = sorted(
        (candidate for candidate in domains.values() if candidate["confidence"] > 0),
        key=lambda candidate: candidate["confidence"],
        reverse=True,
    )
    if not ranked:
        return [
            {
                "domain": "unknown",
                "confidence": 0.25,
                "evidence": ["no dominant domain-specific signal was found in the current observation"],
            }
        ]
    return ranked


def _merge_candidate_scope(suspected_domains: list[dict[str, Any]]) -> dict[str, Any]:
    top_confidence = suspected_domains[0]["confidence"] if suspected_domains else 0.0
    threshold = max(0.3, top_confidence * 0.55)
    selected_domains = [
        candidate["domain"]
        for candidate in suspected_domains
        if candidate["confidence"] >= threshold
    ]
    if not selected_domains:
        selected_domains = ["unknown"]

    files: set[str] = set()
    services: set[str] = set()
    allowed_actions: set[str] = set()
    for domain in selected_domains[:3]:
        policy = DOMAIN_POLICY_MAP.get(domain, DOMAIN_POLICY_MAP["unknown"])
        files.update(policy["files"])
        services.update(policy["services"])
        allowed_actions.update(policy["allowed_actions"])

    ordered_files = [path for path in ["nginx/nginx.conf", "app/main.py", "app/requirements.txt", "app/app.env"] if path in files]
    ordered_services = [service for service in ["nginx", "app", "db"] if service in services]
    ordered_actions = [
        action
        for action in ["edit_file", "rebuild_compose_service", "restart_compose_service", "run_config_test"]
        if action in allowed_actions
    ]

    return {
        "files": ordered_files,
        "editable_files": ordered_files,
        "services": ordered_services,
        "allowed_actions": ordered_actions,
    }


def _ambiguity_level(suspected_domains: list[dict[str, Any]]) -> str:
    if not suspected_domains:
        return "high"
    if suspected_domains[0]["domain"] == "unknown":
        return "high"
    if len(suspected_domains) == 1:
        return "low" if suspected_domains[0]["confidence"] >= 0.8 else "medium"
    gap = suspected_domains[0]["confidence"] - suspected_domains[1]["confidence"]
    if suspected_domains[0]["confidence"] < 0.55:
        return "high"
    if gap >= 0.25:
        return "low"
    if gap >= 0.1:
        return "medium"
    return "high"


def _missing_evidence_and_next_steps(
    suspected_domains: list[dict[str, Any]],
    observation: dict[str, Any],
) -> tuple[list[str], list[str]]:
    missing_evidence: list[str] = []
    recommended_next_observations: list[str] = []
    top_domain = suspected_domains[0]["domain"] if suspected_domains else "unknown"
    ambiguity = _ambiguity_level(suspected_domains)
    file_snippets = observation.get("file_snippets", {})
    baseline_app_port = str(observation.get("static_observations", {}).get("baseline_app_port", "")).strip()
    app_excerpt = str(observation.get("relevant_log_excerpts", {}).get("app", ""))
    nginx_excerpt = str(observation.get("relevant_log_excerpts", {}).get("nginx", ""))
    http_error_text = "\n".join(str(value) for value in observation.get("http_error_evidence", {}).values())

    if top_domain in {"query_or_code_bug", "schema_drift", "healthcheck_only_failure"} and (
        ambiguity != "low" or not app_excerpt
    ):
        if not app_excerpt:
            missing_evidence.append("more specific app error excerpt")
        if "cursor.execute" not in str(file_snippets.get("app/main.py", "")):
            missing_evidence.append("a narrower code snippet around the failing query or health check")
        recommended_next_observations.extend(
            ["expand app log excerpt", "extract narrower relevant snippet from app/main.py"]
        )
    if top_domain == "query_or_code_bug" and "internal error" in http_error_text:
        missing_evidence.append("the HTTP layer is opaque and the precise query failure is still hidden")
        recommended_next_observations.extend(
            ["expand app log excerpt", "extract narrower relevant snippet from app/main.py"]
        )

    if top_domain in {"reverse_proxy_or_upstream_mismatch", "ambiguous_service_disagreement"} and (
        ambiguity != "low" or not nginx_excerpt
    ):
        if not nginx_excerpt:
            missing_evidence.append("more specific nginx upstream error excerpt")
        if "server " not in str(file_snippets.get("nginx/nginx.conf", "")):
            missing_evidence.append("a narrower nginx upstream configuration snippet")
        recommended_next_observations.extend(
            [
                "expand nginx log excerpt",
                "extract narrower relevant snippet from nginx/nginx.conf",
                "run nginx config test as observation",
            ]
        )

    if top_domain in {"app_config_or_env_mismatch", "database_auth_or_connectivity_issue", "ambiguous_service_disagreement"} and (
        ambiguity != "low"
    ):
        if "DB_PASSWORD=" not in str(file_snippets.get("app/app.env", "")) and "APP_PORT=" not in str(
            file_snippets.get("app/app.env", "")
        ):
            missing_evidence.append("a narrower app environment snippet")
        if not _contains_any(http_error_text, ["Access denied", "database error", "500", "502"]):
            missing_evidence.append("more specific application-side error evidence")
        recommended_next_observations.extend(
            ["extract narrower relevant snippet from app/app.env", "expand app log excerpt"]
        )
    if (
        top_domain in {"reverse_proxy_or_upstream_mismatch", "ambiguous_service_disagreement"}
        and baseline_app_port
        and f"APP_PORT={baseline_app_port}" not in str(file_snippets.get("app/app.env", ""))
        and "DB_PASSWORD=" not in str(file_snippets.get("app/app.env", ""))
    ):
        missing_evidence.append("additional downstream application failures may still be masked until upstream reachability is restored")
    if top_domain in {
        "reverse_proxy_or_upstream_mismatch",
        "ambiguous_service_disagreement",
        "app_startup_or_dependency_failure",
        "database_auth_or_connectivity_issue",
        "app_config_or_env_mismatch",
    }:
        missing_evidence.append(
            "downstream application faults may remain masked until the current upstream, startup, or credential blocker is cleared"
        )

    if top_domain == "unknown":
        missing_evidence.extend(
            ["a narrower app error excerpt", "a narrower nginx error excerpt", "a more specific editable file snippet"]
        )
        recommended_next_observations.extend(
            [
                "expand app log excerpt",
                "expand nginx log excerpt",
                "extract narrower relevant snippet from app/main.py",
                "extract narrower relevant snippet from nginx/nginx.conf",
            ]
        )

    deduped_missing = list(dict.fromkeys(missing_evidence))
    deduped_next = list(dict.fromkeys(recommended_next_observations))
    return deduped_missing, deduped_next[:4]


def _triage_summary(
    suspected_domains: list[dict[str, Any]],
    ambiguity_level: str,
    observation: dict[str, Any],
) -> str:
    if not suspected_domains:
        return "No domain hypothesis was produced from the current observation."
    primary = suspected_domains[0]
    historical_evidence = observation.get("historical_evidence", [])
    if primary["domain"] == "unknown":
        return "The current observation is too weak or inconsistent to support a confident recovery-domain hypothesis."
    if historical_evidence and primary["domain"] in {"query_or_code_bug", "schema_drift"}:
        return (
            f"The strongest current-state hypothesis is {primary['domain']}. Older reverse-proxy errors remain in recent logs, "
            f"so overall ambiguity is {ambiguity_level} and stale evidence should be treated cautiously."
        )
    if len(suspected_domains) == 1 or suspected_domains[1]["confidence"] < 0.3:
        return (
            f"The strongest hypothesis is {primary['domain']} with {ambiguity_level} ambiguity "
            "based on the currently visible evidence."
        )
    secondary = suspected_domains[1]
    return (
        f"The strongest hypothesis is {primary['domain']}, but {secondary['domain']} remains plausible. "
        f"Overall ambiguity is {ambiguity_level}."
    )


def build_triage_result(
    observation: dict[str, Any],
) -> dict[str, Any]:
    suspected_domains = _rank_domains(observation)
    candidate_scope = _merge_candidate_scope(suspected_domains)
    missing_evidence, recommended_next_observations = _missing_evidence_and_next_steps(
        suspected_domains,
        observation,
    )
    ambiguity_level = _ambiguity_level(suspected_domains)
    triage_summary = _triage_summary(suspected_domains, ambiguity_level, observation)

    initial_postcheck_result = run_postcheck(
        {
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
    )

    return {
        "suspected_domains": suspected_domains,
        "candidate_scope": candidate_scope,
        "missing_evidence": missing_evidence,
        "recommended_next_observations": recommended_next_observations,
        "ambiguity_level": ambiguity_level,
        "triage_summary": triage_summary,
        "initial_postcheck_result": initial_postcheck_result,
        "detection_confidence": suspected_domains[0]["confidence"],
        "detection_evidence": suspected_domains[0]["evidence"],
        "detected_fault_class": suspected_domains[0]["domain"],
        "alternative_candidates": suspected_domains[1:],
    }
