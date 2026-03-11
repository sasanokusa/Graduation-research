import shutil
from pathlib import Path
from typing import Any

from core.actions import expand_execution_actions
from core.healthchecks import compose_config_check, nginx_config_test, run_fixed_command, run_named_health_check
from core.policies import RESULTS_DIR, get_base_file_for, resolve_repo_path, rollback_actions_for_paths


def _ensure_backup(path_value: str, backups: dict[str, str], backup_dir: Path) -> None:
    if path_value in backups:
        return
    source = resolve_repo_path(path_value)
    destination = backup_dir / path_value
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    backups[path_value] = str(destination)


def rollback_files(backups: dict[str, str]) -> dict[str, Any]:
    restored: list[str] = []
    errors: list[str] = []
    for target_rel, backup_path_str in backups.items():
        try:
            shutil.copy2(Path(backup_path_str), resolve_repo_path(target_rel))
            restored.append(target_rel)
        except Exception as exc:
            errors.append(f"{target_rel}: {exc}")
    return {"ok": not errors, "restored_files": restored, "errors": errors}


def _run_compose_refresh(service: str, *, rebuild: bool) -> dict[str, Any]:
    command = (
        ["docker", "compose", "up", "-d", "--force-recreate", service]
        if rebuild
        else ["docker", "compose", "restart", service]
    )
    return run_fixed_command(command)


def _execute_action(
    action: dict[str, Any],
    *,
    backups: dict[str, str] | None = None,
    backup_dir: Path | None = None,
) -> dict[str, Any]:
    action_type = action["type"]

    if action_type == "show_file":
        raise ValueError("show_file is not executable in the single-turn runner")

    if action_type == "edit_file":
        if backups is None or backup_dir is None:
            raise ValueError("edit_file execution requires backup tracking")
        target = action["path"]
        _ensure_backup(target, backups, backup_dir)
        file_path = resolve_repo_path(target)
        if action["operation"] == "replace_text":
            current = file_path.read_text()
            old_text = action.get("old_text", "")
            new_text = action.get("new_text", "")
            occurrences = current.count(old_text)
            if occurrences != 1:
                raise ValueError(
                    f"replace_text requires exactly one occurrence in {target}, found {occurrences}"
                )
            file_path.write_text(current.replace(old_text, new_text, 1))
            return {"action": action, "ok": True, "detail": "text replaced"}
        if action["operation"] == "restore_from_base":
            base_rel = get_base_file_for(target)
            if not base_rel:
                raise ValueError(f"no base file registered for {target}")
            shutil.copy2(resolve_repo_path(base_rel), file_path)
            return {"action": action, "ok": True, "detail": "restored from base"}
        raise ValueError(f"unsupported edit operation: {action['operation']}")

    if action_type == "restart_compose_service":
        command_result = _run_compose_refresh(action["service"], rebuild=False)
        ok = command_result["returncode"] == 0 and not command_result["timed_out"]
        return {"action": action, "ok": ok, "detail": command_result}

    if action_type == "rebuild_compose_service":
        command_result = _run_compose_refresh(action["service"], rebuild=True)
        ok = command_result["returncode"] == 0 and not command_result["timed_out"]
        return {"action": action, "ok": ok, "detail": command_result}

    if action_type == "run_config_test":
        if action["target"] == "compose":
            command_result = compose_config_check()
        elif action["target"] == "nginx":
            command_result = nginx_config_test()
        else:
            raise ValueError(f"unsupported config test target: {action['target']}")
        ok = command_result["returncode"] == 0 and not command_result["timed_out"]
        return {"action": action, "ok": ok, "detail": command_result}

    if action_type == "run_health_check":
        check_result = run_named_health_check(action["check_name"])
        return {"action": action, "ok": bool(check_result.get("ok")), "detail": check_result}

    raise ValueError(f"unsupported action type: {action_type}")


def _action_requests_readiness_wait(action: dict[str, Any]) -> bool:
    return action.get("type") in {"restart_compose_service", "rebuild_compose_service"} and action.get(
        "service"
    ) in {"nginx", "app"}


