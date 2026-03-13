import json
import os
import socket
import subprocess
import urllib.error
import urllib.request
from typing import Any

from core.policies import (
    API_ITEMS_REQUIRED_KEYS,
    ROOT_DIR,
    get_baseline_port_contract,
    get_current_port_contract,
)


DEFAULT_COMMAND_TIMEOUT_SECONDS = 20
DEFAULT_HTTP_TIMEOUT_SECONDS = 3


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return int(float(value))
    except ValueError:
        return default


def command_timeout_seconds() -> int:
    return _env_int("COMMAND_TIMEOUT_SECONDS", DEFAULT_COMMAND_TIMEOUT_SECONDS)


def http_timeout_seconds() -> int:
    return _env_int("HTTP_TIMEOUT_SECONDS", DEFAULT_HTTP_TIMEOUT_SECONDS)


def run_fixed_command(args: list[str], *, timeout_seconds: int | None = None) -> dict[str, Any]:
    effective_timeout = timeout_seconds or command_timeout_seconds()
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            cwd=ROOT_DIR,
            timeout=effective_timeout,
        )
        return {
            "command": args,
            "returncode": result.returncode,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "timed_out": False,
            "timeout_seconds": effective_timeout,
            "exception_class": "",
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "command": args,
            "returncode": None,
            "stdout": (exc.stdout or "").strip() if isinstance(exc.stdout, str) else "",
            "stderr": (exc.stderr or "").strip() if isinstance(exc.stderr, str) else "",
            "timed_out": True,
            "timeout_seconds": effective_timeout,
            "exception_class": exc.__class__.__name__,
        }
    except Exception as exc:
        return {
            "command": args,
            "returncode": None,
            "stdout": "",
            "stderr": str(exc),
            "timed_out": False,
            "timeout_seconds": effective_timeout,
            "exception_class": exc.__class__.__name__,
        }


def docker_compose_ps() -> dict[str, Any]:
    json_result = run_fixed_command(["docker", "compose", "ps", "--format", "json"])
    if json_result["returncode"] == 0 and json_result["stdout"]:
        try:
            parsed = json.loads(json_result["stdout"])
            return {"raw": json_result, "services": parsed if isinstance(parsed, list) else [parsed]}
        except json.JSONDecodeError:
            pass

    fallback = run_fixed_command(["docker", "compose", "ps"])
    return {"raw": fallback, "services": []}


def collect_service_logs(services: list[str], tail: int = 40) -> dict[str, str]:
    logs: dict[str, str] = {}
    for service in services:
        result = run_fixed_command(["docker", "compose", "logs", f"--tail={tail}", service])
        if result["returncode"] != 0:
            fallback = run_fixed_command(["docker", "logs", f"--tail={tail}", f"target-{service}"])
            logs[service] = "\n".join(line for line in [fallback["stdout"], fallback["stderr"]] if line)
        else:
            logs[service] = "\n".join(line for line in [result["stdout"], result["stderr"]] if line)
    return logs


def service_running(ps_snapshot: dict[str, Any], service_name: str) -> bool:
    services = ps_snapshot.get("services", [])
    for service in services:
        if service.get("Service") == service_name:
            state = str(service.get("State", "")).lower()
            return "running" in state

    raw_stdout = ps_snapshot.get("raw", {}).get("stdout", "")
    for line in raw_stdout.splitlines():
        if service_name in line and ("running" in line.lower() or "up" in line.lower()):
            return True
    return False


def _classify_http_exception(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, TimeoutError):
        return "timeout", exc.__class__.__name__
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        if isinstance(reason, TimeoutError):
            return "timeout", reason.__class__.__name__
        if isinstance(reason, ConnectionRefusedError):
            return "connection_refused", reason.__class__.__name__
        if isinstance(reason, socket.timeout):
            return "timeout", reason.__class__.__name__
        return "transport_error", reason.__class__.__name__ if hasattr(reason, "__class__") else exc.__class__.__name__
    return "transport_error", exc.__class__.__name__


