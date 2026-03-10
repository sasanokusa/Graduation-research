import difflib
import time
from typing import Any

from core.actions import expand_execution_actions
from core.healthchecks import collect_service_logs, compose_config_check, docker_compose_ps, http_check
from core.policies import (
    ALLOWED_EDIT_FILES,
    MAX_CHANGED_LINES,
    SUPPORTED_SUCCESS_CHECKS,
    get_base_file_for,
    resolve_repo_path,
)


def _count_changed_lines(before_text: str, after_text: str) -> int:
    diff = difflib.unified_diff(
        before_text.splitlines(),
        after_text.splitlines(),
        lineterm="",
    )
    changed = 0
    for line in diff:
        if line.startswith(("---", "+++")):
            continue
        if line.startswith(("+", "-")):
            changed += 1
    return changed


def _simulate_edit(action: dict[str, Any]) -> tuple[str, list[str]]:
    path = resolve_repo_path(action["path"])
    current = path.read_text()
    errors: list[str] = []

    if action["operation"] == "replace_text":
        old_text = action.get("old_text", "")
        new_text = action.get("new_text", "")
        occurrences = current.count(old_text)
        if occurrences != 1:
            errors.append(
                f"replace_text requires exactly one occurrence in {action['path']}, found {occurrences}"
            )
            return current, errors
        return current.replace(old_text, new_text, 1), errors

    if action["operation"] == "restore_from_base":
        base_rel = get_base_file_for(action["path"])
        if not base_rel:
            errors.append(f"no base file registered for {action['path']}")
            return current, errors
        base_path = resolve_repo_path(base_rel)
        return base_path.read_text(), errors

    errors.append(f"unsupported edit operation: {action['operation']}")
    return current, errors


def _validate_success_checks(success_checks: list[str]) -> tuple[list[str], list[str]]:
    validated: list[str] = []
    errors: list[str] = []
    for check_name in success_checks:
        if check_name not in SUPPORTED_SUCCESS_CHECKS:
            errors.append(f"unsupported scenario success check: {check_name}")
            continue
        validated.append(check_name)
    return validated, errors


def _evaluate_success_check(
    check_id: str,
    *,
    ps_snapshot: dict[str, Any],
    healthz: dict[str, Any],
    api_items: dict[str, Any],
) -> bool:
    if check_id == "healthz_200":
        return healthz.get("status") == 200
    if check_id == "api_items_200":
        return api_items.get("status") == 200
    if check_id == "app_running":
        return _service_running(ps_snapshot, "app")
    if check_id == "nginx_running":
        return _service_running(ps_snapshot, "nginx")
    if check_id == "db_running":
        return _service_running(ps_snapshot, "db")
    return False


