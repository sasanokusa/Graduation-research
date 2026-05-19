import re
import time
from typing import Any

from core.healthchecks import (
    classify_front_most_failure,
    collect_service_logs,
    docker_compose_ps,
    evaluate_api_items_nonempty,
    evaluate_api_items_schema_ok,
    evaluate_dc_no_degraded_mode,
    evaluate_dc_topology_contract_ok,
    evaluate_port_contract_matches_baseline,
    http_check,
    nginx_config_test,
)
from core.policies import get_baseline_app_port, resolve_repo_path
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


def _summarize_symptoms(logs: dict[str, str], healthz: dict, api_items: dict, topology: dict) -> list[str]:
    symptoms: list[str] = []
    api_body = str(api_items.get("body", ""))
    api_nonempty = evaluate_api_items_nonempty(api_items)
    api_schema_ok = evaluate_api_items_schema_ok(api_items)
    topology_contract = evaluate_dc_topology_contract_ok(topology)
    no_degraded_mode = evaluate_dc_no_degraded_mode(topology)
    if healthz.get("status") != 200:
        symptoms.append(f"/healthz returned {healthz.get('status')}")
    if api_items.get("status") != 200:
        symptoms.append(f"/api/items returned {api_items.get('status')}")
    if api_items.get("status") == 200 and not api_nonempty["ok"]:
        symptoms.append("/api/items returned 200 but the payload was empty")
    if api_items.get("status") == 200 and api_nonempty["ok"] and not api_schema_ok["ok"]:
        symptoms.append("/api/items returned 200 but the item schema was degraded")
    if topology.get("status") == 200 and not topology_contract["ok"]:
        symptoms.append("/api/topology returned 200 but the DC topology contract was degraded")
    if topology.get("status") == 200 and not no_degraded_mode["ok"]:
        symptoms.append("the topology endpoint reports degraded mode or a degraded topology state")

    nginx_log = logs.get("nginx", "")
    app_log = logs.get("app", "")
    if "connect() failed" in nginx_log:
        symptoms.append("nginx upstream connection failure observed")
    if "host not found in upstream" in nginx_log or "could not be resolved" in nginx_log:
        symptoms.append("nginx upstream host resolution failure observed")
    if "ModuleNotFoundError" in app_log or "uvicorn: not found" in app_log:
        symptoms.append("application dependency or startup failure observed")
    if "database error" in app_log or "Access denied" in app_log:
        symptoms.append("database authentication failure observed")
    if "Can't connect" in app_log or "Connection refused" in app_log:
        symptoms.append("database connectivity failure observed (host unreachable)")
    if "opaque_items_failure" in app_log:
        symptoms.append("application emitted an opaque API failure marker")
    baseline_app_port = get_baseline_app_port()
    if "Uvicorn running on http://0.0.0.0:" in app_log and (
        not baseline_app_port or f"Uvicorn running on http://0.0.0.0:{baseline_app_port}" not in app_log
    ):
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
        for marker in ["Access denied", "using password: YES", "OperationalError", "Can't connect", "Connection refused"]
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
            "Can't connect",
            "Connection refused",
            "Uvicorn running on http://0.0.0.0:",
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
    baseline_app_port = get_baseline_app_port()
    if baseline_app_port:
        observations["baseline_app_port"] = baseline_app_port
    if "APP_PORT=" in file_snippets.get("app/app.env", ""):
        for line in file_snippets["app/app.env"].splitlines():
            if line.startswith("APP_PORT="):
                observations["app_env_port"] = line.split("=", 1)[1].strip()
    topology_env_keys = [
        "CACHE_HOST",
        "CACHE_EXPECTED_HOST",
        "CACHE_HOST_GROUP",
        "CACHE_EXPECTED_GROUP",
        "QUEUE_HOST",
        "QUEUE_EXPECTED_HOST",
        "QUEUE_HOST_GROUP",
        "QUEUE_EXPECTED_GROUP",
        "METRICS_HOST",
        "METRICS_EXPECTED_HOST",
        "METRICS_HOST_GROUP",
        "METRICS_EXPECTED_GROUP",
        "APP_HOST_GROUP",
        "DEGRADED_MODE",
    ]
    topology_env: dict[str, str] = {}
    for line in file_snippets.get("app/app.env", "").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in topology_env_keys:
            topology_env[key] = value.strip()
    if topology_env:
        observations["dc_topology_env"] = topology_env

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


