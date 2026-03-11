import json
import re
from typing import Any

from core.policies import (
    ALLOWED_ACTION_TYPES,
    ALLOWED_CONFIG_TEST_TARGETS,
    ALLOWED_HEALTH_CHECKS,
    ALLOWED_SERVICES,
    MAX_ACTIONS_PER_PLAN,
    normalize_repo_path,
)


def strip_fences(text: str) -> str:
    cleaned = text.strip()
    fence_match = re.match(r"^```(?:json)?\s*(.*?)```$", cleaned, flags=re.DOTALL)
    if fence_match:
        cleaned = fence_match.group(1).strip()
    return cleaned.strip("`").strip()


def normalize_action(
    action: dict[str, Any],
    *,
    index_label: str,
    forbidden_action_types: set[str] | None = None,
) -> tuple[dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    forbidden_action_types = forbidden_action_types or set()

    action_type = str(action.get("type", "")).strip()
    if not action_type:
        return None, [f"{index_label} is missing required field: type"]
    if action_type in forbidden_action_types:
        return None, [f"{index_label} uses forbidden action type in the single-turn runner: {action_type}"]
    if action_type not in ALLOWED_ACTION_TYPES:
        return None, [f"{index_label} has unsupported type: {action_type}"]

    normalized: dict[str, Any] = {"type": action_type}
    if "auto_generated" in action:
        normalized["auto_generated"] = bool(action.get("auto_generated"))
    if "reason" in action:
        normalized["reason"] = str(action.get("reason", ""))

    if action_type == "edit_file":
        path_value = str(action.get("path", "")).strip()
        operation_payload = action.get("operation", "")
        nested_operation = operation_payload if isinstance(operation_payload, dict) else {}
        operation = str(
            nested_operation.get("type", operation_payload) if nested_operation else operation_payload
        ).strip()
        if not path_value:
            errors.append(f"{index_label} is missing required field: path")
        else:
            normalized["path"] = normalize_repo_path(path_value)
        if not operation:
            errors.append(f"{index_label} is missing required field: operation")
        else:
            normalized["operation"] = operation

        if operation == "replace_text":
            if "old_text" not in action and "old_text" not in nested_operation:
                errors.append(f"{index_label} is missing required field: old_text")
            else:
                old_text = str(action.get("old_text", nested_operation.get("old_text", "")))
                if not old_text:
                    errors.append(f"{index_label} has empty required field: old_text")
                normalized["old_text"] = old_text
            if "new_text" not in action and "new_text" not in nested_operation:
                errors.append(f"{index_label} is missing required field: new_text")
            else:
                normalized["new_text"] = str(action.get("new_text", nested_operation.get("new_text", "")))
        elif operation == "restore_from_base":
            pass
        elif operation:
            errors.append(f"{index_label} has unsupported edit operation: {operation}")
    elif action_type in {"restart_compose_service", "rebuild_compose_service"}:
        service = str(action.get("service", action.get("service_name", ""))).strip()
        if not service:
            errors.append(f"{index_label} is missing required field: service")
        elif service not in ALLOWED_SERVICES:
            errors.append(f"{index_label} references unsupported service: {service}")
        normalized["service"] = service
    elif action_type == "run_config_test":
        target = str(
            action.get("target", action.get("service_name", action.get("service", "")))
        ).strip()
        if not target:
            errors.append(f"{index_label} is missing required field: target")
        elif target not in ALLOWED_CONFIG_TEST_TARGETS:
            errors.append(f"{index_label} references unsupported config test target: {target}")
        normalized["target"] = target
    elif action_type == "run_health_check":
        check_name = str(
            action.get("check_name", action.get("check", action.get("name", "")))
        ).strip()
        if not check_name:
            errors.append(f"{index_label} is missing required field: check_name")
        elif check_name not in ALLOWED_HEALTH_CHECKS:
            errors.append(f"{index_label} references unsupported health check: {check_name}")
        normalized["check_name"] = check_name
    elif action_type == "show_file":
        path_value = str(action.get("path", "")).strip()
        if not path_value:
            errors.append(f"{index_label} is missing required field: path")
        else:
            normalized["path"] = normalize_repo_path(path_value)

    if errors:
        return None, errors
    return normalized, []


def normalize_actions(
    actions: list[Any],
    *,
    prefix: str = "action",
    forbidden_action_types: set[str] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    normalized_actions: list[dict[str, Any]] = []
    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            errors.append(f"{prefix}[{index}] must be an object")
            continue
        normalized, action_errors = normalize_action(
            action,
            index_label=f"{prefix}[{index}]",
            forbidden_action_types=forbidden_action_types,
        )
        if action_errors:
            errors.extend(action_errors)
            continue
        if normalized:
            normalized_actions.append(normalized)

    if len(normalized_actions) > MAX_ACTIONS_PER_PLAN:
        errors.append(f"too many actions: {len(normalized_actions)} > {MAX_ACTIONS_PER_PLAN}")
    return normalized_actions, errors


def parse_plan_text(
    raw_text: str,
    *,
    forbidden_action_types: set[str] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    cleaned = strip_fences(raw_text)
    errors: list[str] = []

    try:
        json_match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        payload = json.loads(json_match.group(0) if json_match else cleaned)
    except Exception as exc:
        return empty_plan(), [f"failed to parse worker output as JSON: {exc}"]

    if not isinstance(payload, dict):
        return empty_plan(), ["worker output must be a JSON object"]

    summary = str(payload.get("summary", "")).strip()
    actions = payload.get("actions", [])
    if not isinstance(actions, list):
        errors.append("actions must be a JSON array")
        actions = []

    normalized_actions, normalization_errors = normalize_actions(
        actions,
        prefix="action",
        forbidden_action_types=forbidden_action_types,
    )
    errors.extend(normalization_errors)
    return {"summary": summary, "actions": normalized_actions}, errors


def empty_plan() -> dict[str, Any]:
    return {"summary": "", "actions": []}


def format_actions(actions: list[dict[str, Any]]) -> str:
    return json.dumps(actions, ensure_ascii=False, indent=2)


def action_uses_restore_from_base(action: dict[str, Any]) -> bool:
    return action.get("type") == "edit_file" and action.get("operation") == "restore_from_base"


def action_uses_minimal_patch(action: dict[str, Any]) -> bool:
    return action.get("type") == "edit_file" and action.get("operation") == "replace_text"


def plan_uses_restore_from_base(actions: list[dict[str, Any]], path_value: str | None = None) -> bool:
    for action in actions:
        if not action_uses_restore_from_base(action):
            continue
        if path_value is None or action.get("path") == path_value:
            return True
    return False


def plan_uses_minimal_patch(actions: list[dict[str, Any]], path_value: str | None = None) -> bool:
    for action in actions:
        if not action_uses_minimal_patch(action):
            continue
        if path_value is None or action.get("path") == path_value:
            return True
    return False


def _normalize_auto_action(raw_auto_action: dict[str, Any], *, index_label: str) -> tuple[dict[str, Any] | None, list[str]]:
    return normalize_action(raw_auto_action, index_label=index_label)


def _maybe_upgrade_app_restart(
    action: dict[str, Any],
    *,
    current_actions: list[dict[str, Any]],
    has_app_recreate_edit: bool,
    has_explicit_app_rebuild: bool,
    index: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str], bool]:
    if not (
        has_app_recreate_edit
        and action.get("type") == "restart_compose_service"
        and action.get("service") == "app"
        and not has_explicit_app_rebuild
    ):
        return [], [], [], False
    if any(
        candidate.get("type") == "rebuild_compose_service" and candidate.get("service") == "app"
        for candidate in current_actions
    ):
        return [], [], [], True
    raw_auto_action = {
        "type": "rebuild_compose_service",
        "service": "app",
        "auto_generated": True,
        "reason": "app startup-time file changes require recreate semantics; upgraded restart to rebuild",
    }
    normalized_auto_action, action_errors = _normalize_auto_action(
        raw_auto_action,
        index_label=f"auto_action[{index}]",
    )
    if action_errors:
        return [], [], action_errors, True
    if not normalized_auto_action:
        return [], [], [], True
    return [normalized_auto_action], [normalized_auto_action], [], True


def _maybe_append_nginx_config_test(
    action: dict[str, Any],
    *,
    has_explicit_nginx_test: bool,
    index: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    if not (
        action.get("type") == "edit_file"
        and action.get("path") == "nginx/nginx.conf"
        and not has_explicit_nginx_test
    ):
        return [], [], []
    raw_auto_action = {
        "type": "run_config_test",
        "target": "nginx",
        "auto_generated": True,
        "reason": "validate nginx syntax immediately after nginx.conf edit",
    }
    normalized_auto_action, action_errors = _normalize_auto_action(
        raw_auto_action,
        index_label=f"auto_action[{index}]",
    )
    if action_errors:
        return [], [], action_errors
    if not normalized_auto_action:
        return [], [], []
    return [normalized_auto_action], [normalized_auto_action], []


def _maybe_append_app_rebuild(
    action: dict[str, Any],
    *,
    current_actions: list[dict[str, Any]],
    has_explicit_app_rebuild: bool,
    app_recreate_edit_paths: set[str],
    index: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    if not (
        action.get("type") == "edit_file"
        and action.get("path") in app_recreate_edit_paths
        and not has_explicit_app_rebuild
        and not any(
            candidate.get("type") == "rebuild_compose_service" and candidate.get("service") == "app"
            for candidate in current_actions
        )
    ):
        return [], [], []
    raw_auto_action = {
        "type": "rebuild_compose_service",
        "service": "app",
        "auto_generated": True,
        "reason": "app code/env/dependency changes require app recreate to take effect",
    }
    normalized_auto_action, action_errors = _normalize_auto_action(
        raw_auto_action,
        index_label=f"auto_action[{index}]",
    )
    if action_errors:
        return [], [], action_errors
    if not normalized_auto_action:
        return [], [], []
    return [normalized_auto_action], [normalized_auto_action], []


def expand_execution_actions(
    normalized_actions: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    expanded_actions: list[dict[str, Any]] = []
    auto_appended_actions: list[dict[str, Any]] = []
    errors: list[str] = []
    app_recreate_edit_paths = {"app/app.env", "app/main.py", "app/requirements.txt"}
    has_explicit_nginx_test = any(
        action.get("type") == "run_config_test" and action.get("target") == "nginx"
        for action in normalized_actions
    )
    has_app_recreate_edit = any(
        action.get("type") == "edit_file" and action.get("path") in app_recreate_edit_paths
        for action in normalized_actions
    )
    has_explicit_app_rebuild = any(
        action.get("type") == "rebuild_compose_service" and action.get("service") == "app"
        for action in normalized_actions
    )

    for index, action in enumerate(normalized_actions):
        upgraded_actions, upgraded_auto_actions, upgrade_errors, was_upgraded = _maybe_upgrade_app_restart(
            action,
            current_actions=expanded_actions,
            has_app_recreate_edit=has_app_recreate_edit,
            has_explicit_app_rebuild=has_explicit_app_rebuild,
            index=index,
        )
        if upgrade_errors:
            errors.extend(upgrade_errors)
            continue
        if was_upgraded:
            expanded_actions.extend(upgraded_actions)
            auto_appended_actions.extend(upgraded_auto_actions)
            continue

        expanded_actions.append(action)
        nginx_actions, nginx_auto_actions, nginx_errors = _maybe_append_nginx_config_test(
            action,
            has_explicit_nginx_test=has_explicit_nginx_test,
            index=index,
        )
        if nginx_errors:
            errors.extend(nginx_errors)
            continue
        expanded_actions.extend(nginx_actions)
        auto_appended_actions.extend(nginx_auto_actions)

        rebuild_actions, rebuild_auto_actions, rebuild_errors = _maybe_append_app_rebuild(
            action,
            current_actions=expanded_actions,
            has_explicit_app_rebuild=has_explicit_app_rebuild,
            app_recreate_edit_paths=app_recreate_edit_paths,
            index=index,
        )
        if rebuild_errors:
            errors.extend(rebuild_errors)
            continue
        expanded_actions.extend(rebuild_actions)
        auto_appended_actions.extend(rebuild_auto_actions)

    return expanded_actions, auto_appended_actions, errors
