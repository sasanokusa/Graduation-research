from pathlib import Path

from core.executor import execute_plan, plan_rollback_actions, rollback_with_refresh


def test_plan_rollback_actions_selects_service_refreshes() -> None:
    actions = plan_rollback_actions(
        {
            "nginx/nginx.conf": "/tmp/nginx.conf.backup",
            "app/main.py": "/tmp/main.py.backup",
            "app/app.env": "/tmp/app.env.backup",
        }
    )
    assert {"type": "run_config_test", "target": "nginx"} in actions
    assert {"type": "restart_compose_service", "service": "nginx"} in actions
    assert {"type": "rebuild_compose_service", "service": "app"} in actions
    assert actions.count({"type": "rebuild_compose_service", "service": "app"}) == 1


def test_execute_plan_rejects_show_file() -> None:
    result = execute_plan(
        {
            "summary": "show file",
            "actions": [{"type": "show_file", "path": "app/main.py"}],
        },
        run_id="test_show_file",
    )
    assert result["ok"] is False
    assert any("show_file" in str(action_result["detail"]) for action_result in result["action_results"])


def test_rollback_with_refresh_restores_file_and_executes_refresh(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "main.py"
    backup = tmp_path / "main.py.backup"
    target.write_text("broken")
    backup.write_text("baseline")

    monkeypatch.setattr(
        "core.executor.resolve_repo_path",
        lambda path_value: target if path_value == "app/main.py" else Path(path_value),
    )
    monkeypatch.setattr(
        "core.executor._execute_actions",
        lambda actions, **kwargs: {
            "ok": True,
            "action_results": [{"action": action, "ok": True, "detail": "ok"} for action in actions],
            "failed_action": None,
            "readiness_wait_requested": True,
        },
    )

    result = rollback_with_refresh({"app/main.py": str(backup)}, run_id="test_rollback")
    assert result["ok"] is True
    assert target.read_text() == "baseline"
    assert result["rollback_actions"] == [{"type": "rebuild_compose_service", "service": "app"}]
    assert result["readiness_wait_requested"] is True
