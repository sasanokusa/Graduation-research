import shutil
from pathlib import Path
from typing import Any

from core.actions import expand_execution_actions
from core.healthchecks import compose_config_check, nginx_config_test, run_fixed_command, run_named_health_check
from core.policies import RESULTS_DIR, get_base_file_for, resolve_repo_path


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


def execute_plan(plan: dict[str, Any], run_id: str) -> dict[str, Any]:
    expanded_actions, auto_appended_actions, expansion_errors = expand_execution_actions(
        plan.get("actions", [])
    )
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
            "rollback_used": False,
            "failed_action": None,
            "errors": expansion_errors,
        }

    action_results: list[dict[str, Any]] = []
    backups: dict[str, str] = {}
    backup_dir = RESULTS_DIR / "backups" / run_id
    backup_dir.mkdir(parents=True, exist_ok=True)
    rollback_used = False
    readiness_wait_requested = False

    for action in expanded_actions:
        action_type = action["type"]

        try:
            if action_type == "edit_file":
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
                    action_results.append({"action": action, "ok": True, "detail": "text replaced"})
                elif action["operation"] == "restore_from_base":
                    base_rel = get_base_file_for(target)
                    if not base_rel:
                        raise ValueError(f"no base file registered for {target}")
                    shutil.copy2(resolve_repo_path(base_rel), file_path)
                    action_results.append({"action": action, "ok": True, "detail": "restored from base"})
                else:
                    raise ValueError(f"unsupported edit operation: {action['operation']}")
            elif action_type == "restart_compose_service":
                command_result = run_fixed_command(
                    ["docker", "compose", "restart", action["service"]]
                )
                ok = command_result["returncode"] == 0
                action_results.append({"action": action, "ok": ok, "detail": command_result})
                if not ok:
                    raise RuntimeError("docker compose restart failed")
                if action["service"] in {"nginx", "app"}:
                    readiness_wait_requested = True
            elif action_type == "rebuild_compose_service":
                command_result = run_fixed_command(
                    ["docker", "compose", "up", "-d", "--force-recreate", action["service"]]
                )
                ok = command_result["returncode"] == 0
                action_results.append({"action": action, "ok": ok, "detail": command_result})
                if not ok:
                    raise RuntimeError("docker compose up --force-recreate failed")
                if action["service"] in {"nginx", "app"}:
                    readiness_wait_requested = True
            elif action_type == "run_config_test":
                if action["target"] == "compose":
                    command_result = compose_config_check()
                elif action["target"] == "nginx":
                    command_result = nginx_config_test()
                else:
                    raise ValueError(f"unsupported config test target: {action['target']}")
                ok = command_result["returncode"] == 0
                action_results.append({"action": action, "ok": ok, "detail": command_result})
                if not ok:
                    raise RuntimeError("config test failed")
            elif action_type == "run_health_check":
                check_result = run_named_health_check(action["check_name"])
                ok = bool(check_result.get("ok"))
                action_results.append({"action": action, "ok": ok, "detail": check_result})
                if not ok:
                    raise RuntimeError("health check action failed")
            elif action_type == "show_file":
                file_contents = resolve_repo_path(action["path"]).read_text()
                action_results.append(
                    {
                        "action": action,
                        "ok": True,
                        "detail": file_contents[:800],
                    }
                )
            else:
                raise ValueError(f"unsupported action type: {action_type}")
        except Exception as exc:
            rollback_result = rollback_files(backups) if backups else {"ok": True, "restored_files": [], "errors": []}
            rollback_used = bool(backups)
            action_results.append({"action": action, "ok": False, "detail": str(exc)})
            return {
                "ok": False,
                "input_actions": plan.get("actions", []),
                "auto_appended_actions": auto_appended_actions,
                "expanded_actions": expanded_actions,
                "action_results": action_results,
                "backups": backups,
                "backup_dir": str(backup_dir),
                "rollback_result": rollback_result,
                "rollback_used": rollback_used,
                "readiness_wait_requested": readiness_wait_requested,
                "failed_action": action,
                "errors": [],
            }

    return {
        "ok": True,
        "input_actions": plan.get("actions", []),
        "auto_appended_actions": auto_appended_actions,
        "expanded_actions": expanded_actions,
        "action_results": action_results,
        "backups": backups,
        "backup_dir": str(backup_dir),
        "rollback_result": {"ok": True, "restored_files": [], "errors": []},
        "rollback_used": rollback_used,
        "readiness_wait_requested": readiness_wait_requested,
        "failed_action": None,
        "errors": [],
    }