def _app_env_needles(
    service_logs: dict[str, str],
    healthz: dict[str, Any],
    api_items: dict[str, Any],
    topology: dict[str, Any] | None = None,
) -> list[str]:
    needles: list[str] = []
    app_log = service_logs.get("app", "")
    nginx_log = service_logs.get("nginx", "")
    http_text = "\n".join(str(value) for value in [healthz.get("body", ""), api_items.get("body", "")])

    if (
        "Uvicorn running on http://0.0.0.0:" in app_log
        or "connect() failed" in nginx_log
        or healthz.get("status") == 502
        or api_items.get("status") == 502
    ):
        needles.append("APP_PORT=")
    if any(marker in app_log for marker in ["Access denied", "database error", "OperationalError"]) or any(
        marker in http_text for marker in ["Access denied", "database error", "using password: YES"]
    ):
        needles.append("DB_PASSWORD=")
    if any(marker in app_log for marker in ["Can't connect", "Connection refused"]) or any(
        marker in http_text for marker in ["Can't connect", "Connection refused"]
    ):
        needles.append("DB_HOST=")
    topology = topology or {}
    topology_contract = evaluate_dc_topology_contract_ok(topology)
    if topology.get("status") == 200 and not topology_contract["ok"]:
        needles.extend(
            [
                "CACHE_HOST=",
                "CACHE_EXPECTED_HOST=",
                "CACHE_HOST_GROUP=",
                "CACHE_EXPECTED_GROUP=",
                "QUEUE_HOST=",
                "QUEUE_EXPECTED_HOST=",
                "QUEUE_HOST_GROUP=",
                "QUEUE_EXPECTED_GROUP=",
                "METRICS_HOST=",
                "METRICS_EXPECTED_HOST=",
                "METRICS_HOST_GROUP=",
                "METRICS_EXPECTED_GROUP=",
                "APP_HOST_GROUP=",
                "DEGRADED_MODE=",
            ]
        )

    return needles or ["APP_PORT=", "CACHE_HOST=", "QUEUE_HOST=", "METRICS_HOST=", "DEGRADED_MODE="]


def _app_main_needles(service_logs: dict[str, str], healthz: dict[str, Any], api_items: dict[str, Any]) -> list[str]:
    app_log = service_logs.get("app", "")
    api_body = str(api_items.get("body", ""))
    if _should_mask_app_main_query_snippet(service_logs, healthz, api_items):
        return ['@app.get("/api/items")', "def list_items():", '@app.get("/healthz")', "def healthz():"]
    if healthz.get("status") == 200 and api_items.get("status") == 200 and api_items.get("body", "").strip() == "[]":
        return ['@app.get("/api/items")', "itemz", "return []", "cursor.execute("]
    if healthz.get("status") == 200 and api_items.get("status") != 200 and "internal error" in api_body:
        return ['@app.get("/api/items")', "def list_items():", "cursor.execute(K_ITEMS_QUERY)"]
    if "opaque_items_failure" in app_log:
        return ["opaque_items_failure", "cursor.execute(K_ITEMS_QUERY)", "@app.get(\"/api/items\")"]
    if healthz.get("status") != 200 and api_items.get("status") == 200:
        return ["SELECT missing FROM health_checks", "@app.get(\"/healthz\")", "def healthz():"]
    return ["cursor.execute(", "itemz", "details", "return []", "SELECT missing FROM health_checks", "K_ITEMS_QUERY"]