def run_precheck(
    plan: dict[str, Any],
    scenario_definition: dict[str, Any],
    observation: dict[str, Any] | None = None,
    scope_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    action_validation_errors: list[str] = []
    scope_validation_errors: list[str] = []
    success_check_validation_errors: list[str] = []
    warnings: list[str] = []
    checks: dict[str, Any] = {}
    scope_policy = scope_policy or {}
    allowed_files = set(scope_policy.get("editable_files", scenario_definition.get("allowed_files", [])))
    allowed_actions = set(scope_policy.get("allowed_actions", scenario_definition.get("allowed_actions", [])))
    original_actions = plan.get("actions", [])
    actions, auto_appended_actions, auto_errors = expand_execution_actions(original_actions)
    action_validation_errors.extend(auto_errors)

    if not actions:
        action_validation_errors.append("planner returned no executable actions")

    config_result = compose_config_check()
    checks["compose_config"] = config_result
    if config_result["returncode"] != 0:
        action_validation_errors.append("docker compose config failed")

    validated_success_checks, success_check_validation_errors = _validate_success_checks(
        scenario_definition.get("success_checks", [])
    )

    for index, action in enumerate(actions):
        action_type = action["type"]
        if action_type not in allowed_actions and not action.get("auto_generated"):
            scope_validation_errors.append(
                f"action[{index}] is outside the triage scope for allowed actions: {action_type}"
            )
            continue
        if action_type == "edit_file":
            path = action["path"]
            if path not in allowed_files:
                scope_validation_errors.append(f"action[{index}] touches file outside the triage scope: {path}")
                continue
            if path not in ALLOWED_EDIT_FILES:
                action_validation_errors.append(
                    f"action[{index}] targets file outside the executor whitelist: {path}"
                )
                continue

            simulated_text, simulation_errors = _simulate_edit(action)
            action_validation_errors.extend(simulation_errors)
            if simulation_errors:
                continue

            current_text = resolve_repo_path(path).read_text()
            changed_lines = _count_changed_lines(current_text, simulated_text)
            checks[f"edit:{path}"] = {"changed_lines": changed_lines}
            if changed_lines > MAX_CHANGED_LINES:
                action_validation_errors.append(
                    f"action[{index}] changes too many lines in {path}: {changed_lines} > {MAX_CHANGED_LINES}"
                )
        elif action_type == "show_file":
            if action["path"] not in allowed_files:
                action_validation_errors.append(f"action[{index}] shows disallowed file: {action['path']}")
        elif action_type == "run_health_check":
            if not action.get("check_name"):
                action_validation_errors.append(f"action[{index}] is missing required field: check_name")

    observation = observation or {}
    nginx_snippet = observation.get("file_snippets", {}).get("nginx/nginx.conf", "")
    saw_nginx_edit = any(
        action.get("type") == "edit_file" and action.get("path") == "nginx/nginx.conf"
        for action in actions
    )
    saw_nginx_restart = any(
        action.get("type") == "restart_compose_service" and action.get("service") == "nginx"
        for action in actions
    )
    if scenario_definition.get("name") == "A" and "server app:8001;" in nginx_snippet and not saw_nginx_edit:
        action_validation_errors.append(
            "scenario A requires edit_file for nginx/nginx.conf when the snippet shows server app:8001;"
        )
    if scenario_definition.get("name") == "A" and saw_nginx_restart and not saw_nginx_edit:
        action_validation_errors.append(
            "scenario A does not allow restart_compose_service for nginx without a preceding edit_file"
        )

    combined_errors = action_validation_errors + scope_validation_errors + success_check_validation_errors

    return {
        "ok": not combined_errors,
        "errors": combined_errors,
        "warnings": warnings,
        "checks": checks,
        "validated_actions": actions,
        "validated_success_checks": validated_success_checks,
        "action_validation_errors": action_validation_errors,
        "scope_validation_errors": scope_validation_errors,
        "success_check_validation_errors": success_check_validation_errors,
        "validated_scope": {
            "editable_files": sorted(allowed_files),
            "allowed_actions": sorted(allowed_actions),
        },
        "normalized_input_actions": original_actions,
        "auto_appended_actions": auto_appended_actions,
        "precheck_input_actions": actions,
    }


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


def _collect_postcheck_snapshot(scenario_definition: dict[str, Any]) -> dict[str, Any]:
    ps_snapshot = docker_compose_ps()
    healthz = http_check("/healthz")
    api_items = http_check("/api/items")
    recent_logs = collect_service_logs(["nginx", "app", "db"], tail=20)

    suspicious_patterns = {
        "nginx": ["connect() failed", "502 Bad Gateway"],
        "app": ["ModuleNotFoundError", "Traceback", "database error"],
        "db": ["Access denied", "ERROR"],
    }
    suspicious_hits: dict[str, list[str]] = {}
    for service, patterns in suspicious_patterns.items():
        service_log = recent_logs.get(service, "")
        hits = [pattern for pattern in patterns if pattern in service_log]
        if hits:
            suspicious_hits[service] = hits

    validated_success_checks, success_check_validation_errors = _validate_success_checks(
        scenario_definition.get("success_checks", [])
    )
    evaluated_checks: dict[str, bool] = {}
    for check_id in validated_success_checks:
        evaluated_checks[check_id] = _evaluate_success_check(
            check_id,
            ps_snapshot=ps_snapshot,
            healthz=healthz,
            api_items=api_items,
        )

    ok = all(evaluated_checks.values()) if evaluated_checks and not success_check_validation_errors else False
    warnings: list[str] = []
    if suspicious_hits:
        warnings.append("suspicious patterns were still observed in recent logs")
    if success_check_validation_errors:
        warnings.append("scenario contains unsupported success checks")

    return {
        "ok": ok,
        "checks": evaluated_checks,
        "validated_success_checks": validated_success_checks,
        "success_check_validation_errors": success_check_validation_errors,
        "compose_ps": ps_snapshot,
        "healthz": healthz,
        "api_items": api_items,
        "recent_logs": recent_logs,
        "suspicious_hits": suspicious_hits,
        "warnings": warnings,
        "failure_conditions": scenario_definition.get("failure_conditions", []),
    }


def run_postcheck(
    scenario_definition: dict[str, Any],
    *,
    readiness_wait_used: bool = False,
    interval_seconds: int = 2,
    max_wait_seconds: int = 30,
) -> dict[str, Any]:
    start_time = time.time()
    attempts = 0
    first_success_time_seconds: float | None = None
    latest_snapshot: dict[str, Any] = {}

    while True:
        attempts += 1
        latest_snapshot = _collect_postcheck_snapshot(scenario_definition)
        if latest_snapshot["ok"]:
            first_success_time_seconds = round(time.time() - start_time, 3)
            break
        if not readiness_wait_used:
            break
        if time.time() - start_time >= max_wait_seconds:
            break
        time.sleep(interval_seconds)

    latest_snapshot["readiness_wait_used"] = readiness_wait_used
    latest_snapshot["readiness_attempts"] = attempts
    latest_snapshot["first_success_time_seconds"] = first_success_time_seconds
    return latest_snapshot
