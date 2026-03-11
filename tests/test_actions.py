from core.actions import expand_execution_actions, normalize_action, normalize_actions


def test_normalize_action_accepts_service_name_alias() -> None:
    action, errors = normalize_action(
        {"type": "restart_compose_service", "service_name": "app"},
        index_label="action[0]",
    )
    assert errors == []
    assert action == {"type": "restart_compose_service", "service": "app"}


def test_normalize_actions_rejects_forbidden_show_file() -> None:
    actions, errors = normalize_actions(
        [{"type": "show_file", "path": "app/main.py"}],
        forbidden_action_types={"show_file"},
    )
    assert actions == []
    assert "forbidden action type" in errors[0]


def test_expand_execution_actions_adds_nginx_test_and_app_rebuild() -> None:
    actions, auto_actions, errors = expand_execution_actions(
        [
            {
                "type": "edit_file",
                "path": "nginx/nginx.conf",
                "operation": "replace_text",
                "old_text": "server app:8001 resolve;",
                "new_text": "server app:8000 resolve;",
            },
            {
                "type": "edit_file",
                "path": "app/main.py",
                "operation": "replace_text",
                "old_text": "FROM itemz ORDER BY id",
                "new_text": "FROM items ORDER BY id",
            },
        ]
    )
    assert errors == []
    assert any(action["type"] == "run_config_test" and action["target"] == "nginx" for action in actions)
    assert any(action["type"] == "rebuild_compose_service" and action["service"] == "app" for action in actions)
    assert len(auto_actions) == 2


def test_expand_execution_actions_upgrades_app_restart_to_rebuild() -> None:
    actions, auto_actions, errors = expand_execution_actions(
        [
            {
                "type": "edit_file",
                "path": "app/app.env",
                "operation": "replace_text",
                "old_text": "APP_PORT=9000",
                "new_text": "APP_PORT=8000",
            },
            {"type": "restart_compose_service", "service": "app"},
        ]
    )
    assert errors == []
    assert not any(action["type"] == "restart_compose_service" and action["service"] == "app" for action in actions)
    assert any(action["type"] == "rebuild_compose_service" and action["service"] == "app" for action in actions)
    assert any(action["type"] == "rebuild_compose_service" for action in auto_actions)
