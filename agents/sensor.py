import re
import time
from typing import Any

from core.healthchecks import (
    collect_service_logs,
    docker_compose_ps,
    http_check,
    nginx_config_test,
)
from core.policies import resolve_repo_path
from core.state import SingleAgentState


OBSERVATION_STABILIZATION_SECONDS = 2
OBSERVATION_STABILIZATION_ATTEMPTS = 2


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
    health_body = str(healthz.get("body", ""))
    api_body = str(api_items.get("body", ""))
    if healthz.get("status") != 200:
        symptoms.append(f"/healthz returned {healthz.get('status')}")
    if api_items.get("status") != 200:
        symptoms.append(f"/api/items returned {api_items.get('status')}")

    nginx_log = logs.get("nginx", "")
    app_log = logs.get("app", "")
    if "connect() failed" in nginx_log:
        symptoms.append("nginx upstream connection failure observed")
    if "host not found in upstream" in nginx_log or "could not be resolved" in nginx_log:
        symptoms.append("nginx upstream host resolution failure observed")
    if "ModuleNotFoundError" in app_log or "uvicorn: not found" in app_log:
        symptoms.append("application dependency or startup failure observed")
    if "database error" in app_log or "Access denied" in app_log:
        symptoms.append("database connectivity failure observed")
    if "opaque_items_failure" in app_log:
        symptoms.append("application emitted an opaque API failure marker")
    if "Uvicorn running on http://0.0.0.0:9000" in app_log:
        symptoms.append("application listen port drift observed")
    if healthz.get("status") == 200 and api_items.get("status") != 200 and "doesn't exist" in api_body:
        symptoms.append("application query references a missing table")
    if healthz.get("status") == 200 and api_items.get("status") != 200 and "Unknown column" in api_body:
        symptoms.append("application query references a missing column")
    if healthz.get("status") == 200 and api_items.get("status") != 200 and "internal error" in api_body:
        symptoms.append("application API failure is opaque at the HTTP layer")
    if healthz.get("status") != 200 and api_items.get("status") == 200:
        symptoms.append("partial failure observed: health endpoint is broken while the main API still works")
    if not symptoms:
        symptoms.append("service degradation observed but no dominant symptom detected")
    return symptoms


def _extract_relevant_snippet(path_value: str, needles: str | list[str], context: int = 2) -> str:
    file_text = resolve_repo_path(path_value).read_text()
    lines = file_text.splitlines()
    needle_list = [needles] if isinstance(needles, str) else needles
    snippets: list[str] = []
    seen_windows: set[tuple[int, int]] = set()

    for needle in needle_list:
        for index, line in enumerate(lines):
            if needle in line:
                window_start = max(0, index - context)
                window_end = min(len(lines), index + context + 1)
                if (window_start, window_end) in seen_windows:
                    continue
                seen_windows.add((window_start, window_end))
                if context == 0:
                    snippets.append(line)
                else:
                    snippets.append("\n".join(lines[window_start:window_end]))

    if snippets:
        return "\n...\n".join(snippets[:4])
    if len(lines) <= 8:
        return "\n".join(lines)
    return "\n".join(lines[:8])


def _extract_braced_block(lines: list[str], start_index: int) -> str:
    block: list[str] = []
    depth = 0
    started = False
    for index in range(start_index, len(lines)):
        line = lines[index]
        block.append(line)
        if "{" in line:
            depth += line.count("{")
            started = True
        if "}" in line and started:
            depth -= line.count("}")
            if depth <= 0:
                break
    return "\n".join(block).strip()


def _extract_nginx_reference_snippet() -> str:
    file_text = resolve_repo_path("nginx/nginx.conf").read_text()
    lines = file_text.splitlines()
    upstream_block = ""
    location_block = ""

    for index, line in enumerate(lines):
        if not upstream_block and "upstream " in line and "{" in line:
            upstream_block = _extract_braced_block(lines, index)
        if "proxy_pass http://" in line:
            location_start = index
            for probe in range(index, -1, -1):
                if "location " in lines[probe] and "{" in lines[probe]:
                    location_start = probe
                    break
            location_block = _extract_braced_block(lines, location_start)
            break

    sections = [section for section in [upstream_block, location_block] if section]
    if sections:
        return "\n...\n".join(sections)
    return _extract_relevant_snippet(
        "nginx/nginx.conf",
        ["upstream backend", "server app:", "server backend:", "proxy_pass http://backend"],
        context=2,
    )


