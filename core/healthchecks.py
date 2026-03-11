import json
import os
import socket
import subprocess
import urllib.error
import urllib.request
from typing import Any

from core.policies import ROOT_DIR


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


def run_named_health_check(check_name: str) -> dict[str, Any]:
    if check_name == "healthz_200":
        result = http_check("/healthz")
        result["ok"] = result.get("status") == 200
        return result
    if check_name == "api_items_200":
        result = http_check("/api/items")
        result["ok"] = result.get("status") == 200
        return result
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