def _execute_actions(
    actions: list[dict[str, Any]],
    *,
    backups: dict[str, str] | None = None,
    backup_dir: Path | None = None,
) -> dict[str, Any]:
    action_results: list[dict[str, Any]] = []
    readiness_wait_requested = False
    for action in actions:
        try:
            action_result = _execute_action(action, backups=backups, backup_dir=backup_dir)
            action_results.append(action_result)
            if not action_result["ok"]:
                raise RuntimeError("action execution failed")
            if _action_requests_readiness_wait(action):
                readiness_wait_requested = True
        except Exception as exc:
            action_results.append({"action": action, "ok": False, "detail": str(exc)})
            return {
                "ok": False,
                "action_results": action_results,
                "failed_action": action,
                "readiness_wait_requested": readiness_wait_requested,
            }
    return {
        "ok": True,
        "action_results": action_results,
        "failed_action": None,
        "readiness_wait_requested": readiness_wait_requested,
    }


def plan_rollback_actions(backups: dict[str, str]) -> list[dict[str, str]]:
    restored_files = list(backups.keys())
    return rollback_actions_for_paths(restored_files)


def rollback_with_refresh(backups: dict[str, str], run_id: str) -> dict[str, Any]:
    rollback_result = rollback_files(backups)
    rollback_actions = plan_rollback_actions(backups) if rollback_result["ok"] else []
    refresh_result = _execute_actions(rollback_actions)
    return {
        "ok": rollback_result["ok"] and refresh_result["ok"],
        "restored_files": rollback_result.get("restored_files", []),
        "errors": rollback_result.get("errors", []),
        "rollback_actions": rollback_actions,
        "rollback_action_results": refresh_result["action_results"],
        "rollback_failed_action": refresh_result["failed_action"],
        "readiness_wait_requested": refresh_result["readiness_wait_requested"],
        "backup_dir": str(RESULTS_DIR / "backups" / run_id),
    }


def execute_plan(plan: dict[str, Any], run_id: str) -> dict[str, Any]:
    expanded_actions, auto_appended_actions, expansion_errors = expand_execution_actions(plan.get("actions", []))
    if expansion_errors:
        return {
            "ok": False,
            "input_actions": plan.get("actions", []),
            "auto_appended_actions": auto_appended_actions,
            "expanded_actions": expanded_actions,
            "action_results": [],
            "backups": {},
            "backup_dir": "",
            "rollback_result": {"ok": True, "restored_files": [], "errors": []},
            "rollback_actions": [],
            "rollback_action_results": [],
            "rollback_used": False,
            "failed_action": None,
            "errors": expansion_errors,
            "readiness_wait_requested": False,
        }

    backups: dict[str, str] = {}
    backup_dir = RESULTS_DIR / "backups" / run_id
    backup_dir.mkdir(parents=True, exist_ok=True)

    execution = _execute_actions(expanded_actions, backups=backups, backup_dir=backup_dir)
    if not execution["ok"]:
        rollback_result = (
            rollback_with_refresh(backups, run_id)
            if backups
            else {
                "ok": True,
                "restored_files": [],
                "errors": [],
                "rollback_actions": [],
                "rollback_action_results": [],
                "rollback_failed_action": None,
                "readiness_wait_requested": False,
                "backup_dir": str(backup_dir),
            }
        )
        return {
            "ok": False,
            "input_actions": plan.get("actions", []),
            "auto_appended_actions": auto_appended_actions,
            "expanded_actions": expanded_actions,
            "action_results": execution["action_results"],
            "backups": backups,
            "backup_dir": str(backup_dir),
            "rollback_result": rollback_result,
            "rollback_actions": rollback_result.get("rollback_actions", []),
            "rollback_action_results": rollback_result.get("rollback_action_results", []),
            "rollback_used": bool(backups),
            "readiness_wait_requested": execution["readiness_wait_requested"],
            "failed_action": execution["failed_action"],
            "errors": [],
        }

    return {
        "ok": True,
        "input_actions": plan.get("actions", []),
        "auto_appended_actions": auto_appended_actions,
        "expanded_actions": expanded_actions,
        "action_results": execution["action_results"],
        "backups": backups,
        "backup_dir": str(backup_dir),
        "rollback_result": {
            "ok": True,
            "restored_files": [],
            "errors": [],
            "rollback_actions": [],
            "rollback_action_results": [],
            "rollback_failed_action": None,
            "readiness_wait_requested": False,
            "backup_dir": str(backup_dir),
        },
        "rollback_actions": [],
        "rollback_action_results": [],
        "rollback_used": False,
        "readiness_wait_requested": execution["readiness_wait_requested"],
        "failed_action": None,
        "errors": [],
    }
