import difflib
import os
import time
from typing import Any

from core.actions import (
    action_uses_minimal_patch,
    action_uses_restore_from_base,
    expand_execution_actions,
)
from core.healthchecks import (
    collect_service_logs,
    compose_config_check,
    docker_compose_ps,
    http_check,
    service_running,
)
from core.policies import (
    ALLOWED_EDIT_FILES,
    MAX_CHANGED_LINES,
    SUPPORTED_SUCCESS_CHECKS,
    get_base_file_for,
    get_restore_policy,
    is_code_file,
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


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return int(float(value))
    except ValueError:
        return default


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
        return service_running(ps_snapshot, "app")
    if check_id == "nginx_running":
        return service_running(ps_snapshot, "nginx")
    if check_id == "db_running":
        return service_running(ps_snapshot, "db")
    return False


def run_precheck(
    plan: dict[str, Any],
    scenario_definition: dict[str, Any],
    internal_scenario_definition: dict[str, Any] | None = None,
    observation: dict[str, Any] | None = None,
    scope_policy: dict[str, Any] | None = None,
    planner_error_type: str = "none",
) -> dict[str, Any]:
    action_validation_errors: list[str] = []
    scope_validation_errors: list[str] = []
    success_check_validation_errors: list[str] = []
    warnings: list[str] = []
    checks: dict[str, Any] = {}
    restore_from_base_blocked = False
    restore_from_base_block_reason = ""
    blocked_actions_reason: list[str] = []
    scope_policy = scope_policy or {}
    policy_definition = internal_scenario_definition or scenario_definition
    allowed_files = set(scope_policy.get("files", scope_policy.get("editable_files", scenario_definition.get("allowed_files", []))))
    allowed_services = set(scope_policy.get("services", []))
    allowed_actions = set(scope_policy.get("allowed_actions", scenario_definition.get("allowed_actions", [])))
    original_actions = plan.get("actions", [])
    actions, auto_appended_actions, auto_errors = expand_execution_actions(original_actions)
    action_validation_errors.extend(auto_errors)

    if not actions and planner_error_type in {
        "api_key_missing",
        "planner_timeout",
        "planner_transport_error",
        "planner_invocation_error",
    }:
        action_validation_errors.append(
            f"planner invocation failed before executable actions were produced: {planner_error_type}"
        )
    elif not actions and planner_error_type == "planner_parse_error":
        action_validation_errors.append("planner output could not be normalized into executable actions")
    elif not actions:
        action_validation_errors.append("planner returned no executable actions")

    config_result = compose_config_check()
    checks["compose_config"] = config_result
    if config_result["returncode"] != 0:
        action_validation_errors.append("docker compose config failed")

    validated_success_checks, success_check_validation_errors = _validate_success_checks(
        scenario_definition.get("success_checks", [])
    )
    restore_policy = get_restore_policy(policy_definition)
    disallow_initial_restore_for = set(restore_policy.get("disallow_initial_restore_for", []))
    allow_restore_only_after_failed_patch_for = set(
        restore_policy.get("allow_restore_only_after_failed_patch_for", [])
    )
    restore_from_base_used = any(action_uses_restore_from_base(action) for action in actions)
    minimal_patch_used = any(action_uses_minimal_patch(action) for action in actions)

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
            if (
                action.get("operation") == "restore_from_base"
                and path in disallow_initial_restore_for
                and path in allow_restore_only_after_failed_patch_for
                and is_code_file(path)
            ):
                restore_from_base_blocked = True
                restore_from_base_block_reason = (
                    f"restore_from_base for {path} is reserved as a last resort in this hard scenario; "
                    "initial single-turn code restores are blocked until a narrower patch attempt has failed"
                )
                action_validation_errors.append(
                    f"action[{index}] restore_from_base for {path} is blocked by restore policy"
                )
                blocked_actions_reason.append(restore_from_base_block_reason)
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
        elif action_type in {"restart_compose_service", "rebuild_compose_service"}:
            service = action.get("service", "")
            if allowed_services and service not in allowed_services and not action.get("auto_generated"):
                scope_validation_errors.append(
                    f"action[{index}] targets service outside the triage scope: {service}"
                )
        elif action_type == "show_file":
            action_validation_errors.append(
                f"action[{index}] uses show_file, which is not executable in the single-turn runner"
            )
        elif action_type == "run_health_check":
            if not action.get("check_name"):
                action_validation_errors.append(f"action[{index}] is missing required field: check_name")
        elif action_type == "run_config_test":
            target = action.get("target", "")
            if target == "nginx" and allowed_services and "nginx" not in allowed_services and not action.get("auto_generated"):
                scope_validation_errors.append(
                    f"action[{index}] targets config test outside the triage scope: {target}"
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
            "files": sorted(allowed_files),
            "editable_files": sorted(allowed_files),
            "services": sorted(allowed_services),
            "allowed_actions": sorted(allowed_actions),
        },
        "restore_from_base_used": restore_from_base_used,
        "restore_from_base_blocked": restore_from_base_blocked,
        "restore_from_base_block_reason": restore_from_base_block_reason,
        "minimal_patch_used": minimal_patch_used,
        "blocked_actions_reason": blocked_actions_reason,
        "planner_error_type": planner_error_type,
        "normalized_input_actions": original_actions,
        "auto_appended_actions": auto_appended_actions,
        "precheck_input_actions": actions,
    }

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
    interval_seconds: int | None = None,
    max_wait_seconds: int | None = None,
) -> dict[str, Any]:
    retry_interval_seconds = interval_seconds or _env_int("POSTCHECK_RETRY_INTERVAL_SECONDS", 2)
    retry_attempts = _env_int("POSTCHECK_RETRY_ATTEMPTS", 15)
    retry_window_enabled = bool(readiness_wait_used)
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
        if not retry_window_enabled:
            break
        if attempts >= retry_attempts:
            break
        if max_wait_seconds is not None and time.time() - start_time >= max_wait_seconds:
            break
        time.sleep(retry_interval_seconds)

    latest_snapshot["readiness_wait_used"] = readiness_wait_used
    latest_snapshot["readiness_attempts"] = attempts
    latest_snapshot["first_success_time_seconds"] = first_success_time_seconds
    latest_snapshot["postcheck_used_retry_window"] = retry_window_enabled
    latest_snapshot["postcheck_retry_attempts"] = attempts
    latest_snapshot["postcheck_first_success_time_seconds"] = first_success_time_seconds
    latest_snapshot["postcheck_retry_interval_seconds"] = retry_interval_seconds
    return latest_snapshot