def _build_temporal_evidence(
    service_logs: dict[str, str],
    healthz: dict[str, Any],
    api_items: dict[str, Any],
    topology: dict[str, Any],
    file_snippets: dict[str, str],
    relevant_log_excerpts: dict[str, str],
) -> tuple[list[str], list[str]]:
    current_state_evidence: list[str] = []
    historical_evidence: list[str] = []
    api_nonempty = evaluate_api_items_nonempty(api_items)
    api_schema_ok = evaluate_api_items_schema_ok(api_items)
    port_contract = evaluate_port_contract_matches_baseline()
    topology_contract = evaluate_dc_topology_contract_ok(topology)
    no_degraded_mode = evaluate_dc_no_degraded_mode(topology)

    current_state_evidence.append(f"/healthz currently returns {healthz.get('status')}")
    current_state_evidence.append(f"/api/items currently returns {api_items.get('status')}")
    current_state_evidence.append(f"/api/topology currently returns {topology.get('status')}")

    nginx_excerpt = relevant_log_excerpts.get("nginx", "")
    app_excerpt = relevant_log_excerpts.get("app", "")
    app_env_snippet = file_snippets.get("app/app.env", "")
    baseline_app_port = get_baseline_app_port()
    if "APP_PORT=" in app_env_snippet:
        for line in app_env_snippet.splitlines():
            if line.startswith("APP_PORT="):
                current_app_port = line.split("=", 1)[1].strip()
                if baseline_app_port and current_app_port != baseline_app_port:
                    current_state_evidence.append(
                        f"visible app env snippet shows a non-baseline APP_PORT={current_app_port}"
                    )
    if "DB_PASSWORD=wrongpassword" in file_snippets.get("app/app.env", ""):
        current_state_evidence.append("visible app env snippet shows a non-baseline DB password")
    if "DB_HOST=" in app_env_snippet:
        for line in app_env_snippet.splitlines():
            if line.startswith("DB_HOST="):
                current_db_host = line.split("=", 1)[1].strip()
                if current_db_host not in ("db", ""):
                    current_state_evidence.append(
                        f"visible app env snippet shows a non-baseline DB_HOST={current_db_host}"
                    )
    for dependency_name in ["CACHE", "QUEUE", "METRICS"]:
        host_key = f"{dependency_name}_HOST"
        expected_host_key = f"{dependency_name}_EXPECTED_HOST"
        group_key = f"{dependency_name}_HOST_GROUP"
        expected_group_key = f"{dependency_name}_EXPECTED_GROUP"
        env_values: dict[str, str] = {}
        for line in app_env_snippet.splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key in {host_key, expected_host_key, group_key, expected_group_key}:
                env_values[key] = value.strip()
        if host_key in env_values and expected_host_key in env_values and env_values[host_key] != env_values[expected_host_key]:
            current_state_evidence.append(
                f"visible app env snippet shows {host_key}={env_values[host_key]} but expected {expected_host_key}={env_values[expected_host_key]}"
            )
        if group_key in env_values and expected_group_key in env_values and env_values[group_key] != env_values[expected_group_key]:
            current_state_evidence.append(
                f"visible app env snippet shows {group_key}={env_values[group_key]} but expected {expected_group_key}={env_values[expected_group_key]}"
            )
    if "DEGRADED_MODE=true" in app_env_snippet:
        current_state_evidence.append("visible app env snippet enables degraded mode")
    if "server app:8001" in file_snippets.get("nginx/nginx.conf", ""):
        current_state_evidence.append("visible nginx snippet shows an upstream port mismatch")
    if "server backend:8000" in file_snippets.get("nginx/nginx.conf", ""):
        current_state_evidence.append("visible nginx snippet shows an upstream host mismatch")
    if "K_ITEMS_QUERY" in file_snippets.get("app/main.py", ""):
        current_state_evidence.append("visible app code snippet references an indirect query constant")
    if (
        file_snippets.get("app/requirements.txt")
        and "uvicorn[standard]" not in file_snippets.get("app/requirements.txt", "")
    ):
        current_state_evidence.append("visible requirements snippet is missing uvicorn")
    if "itemz" in file_snippets.get("app/main.py", ""):
        current_state_evidence.append("visible app code snippet references a non-existent table name")
    if "details" in file_snippets.get("app/main.py", ""):
        current_state_evidence.append("visible app code snippet references a non-existent column name")
    if "return []" in file_snippets.get("app/main.py", ""):
        current_state_evidence.append("visible app code snippet swallows a query failure with an empty fallback response")
    if api_items.get("status") == 200 and not api_nonempty["ok"]:
        current_state_evidence.append("the items API currently returns HTTP 200 but an empty payload")
    if api_items.get("status") == 200 and not api_schema_ok["ok"]:
        current_state_evidence.append("the items API currently returns HTTP 200 but an invalid or degraded item schema")
    if not port_contract["ok"]:
        current_state_evidence.append("the current app/nginx port contract has drifted away from the baseline")
    if topology.get("status") == 200 and not topology_contract["ok"]:
        failed_checks = ", ".join(topology_contract.get("failed_checks", [])) or "unknown checks"
        current_state_evidence.append(f"the DC topology contract is degraded: {failed_checks}")
    if topology.get("status") == 200 and not no_degraded_mode["ok"]:
        current_state_evidence.append("the DC semantic check does not allow degraded mode")
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