def _extract_log_excerpt(log_text: str, patterns: list[str], context: int = 1, fallback_tail: int = 6) -> str:
    lines = [line for line in log_text.splitlines() if line.strip()]
    noise_markers = (
        "Collecting ",
        "Downloading ",
        "Installing collected packages",
        "Successfully installed",
        "Requirement already satisfied:",
        "[notice] ",
    )
    filtered_lines = [line for line in lines if not any(marker in line for marker in noise_markers)]
    if filtered_lines:
        lines = filtered_lines
    if not lines:
        return ""
    for index in range(len(lines) - 1, -1, -1):
        line = lines[index]
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


def _has_upstream_blocker(service_logs: dict[str, str], healthz: dict[str, Any], api_items: dict[str, Any]) -> bool:
    nginx_log = service_logs.get("nginx", "")
    return (
        healthz.get("status") in {502, 503, 504}
        or api_items.get("status") in {502, 503, 504}
        or any(
            marker in nginx_log
            for marker in ["connect() failed", "host not found in upstream", "could not be resolved", "no live upstreams"]
        )
    )


def _has_startup_blocker(service_logs: dict[str, str]) -> bool:
    app_log = service_logs.get("app", "")
    return any(
        marker in app_log
        for marker in ["ModuleNotFoundError", "No module named", "uvicorn: not found", "Error loading ASGI app"]
    )


def _has_db_auth_blocker(service_logs: dict[str, str], healthz: dict[str, Any], api_items: dict[str, Any]) -> bool:
    combined_text = "\n".join(
        [
            service_logs.get("app", ""),
            str(healthz.get("body", "")),
            str(api_items.get("body", "")),
        ]
    )
    return any(
        marker in combined_text
        for marker in ["Access denied", "using password: YES", "database error", "OperationalError"]
    )


def _should_mask_app_main_query_snippet(
    service_logs: dict[str, str],
    healthz: dict[str, Any],
    api_items: dict[str, Any],
) -> bool:
    if _has_startup_blocker(service_logs):
        return True
    if _has_upstream_blocker(service_logs, healthz, api_items) and healthz.get("status") != 200:
        return True
    if _has_db_auth_blocker(service_logs, healthz, api_items) and api_items.get("status") != 200:
        return True
    return False


def _masked_app_main_snippet() -> str:
    return _extract_relevant_snippet(
        "app/main.py",
        ['@app.get("/api/items")', "def list_items():", '@app.get("/healthz")', "def healthz():"],
        context=0,
    )


