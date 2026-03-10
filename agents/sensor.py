from core.healthchecks import collect_service_logs, docker_compose_ps, http_check
from core.policies import resolve_repo_path
from core.state import SingleAgentState


def _section(title: str) -> None:
    divider = "=" * 50
    print(divider)
    print(title)
    print(divider)


def _tail(text: str, count: int = 8) -> str:
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return "(no logs)"
    if len(lines) <= count:
        return "\n".join(lines)
    return "...\n" + "\n".join(lines[-count:])


def _summarize_symptoms(logs: dict[str, str], healthz: dict, api_items: dict) -> list[str]:
    symptoms: list[str] = []
    if healthz.get("status") != 200:
        symptoms.append(f"/healthz returned {healthz.get('status')}")
    if api_items.get("status") != 200:
        symptoms.append(f"/api/items returned {api_items.get('status')}")

    nginx_log = logs.get("nginx", "")
    app_log = logs.get("app", "")
    if "connect() failed" in nginx_log:
        symptoms.append("nginx upstream connection failure observed")
    if "ModuleNotFoundError" in app_log or "uvicorn: not found" in app_log:
        symptoms.append("application dependency or startup failure observed")
    if "database error" in app_log or "Access denied" in app_log:
        symptoms.append("database connectivity failure observed")
    if not symptoms:
        symptoms.append("service degradation observed but no dominant symptom detected")
    return symptoms


def _extract_relevant_snippet(path_value: str, needle: str, context: int = 2) -> str:
    file_text = resolve_repo_path(path_value).read_text()
    lines = file_text.splitlines()
    for index, line in enumerate(lines):
        if needle in line:
            window_start = max(0, index - context)
            window_end = min(len(lines), index + context + 1)
            if context == 0:
                return line
            return "\n".join(lines[window_start:window_end])
    if len(lines) <= 8:
        return "\n".join(lines)
    return "\n".join(lines[:8])


def _extract_log_excerpt(log_text: str, patterns: list[str], context: int = 1, fallback_tail: int = 6) -> str:
    lines = [line for line in log_text.splitlines() if line.strip()]
    if not lines:
        return ""
    for index, line in enumerate(lines):
        if any(pattern in line for pattern in patterns):
            start = max(0, index - context)
            end = min(len(lines), index + context + 1)
            return "\n".join(lines[start:end])
    if len(lines) <= fallback_tail:
        return "\n".join(lines)
    return "...\n" + "\n".join(lines[-fallback_tail:])


def _http_error_evidence(healthz: dict, api_items: dict) -> dict[str, str]:
    evidence: dict[str, str] = {}
    if healthz.get("status") and healthz.get("status") != 200:
        evidence["healthz"] = healthz.get("body", "")[:300]
    if api_items.get("status") and api_items.get("status") != 200:
        evidence["api_items"] = api_items.get("body", "")[:300]
    return evidence


def _collect_suspicious_patterns(
    service_logs: dict[str, str],
    healthz: dict,
    api_items: dict,
) -> dict[str, list[str]]:
    suspicious_patterns = {
        "nginx": ["connect() failed", "502 Bad Gateway"],
        "app": [
            "ModuleNotFoundError",
            "No module named",
            "uvicorn: not found",
            "database error",
            "Access denied",
            "OperationalError",
            "500 Internal Server Error",
        ],
        "http": ["database error", "Access denied", "502 Bad Gateway"],
    }
    health_and_api_text = "\n".join(
        str(value)
        for value in [healthz.get("body", ""), api_items.get("body", "")]
        if value
    )
    return {
        "nginx": [pattern for pattern in suspicious_patterns["nginx"] if pattern in service_logs.get("nginx", "")],
        "app": [pattern for pattern in suspicious_patterns["app"] if pattern in service_logs.get("app", "")],
        "http": [pattern for pattern in suspicious_patterns["http"] if pattern in health_and_api_text],
    }


def sensor_node(state: SingleAgentState) -> SingleAgentState:
    service_logs = collect_service_logs(["nginx", "app", "db"], tail=50)
    compose_ps = docker_compose_ps()
    healthz = http_check("/healthz")
    api_items = http_check("/api/items")
    observed_symptoms = _summarize_symptoms(service_logs, healthz, api_items)
    file_snippets: dict[str, str] = {}
    file_snippets["nginx/nginx.conf"] = _extract_relevant_snippet(
        "nginx/nginx.conf",
        "server app:",
    )
    file_snippets["app/requirements.txt"] = _extract_relevant_snippet(
        "app/requirements.txt",
        "uvicorn[standard]==",
        context=0,
    )
    file_snippets["app/app.env"] = _extract_relevant_snippet(
        "app/app.env",
        "DB_PASSWORD=",
        context=0,
    )

    relevant_log_excerpts = {
        "nginx": _extract_log_excerpt(
            service_logs.get("nginx", ""),
            ["connect() failed", "502 Bad Gateway"],
        ),
        "app": _extract_log_excerpt(
            service_logs.get("app", ""),
            [
                "ModuleNotFoundError",
                "No module named",
                "uvicorn: not found",
                "database error",
                "Access denied",
                "OperationalError",
                "500 Internal Server Error",
            ],
        ),
    }
    http_error_evidence = _http_error_evidence(healthz, api_items)
    suspicious_patterns = _collect_suspicious_patterns(service_logs, healthz, api_items)

    observation = {
        "compose_ps": compose_ps,
        "service_logs": service_logs,
        "health_checks": {
            "healthz": healthz,
            "api_items": api_items,
        },
        "file_snippets": file_snippets,
        "relevant_log_excerpts": relevant_log_excerpts,
        "http_error_evidence": http_error_evidence,
        "suspicious_patterns": suspicious_patterns,
    }

    _section("🤖 [PHASE 1] SENSOR")
    print("Observed symptoms:")
    for symptom in observed_symptoms:
        print(f"- {symptom}")
    print()
    print("Nginx log excerpt:")
    print(_tail(service_logs.get("nginx", "")))
    print()
    if file_snippets:
        print("Relevant file snippets:")
        for path_value, snippet in file_snippets.items():
            print(f"[{path_value}]")
            print(snippet)
            print()
    if relevant_log_excerpts.get("app"):
        print("Relevant app log excerpt:")
        print(relevant_log_excerpts["app"])
        print()
    if http_error_evidence:
        print("HTTP error evidence:")
        for check_name, body in http_error_evidence.items():
            print(f"[{check_name}] {body}")
        print()

    return {
        **state,
        "observation": observation,
        "observed_symptoms": observed_symptoms,
    }