def _collect_observation_snapshot() -> tuple[dict[str, str], dict, dict, dict, dict]:
    service_logs = collect_service_logs(["nginx", "app", "db", "cache", "queue", "worker", "metrics"], tail=50)
    compose_ps = docker_compose_ps()
    healthz = http_check("/healthz")
    api_items = http_check("/api/items")
    topology = http_check("/api/topology")
    return service_logs, compose_ps, healthz, api_items, topology


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
        "Can't connect",
        "Connection refused",
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
    topology: dict[str, Any],
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
            _app_env_needles(service_logs, healthz, api_items, topology),
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
                "Can't connect",
                "Connection refused",
                "Uvicorn running on http://0.0.0.0:",
            ],
        ),
    }


def _build_observation(
    service_logs: dict[str, str],
    compose_ps: dict[str, Any],
    healthz: dict[str, Any],
    api_items: dict[str, Any],
    topology: dict[str, Any],
) -> dict[str, Any]:
    file_snippets = _base_file_snippets(service_logs, healthz, api_items, topology)
    relevant_log_excerpts = _base_log_excerpts(service_logs)
    current_state_evidence, historical_evidence = _build_temporal_evidence(
        service_logs,
        healthz,
        api_items,
        topology,
        file_snippets,
        relevant_log_excerpts,
    )
    return {
        "compose_ps": compose_ps,
        "service_logs": service_logs,
        "health_checks": {
            "healthz": healthz,
            "api_items": api_items,
            "topology": topology,
        },
        "file_snippets": file_snippets,
        "relevant_log_excerpts": relevant_log_excerpts,
        "http_error_evidence": _http_error_evidence(healthz, api_items),
        "suspicious_patterns": _collect_suspicious_patterns(service_logs, healthz, api_items),
        "static_observations": _collect_static_observations(service_logs, file_snippets),
        "current_state_evidence": current_state_evidence,
        "historical_evidence": historical_evidence,
        "front_most_failure": classify_front_most_failure(
            healthz=healthz,
            api_items=api_items,
            topology=topology,
            service_logs=service_logs,
            file_snippets=file_snippets,
        ),
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
        "app/app.env": [
            "APP_PORT=",
            "DB_PASSWORD=",
            "DB_HOST=",
            "CACHE_HOST=",
            "CACHE_EXPECTED_HOST=",
            "QUEUE_HOST=",
            "QUEUE_EXPECTED_HOST=",
            "METRICS_HOST=",
            "METRICS_EXPECTED_HOST=",
            "DEGRADED_MODE=",
        ],
    }
    if path_value == "app/main.py" and _should_mask_app_main_query_snippet(service_logs, healthz, api_items):
        return _masked_app_main_snippet()
    return _extract_relevant_snippet(path_value, needle_map[path_value], context=3 if path_value == "app/main.py" else 1)