def _collect_suspicious_patterns(
    service_logs: dict[str, str],
    healthz: dict,
    api_items: dict,
) -> dict[str, list[str]]:
    suspicious_patterns = {
        "nginx": [
            "connect() failed",
            "502 Bad Gateway",
            "no live upstreams",
            "host not found in upstream",
            "could not be resolved",
        ],
        "app": [
            "ModuleNotFoundError",
            "No module named",
            "uvicorn: not found",
            "database error",
            "Access denied",
            "OperationalError",
            "500 Internal Server Error",
            "Unknown column",
            "doesn't exist",
            "opaque_items_failure",
            "Uvicorn running on http://0.0.0.0:9000",
        ],
        "http": [
            "database error",
            "Access denied",
            "502 Bad Gateway",
            "Unknown column",
            "doesn't exist",
            "internal error",
        ],
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


def _collect_static_observations(service_logs: dict[str, str], file_snippets: dict[str, str]) -> dict[str, Any]:
    observations: dict[str, Any] = {}
    app_log = service_logs.get("app", "")
    marker = "Uvicorn running on http://0.0.0.0:"
    if marker in app_log:
        observations["app_listen_port"] = app_log.split(marker, 1)[1].split()[0].strip()
    if "APP_PORT=" in file_snippets.get("app/app.env", ""):
        for line in file_snippets["app/app.env"].splitlines():
            if line.startswith("APP_PORT="):
                observations["app_env_port"] = line.split("=", 1)[1].strip()

    nginx_text = resolve_repo_path("nginx/nginx.conf").read_text()
    upstream_groups = re.findall(r"upstream\s+([A-Za-z0-9_-]+)\s*{", nginx_text)
    proxy_targets = re.findall(r"proxy_pass\s+http://([A-Za-z0-9_.:-]+);", nginx_text)
    upstream_members = re.findall(r"^\s*server\s+([A-Za-z0-9_.:-]+)\s+resolve;", nginx_text, flags=re.MULTILINE)
    if upstream_groups:
        observations["nginx_upstream_groups"] = upstream_groups
    if proxy_targets:
        observations["nginx_proxy_pass_targets"] = proxy_targets
    if upstream_members:
        observations["nginx_upstream_members"] = upstream_members
    if any(target in upstream_groups for target in proxy_targets):
        observations["nginx_reference_note"] = (
            "proxy_pass may reference a named nginx upstream group, while server lines inside that upstream block "
            "name backend hosts or Docker services"
        )
    return observations


def _app_env_needles(service_logs: dict[str, str], healthz: dict[str, Any], api_items: dict[str, Any]) -> list[str]:
    needles: list[str] = []
    app_log = service_logs.get("app", "")
    nginx_log = service_logs.get("nginx", "")
    http_text = "\n".join(str(value) for value in [healthz.get("body", ""), api_items.get("body", "")])

    if (
        "Uvicorn running on http://0.0.0.0:9000" in app_log
        or "connect() failed" in nginx_log
        or healthz.get("status") == 502
        or api_items.get("status") == 502
    ):
        needles.append("APP_PORT=")
    if any(marker in app_log for marker in ["Access denied", "database error", "OperationalError"]) or any(
        marker in http_text for marker in ["Access denied", "database error", "using password: YES"]
    ):
        needles.append("DB_PASSWORD=")

    return needles or ["APP_PORT="]


def _app_main_needles(service_logs: dict[str, str], healthz: dict[str, Any], api_items: dict[str, Any]) -> list[str]:
    app_log = service_logs.get("app", "")
    api_body = str(api_items.get("body", ""))
    if _should_mask_app_main_query_snippet(service_logs, healthz, api_items):
        return ['@app.get("/api/items")', "def list_items():", '@app.get("/healthz")', "def healthz():"]
    if healthz.get("status") == 200 and api_items.get("status") != 200 and "internal error" in api_body:
        return ['@app.get("/api/items")', "def list_items():", "cursor.execute(K_ITEMS_QUERY)"]
    if "opaque_items_failure" in app_log:
        return ["opaque_items_failure", "cursor.execute(K_ITEMS_QUERY)", "@app.get(\"/api/items\")"]
    if healthz.get("status") != 200 and api_items.get("status") == 200:
        return ["SELECT missing FROM health_checks", "@app.get(\"/healthz\")", "def healthz():"]
    return ["cursor.execute(", "itemz", "details", "SELECT missing FROM health_checks", "K_ITEMS_QUERY"]


def _build_temporal_evidence(
    service_logs: dict[str, str],
    healthz: dict[str, Any],
    api_items: dict[str, Any],
    file_snippets: dict[str, str],
    relevant_log_excerpts: dict[str, str],
) -> tuple[list[str], list[str]]:
    current_state_evidence: list[str] = []
    historical_evidence: list[str] = []

    current_state_evidence.append(f"/healthz currently returns {healthz.get('status')}")
    current_state_evidence.append(f"/api/items currently returns {api_items.get('status')}")

    nginx_excerpt = relevant_log_excerpts.get("nginx", "")
    app_excerpt = relevant_log_excerpts.get("app", "")
    if "APP_PORT=9000" in file_snippets.get("app/app.env", ""):
        current_state_evidence.append("visible app env snippet shows APP_PORT=9000")
    if "DB_PASSWORD=wrongpassword" in file_snippets.get("app/app.env", ""):
        current_state_evidence.append("visible app env snippet shows a non-baseline DB password")
    if "server app:8001" in file_snippets.get("nginx/nginx.conf", ""):
        current_state_evidence.append("visible nginx snippet shows an upstream port mismatch")
    if "server backend:8000" in file_snippets.get("nginx/nginx.conf", ""):
        current_state_evidence.append("visible nginx snippet shows an upstream host mismatch")
    if "K_ITEMS_QUERY" in file_snippets.get("app/main.py", ""):
        current_state_evidence.append("visible app code snippet references an indirect query constant")
    if "itemz" in file_snippets.get("app/main.py", ""):
        current_state_evidence.append("visible app code snippet references a non-existent table name")
    if "details" in file_snippets.get("app/main.py", ""):
        current_state_evidence.append("visible app code snippet references a non-existent column name")
    if "opaque_items_failure" in app_excerpt:
        current_state_evidence.append("current app excerpt shows an opaque API failure marker")
    if any(marker in app_excerpt for marker in ["Unknown column", "doesn't exist", "Access denied", "ModuleNotFoundError"]):
        current_state_evidence.append("current app excerpt contains a concrete application-side failure marker")
    if healthz.get("status") != 200 and any(
        marker in nginx_excerpt for marker in ["connect() failed", "host not found in upstream", "could not be resolved", "no live upstreams"]
    ):
        current_state_evidence.append("current nginx excerpt contains an upstream failure marker")

    nginx_log = service_logs.get("nginx", "")
    if healthz.get("status") == 200 and "connect() failed" in nginx_log:
        historical_evidence.append(
            "recent nginx logs still contain older upstream connection failures even though /healthz currently succeeds"
        )
    if healthz.get("status") == 200 and "no live upstreams" in nginx_log:
        historical_evidence.append(
            "recent nginx logs still contain older no-live-upstreams errors that do not match the current healthy /healthz state"
        )
    if any(marker in app_excerpt for marker in ["Access denied", "Unknown column", "doesn't exist", "database error"]) and any(
        marker in nginx_log for marker in ["connect() failed", "host not found in upstream", "could not be resolved", "no live upstreams"]
    ):
        historical_evidence.append(
            "recent nginx logs still contain older upstream failures, but the stronger current evidence is now application-side"
        )

    return current_state_evidence, historical_evidence


def _collect_observation_snapshot() -> tuple[dict[str, str], dict, dict, dict]:
    service_logs = collect_service_logs(["nginx", "app", "db"], tail=50)
    compose_ps = docker_compose_ps()
    healthz = http_check("/healthz")
    api_items = http_check("/api/items")
    return service_logs, compose_ps, healthz, api_items


def _should_stabilize_observation(service_logs: dict[str, str], healthz: dict, api_items: dict) -> bool:
    app_log = service_logs.get("app", "")
    settled_markers = (
        "Application startup complete.",
        "Uvicorn running on http://0.0.0.0:",
        "ModuleNotFoundError",
        "No module named",
        "uvicorn: not found",
        "Error loading ASGI app",
        "Access denied",
        "OperationalError",
        "Unknown column",
        "doesn't exist",
    )
    install_markers = ("Collecting ", "Installing collected packages", "Successfully installed")
    endpoint_failed = healthz.get("status") != 200 or api_items.get("status") != 200
    if not endpoint_failed:
        return False
    if any(marker in app_log for marker in install_markers):
        return True
    if not any(marker in app_log for marker in settled_markers):
        return True
    return False


def _base_file_snippets(
    service_logs: dict[str, str],
    healthz: dict[str, Any],
    api_items: dict[str, Any],
) -> dict[str, str]:
    app_main_snippet = (
        _masked_app_main_snippet()
        if _should_mask_app_main_query_snippet(service_logs, healthz, api_items)
        else _extract_relevant_snippet(
            "app/main.py",
            _app_main_needles(service_logs, healthz, api_items),
            context=1,
        )
    )
    return {
        "nginx/nginx.conf": _extract_nginx_reference_snippet(),
        "app/main.py": app_main_snippet,
        "app/requirements.txt": _extract_relevant_snippet(
            "app/requirements.txt",
            "uvicorn[standard]==",
            context=0,
        ),
        "app/app.env": _extract_relevant_snippet(
            "app/app.env",
            _app_env_needles(service_logs, healthz, api_items),
            context=0,
        ),
    }


def _base_log_excerpts(service_logs: dict[str, str]) -> dict[str, str]:
    return {
        "nginx": _extract_log_excerpt(
            service_logs.get("nginx", ""),
            ["connect() failed", "502 Bad Gateway", "no live upstreams", "host not found in upstream", "could not be resolved"],
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
                "Unknown column",
                "doesn't exist",
                "opaque_items_failure",
                "Uvicorn running on http://0.0.0.0:9000",
            ],
        ),
    }