def http_check(path: str, *, timeout_seconds: int | None = None) -> dict[str, Any]:
    effective_timeout = timeout_seconds or http_timeout_seconds()
    url = f"http://localhost:8080{path}"
    try:
        with urllib.request.urlopen(url, timeout=effective_timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            status = response.getcode()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        status = exc.code
        return {
            "url": url,
            "ok": False,
            "status": status,
            "body": body[:800],
            "error_type": "http_error",
            "timed_out": False,
            "timeout_seconds": effective_timeout,
            "exception_class": exc.__class__.__name__,
        }
    except Exception as exc:
        error_type, exception_class = _classify_http_exception(exc)
        return {
            "url": url,
            "ok": False,
            "status": None,
            "body": str(exc)[:800],
            "error_type": error_type,
            "timed_out": error_type == "timeout",
            "timeout_seconds": effective_timeout,
            "exception_class": exception_class,
        }

    return {
        "url": url,
        "ok": 200 <= status < 300,
        "status": status,
        "body": body[:800],
        "error_type": "none",
        "timed_out": False,
        "timeout_seconds": effective_timeout,
        "exception_class": "",
    }


def _parse_json_body(body: str) -> Any:
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return None


def extract_api_items_payload(api_items_result: dict[str, Any]) -> dict[str, Any]:
    parsed = _parse_json_body(str(api_items_result.get("body", "")))
    items: list[Any] | None = None
    shape = "unknown"

    if isinstance(parsed, list):
        items = parsed
        shape = "list"
    elif isinstance(parsed, dict) and isinstance(parsed.get("items"), list):
        items = parsed["items"]
        shape = "object.items"
    elif isinstance(parsed, dict):
        shape = "object"

    return {
        "parsed": parsed,
        "items": items,
        "shape": shape,
    }


def evaluate_api_items_nonempty(api_items_result: dict[str, Any]) -> dict[str, Any]:
    payload = extract_api_items_payload(api_items_result)
    items = payload["items"]
    item_count = len(items) if isinstance(items, list) else 0
    ok = api_items_result.get("status") == 200 and isinstance(items, list) and item_count >= 1
    return {
        "check_name": "api_items_nonempty",
        "ok": ok,
        "item_count": item_count,
        "response_shape": payload["shape"],
        "status": api_items_result.get("status"),
    }


def evaluate_api_items_schema_ok(api_items_result: dict[str, Any]) -> dict[str, Any]:
    payload = extract_api_items_payload(api_items_result)
    items = payload["items"]
    missing_key_rows: list[dict[str, Any]] = []
    ok = api_items_result.get("status") == 200 and isinstance(items, list) and len(items) >= 1

    if isinstance(items, list):
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                ok = False
                missing_key_rows.append({"index": index, "missing_keys": list(API_ITEMS_REQUIRED_KEYS)})
                continue
            missing_keys = [key for key in API_ITEMS_REQUIRED_KEYS if key not in item]
            if missing_keys:
                ok = False
                missing_key_rows.append({"index": index, "missing_keys": missing_keys})
    else:
        ok = False

    return {
        "check_name": "api_items_schema_ok",
        "ok": ok,
        "required_keys": list(API_ITEMS_REQUIRED_KEYS),
        "missing_key_rows": missing_key_rows,
        "response_shape": payload["shape"],
        "status": api_items_result.get("status"),
    }


def evaluate_port_contract_matches_baseline() -> dict[str, Any]:
    baseline = get_baseline_port_contract()
    current = get_current_port_contract()
    ok = (
        baseline.get("app_port")
        and baseline.get("nginx_upstream_port")
        and current.get("app_port") == baseline.get("app_port")
        and current.get("nginx_upstream_port") == baseline.get("nginx_upstream_port")
    )
    return {
        "check_name": "port_contract_matches_baseline",
        "ok": bool(ok),
        "baseline": baseline,
        "current": current,
    }


def classify_front_most_failure(
    *,
    healthz: dict[str, Any],
    api_items: dict[str, Any],
    service_logs: dict[str, str] | None = None,
    file_snippets: dict[str, str] | None = None,
) -> str:
    service_logs = service_logs or {}
    file_snippets = file_snippets or {}
    port_contract = evaluate_port_contract_matches_baseline()
    app_text = "\n".join(
        [
            service_logs.get("app", ""),
            str(healthz.get("body", "")),
            str(api_items.get("body", "")),
            str(file_snippets.get("app/main.py", "")),
            str(file_snippets.get("app/app.env", "")),
        ]
    )
    nginx_text = "\n".join(
        [
            service_logs.get("nginx", ""),
            str(file_snippets.get("nginx/nginx.conf", "")),
        ]
    )

    if (
        healthz.get("status") == 200
        and api_items.get("status") == 200
        and evaluate_api_items_nonempty(api_items)["ok"]
        and evaluate_api_items_schema_ok(api_items)["ok"]
        and not port_contract["ok"]
    ):
        return "contract_drift_front"
    if (
        healthz.get("status") == 200
        and api_items.get("status") == 200
        and evaluate_api_items_nonempty(api_items)["ok"]
        and evaluate_api_items_schema_ok(api_items)["ok"]
    ):
        return "recovered"
    if any(
        marker in app_text
        for marker in ["ModuleNotFoundError", "No module named", "uvicorn: not found", "Error loading ASGI app"]
    ):
        return "dependency_front"
    if any(marker in nginx_text for marker in ["host not found in upstream", "could not be resolved"]):
        return "upstream_host_front"
    if (
        healthz.get("status") in {502, 503, 504}
        or api_items.get("status") in {502, 503, 504}
        or any(marker in nginx_text for marker in ["connect() failed", "no live upstreams", "502 Bad Gateway"])
    ):
        return "upstream_port_or_connectivity_front"
    if any(marker in app_text for marker in ["Access denied", "using password: YES", "OperationalError"]):
        return "db_auth_front"
    if healthz.get("status") == 200 and api_items.get("status") == 200 and not evaluate_api_items_nonempty(api_items)["ok"]:
        return "semantic_items_front"
    if healthz.get("status") == 200 and api_items.get("status") == 200 and not evaluate_api_items_schema_ok(api_items)["ok"]:
        return "semantic_items_front"
    if any(marker in app_text for marker in ["itemz", "doesn't exist", "Table '"]):
        return "query_bug_front"
    if any(marker in app_text for marker in ["Unknown column", "details"]):
        return "schema_drift_front"
    if healthz.get("status") != 200 and api_items.get("status") == 200:
        return "healthcheck_front"
    if healthz.get("status") == 200 and api_items.get("status") != 200 and "internal error" in str(api_items.get("body", "")):
        return "opaque_api_front"
    return "unknown_front"


def run_named_health_check(check_name: str) -> dict[str, Any]:
    if check_name == "healthz_200":
        result = http_check("/healthz")
        result["ok"] = result.get("status") == 200
        return result
    if check_name == "api_items_200":
        result = http_check("/api/items")
        result["ok"] = result.get("status") == 200
        return result
    if check_name == "api_items_nonempty":
        result = http_check("/api/items")
        return {
            **result,
            **evaluate_api_items_nonempty(result),
        }
    if check_name == "api_items_schema_ok":
        result = http_check("/api/items")
        return {
            **result,
            **evaluate_api_items_schema_ok(result),
        }
    if check_name == "port_contract_matches_baseline":
        return evaluate_port_contract_matches_baseline()
    if check_name in {"app_running", "nginx_running", "db_running"}:
        service_name = check_name.removesuffix("_running")
        ps_snapshot = docker_compose_ps()
        return {
            "check_name": check_name,
            "ok": service_running(ps_snapshot, service_name),
            "compose_ps": ps_snapshot,
        }
    return {"url": check_name, "ok": False, "status": None, "body": "unsupported health check"}


def compose_config_check() -> dict[str, Any]:
    return run_fixed_command(["docker", "compose", "config"])


def nginx_config_test() -> dict[str, Any]:
    return run_fixed_command(["docker", "compose", "exec", "-T", "nginx", "nginx", "-t"])