def _canonical_observation_requests(requested: list[str]) -> list[str]:
    canonical: list[str] = []
    for raw_request in requested:
        request = str(raw_request).strip()
        normalized = request.lower()
        if not request:
            continue
        if request in {
            "expand app log excerpt",
            "expand nginx log excerpt",
            "extract narrower relevant snippet from app/main.py",
            "extract narrower relevant snippet from app/app.env",
            "extract narrower relevant snippet from nginx/nginx.conf",
            "run nginx config test as observation",
        }:
            canonical.append(request)
            continue
        if "app/main.py" in normalized and any(
            marker in normalized
            for marker in [
                "inspect",
                "read",
                "open",
                "search",
                "locate",
                "snippet",
                "query",
                "sql",
                "itemz",
                "items",
                "table",
                "/api/items",
            ]
        ):
            canonical.append("extract narrower relevant snippet from app/main.py")
            continue
        if "app/app.env" in normalized and any(
            marker in normalized
            for marker in ["inspect", "read", "open", "search", "locate", "snippet", "db_", "password", "host", "cache", "queue"]
        ):
            canonical.append("extract narrower relevant snippet from app/app.env")
            continue
        if "nginx/nginx.conf" in normalized and any(
            marker in normalized
            for marker in ["inspect", "read", "open", "search", "locate", "snippet", "upstream", "proxy_pass"]
        ):
            canonical.append("extract narrower relevant snippet from nginx/nginx.conf")
            continue
        if "app log" in normalized or "app service log" in normalized or "traceback" in normalized:
            canonical.append("expand app log excerpt")
            continue
        if "nginx log" in normalized:
            canonical.append("expand nginx log excerpt")
            continue
        canonical.append(request)
    return list(dict.fromkeys(canonical))


def additional_observation_node(state: SingleAgentState) -> SingleAgentState:
    requested = _canonical_observation_requests(state.get("recommended_next_observations", []))
    collected: dict[str, Any] = {}
    count = state.get("additional_observation_count", 0) + 1
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
                "Can't connect",
                "Connection refused",
                "500 Internal Server Error",
                "Uvicorn running on http://0.0.0.0:",
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
        "count": count,
        "turn": state.get("planner_turn", 1),
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
        "additional_observation_count": count,
        "additional_observation_history": [
            *state.get("additional_observation_history", []),
            {
                "turn": state.get("planner_turn", 1),
                "count": count,
                "requested": requested,
                "collected": collected,
            },
        ],
    }


def sensor_node(state: SingleAgentState) -> SingleAgentState:
    service_logs, compose_ps, healthz, api_items, topology = _collect_observation_snapshot()
    attempts = 0
    while attempts < OBSERVATION_STABILIZATION_ATTEMPTS and _should_stabilize_observation(
        service_logs, healthz, api_items
    ):
        attempts += 1
        time.sleep(OBSERVATION_STABILIZATION_SECONDS)
        service_logs, compose_ps, healthz, api_items, topology = _collect_observation_snapshot()

    observation = _build_observation(service_logs, compose_ps, healthz, api_items, topology)
    observed_symptoms = _summarize_symptoms(service_logs, healthz, api_items, topology)

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
        "stage_progression": [
            *state.get("stage_progression", []),
            *(
                []
                if state.get("stage_progression", [])[-1:] == [observation.get("front_most_failure", "")]
                else [observation.get("front_most_failure", "")]
            ),
        ],
        "surfaced_failure_sequence": [
            *state.get("surfaced_failure_sequence", []),
            *(
                []
                if state.get("surfaced_failure_sequence", [])[-1:] == [observation.get("front_most_failure", "")]
                else [observation.get("front_most_failure", "")]
            ),
        ],
    }