def _build_observation(
    service_logs: dict[str, str],
    compose_ps: dict[str, Any],
    healthz: dict[str, Any],
    api_items: dict[str, Any],
) -> dict[str, Any]:
    file_snippets = _base_file_snippets(service_logs, healthz, api_items)
    relevant_log_excerpts = _base_log_excerpts(service_logs)
    current_state_evidence, historical_evidence = _build_temporal_evidence(
        service_logs,
        healthz,
        api_items,
        file_snippets,
        relevant_log_excerpts,
    )
    return {
        "compose_ps": compose_ps,
        "service_logs": service_logs,
        "health_checks": {
            "healthz": healthz,
            "api_items": api_items,
        },
        "file_snippets": file_snippets,
        "relevant_log_excerpts": relevant_log_excerpts,
        "http_error_evidence": _http_error_evidence(healthz, api_items),
        "suspicious_patterns": _collect_suspicious_patterns(service_logs, healthz, api_items),
        "static_observations": _collect_static_observations(service_logs, file_snippets),
        "current_state_evidence": current_state_evidence,
        "historical_evidence": historical_evidence,
    }


def _narrower_snippet(
    path_value: str,
    service_logs: dict[str, str],
    healthz: dict[str, Any],
    api_items: dict[str, Any],
) -> str:
    needle_map = {
        "nginx/nginx.conf": ["upstream backend", "server app:8001", "server backend:8000", "server app:8000", "proxy_pass http://backend", "location /"],
        "app/main.py": ["itemz", "details", "SELECT missing FROM health_checks", "cursor.execute(", "K_ITEMS_QUERY"],
        "app/app.env": ["APP_PORT=", "DB_PASSWORD="],
    }
    if path_value == "app/main.py" and _should_mask_app_main_query_snippet(service_logs, healthz, api_items):
        return _masked_app_main_snippet()
    return _extract_relevant_snippet(path_value, needle_map[path_value], context=3 if path_value == "app/main.py" else 1)


