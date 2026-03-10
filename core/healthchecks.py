import json
import subprocess
import urllib.error
import urllib.request
from typing import Any

from core.policies import ROOT_DIR


def run_fixed_command(args: list[str]) -> dict[str, Any]:
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        cwd=ROOT_DIR,
    )
    return {
        "command": args,
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
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
            logs[service] = "\n".join(
                line for line in [fallback["stdout"], fallback["stderr"]] if line
            )
        else:
            logs[service] = "\n".join(
                line for line in [result["stdout"], result["stderr"]] if line
            )
    return logs


def _service_running(ps_snapshot: dict[str, Any], service_name: str) -> bool:
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


def http_check(path: str) -> dict[str, Any]:
    url = f"http://localhost:8080{path}"
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            body = response.read().decode("utf-8", errors="replace")
            status = response.getcode()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        status = exc.code
    except Exception as exc:
        return {"url": url, "ok": False, "status": None, "body": str(exc)}

    return {
        "url": url,
        "ok": 200 <= status < 300,
        "status": status,
        "body": body[:800],
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
            "ok": _service_running(ps_snapshot, service_name),
            "compose_ps": ps_snapshot,
        }
    return {"url": check_name, "ok": False, "status": None, "body": "unsupported health check"}


def compose_config_check() -> dict[str, Any]:
    return run_fixed_command(["docker", "compose", "config"])


def nginx_config_test() -> dict[str, Any]:
    return run_fixed_command(["docker", "compose", "exec", "-T", "nginx", "nginx", "-t"])