def additional_observation_node(state: SingleAgentState) -> SingleAgentState:
    requested = state.get("recommended_next_observations", [])
    collected: dict[str, Any] = {}
    observation = {
        **state["observation"],
        "file_snippets": dict(state["observation"].get("file_snippets", {})),
        "relevant_log_excerpts": dict(state["observation"].get("relevant_log_excerpts", {})),
    }

    if "expand app log excerpt" in requested:
        app_logs = collect_service_logs(["app"], tail=120).get("app", "")
        excerpt = _extract_log_excerpt(
            app_logs,
            [
                "ModuleNotFoundError",
                "Access denied",
                "OperationalError",
                "Unknown column",
                "doesn't exist",
                "opaque_items_failure",
                "500 Internal Server Error",
                "Uvicorn running on http://0.0.0.0:9000",
            ],
            context=3,
            fallback_tail=10,
        )
        if excerpt:
            observation["relevant_log_excerpts"]["app"] = excerpt
            collected["app_log_excerpt"] = excerpt

    if "expand nginx log excerpt" in requested:
        nginx_logs = collect_service_logs(["nginx"], tail=120).get("nginx", "")
        excerpt = _extract_log_excerpt(
            nginx_logs,
            ["connect() failed", "502 Bad Gateway", "host not found in upstream", "could not be resolved"],
            context=3,
            fallback_tail=10,
        )
        if excerpt:
            observation["relevant_log_excerpts"]["nginx"] = excerpt
            collected["nginx_log_excerpt"] = excerpt

    if "extract narrower relevant snippet from app/main.py" in requested:
        healthz = observation.get("health_checks", {}).get("healthz", {})
        api_items = observation.get("health_checks", {}).get("api_items", {})
        service_logs = observation.get("service_logs", {})
        snippet = _narrower_snippet("app/main.py", service_logs, healthz, api_items)
        observation["file_snippets"]["app/main.py"] = snippet
        collected["app/main.py"] = snippet

    if "extract narrower relevant snippet from app/app.env" in requested:
        healthz = observation.get("health_checks", {}).get("healthz", {})
        api_items = observation.get("health_checks", {}).get("api_items", {})
        service_logs = observation.get("service_logs", {})
        snippet = _narrower_snippet("app/app.env", service_logs, healthz, api_items)
        observation["file_snippets"]["app/app.env"] = snippet
        collected["app/app.env"] = snippet

    if "extract narrower relevant snippet from nginx/nginx.conf" in requested:
        healthz = observation.get("health_checks", {}).get("healthz", {})
        api_items = observation.get("health_checks", {}).get("api_items", {})
        service_logs = observation.get("service_logs", {})
        snippet = _narrower_snippet("nginx/nginx.conf", service_logs, healthz, api_items)
        observation["file_snippets"]["nginx/nginx.conf"] = snippet
        collected["nginx/nginx.conf"] = snippet

    if "run nginx config test as observation" in requested:
        collected["nginx_config_test"] = nginx_config_test()

    observation["additional_observation"] = {
        "requested": requested,
        "collected": collected,
    }

    _section("🛰️ [PHASE 2.5] ADDITIONAL OBSERVATION")
    print("requested:")
    for item in requested:
        print(f"- {item}")
    print()
    print("collected:")
    print(collected if collected else "(no new observation collected)")
    print()

    return {
        **state,
        "observation": observation,
        "additional_observation_used": True,
    }


def sensor_node(state: SingleAgentState) -> SingleAgentState:
    service_logs, compose_ps, healthz, api_items = _collect_observation_snapshot()
    attempts = 0
    while attempts < OBSERVATION_STABILIZATION_ATTEMPTS and _should_stabilize_observation(
        service_logs, healthz, api_items
    ):
        attempts += 1
        time.sleep(OBSERVATION_STABILIZATION_SECONDS)
        service_logs, compose_ps, healthz, api_items = _collect_observation_snapshot()

    observation = _build_observation(service_logs, compose_ps, healthz, api_items)
    observed_symptoms = _summarize_symptoms(service_logs, healthz, api_items)

    _section("🤖 [PHASE 1] SENSOR")
    print("Observed symptoms:")
    for symptom in observed_symptoms:
        print(f"- {symptom}")
    print()
    print("Nginx log excerpt:")
    print(_tail(service_logs.get("nginx", "")))
    print()
    if observation["file_snippets"]:
        print("Relevant file snippets:")
        for path_value, snippet in observation["file_snippets"].items():
            print(f"[{path_value}]")
            print(snippet)
            print()
    if observation["relevant_log_excerpts"].get("app"):
        print("Relevant app log excerpt:")
        print(observation["relevant_log_excerpts"]["app"])
        print()
    if observation["http_error_evidence"]:
        print("HTTP error evidence:")
        for check_name, body in observation["http_error_evidence"].items():
            print(f"[{check_name}] {body}")
        print()
    if observation["current_state_evidence"]:
        print("Current-state evidence:")
        for item in observation["current_state_evidence"]:
            print(f"- {item}")
        print()
    if observation["historical_evidence"]:
        print("Historical evidence:")
        for item in observation["historical_evidence"]:
            print(f"- {item}")
        print()

    return {
        **state,
        "observation": observation,
        "observed_symptoms": observed_symptoms,
    }
