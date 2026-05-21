from pathlib import Path

import yaml

from core.verifier import run_precheck


def test_precheck_replace_text_requires_single_occurrence(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "main.py"
    target.write_text('cursor.execute("SELECT 1")\ncursor.execute("SELECT 1")\n')

    monkeypatch.setattr("core.verifier.compose_config_check", lambda: {"returncode": 0, "stdout": "", "stderr": ""})
    monkeypatch.setattr(
        "core.verifier.resolve_repo_path",
        lambda path_value: target if path_value == "app/main.py" else Path(path_value),
    )

    result = run_precheck(
        {
            "summary": "test",
            "actions": [
                {
                    "type": "edit_file",
                    "path": "app/main.py",
                    "operation": "replace_text",
                    "old_text": 'cursor.execute("SELECT 1")',
                    "new_text": 'cursor.execute("SELECT 2")',
                }
            ],
        },
        {"allowed_files": ["app/main.py"], "allowed_actions": ["edit_file"], "success_checks": []},
        scope_policy={"files": ["app/main.py"], "services": [], "allowed_actions": ["edit_file"]},
    )
    assert result["ok"] is False
    assert any("exactly one occurrence" in error for error in result["action_validation_errors"])


def test_precheck_rejects_broad_single_token_code_replacement(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "main.py"
    target.write_text('cursor.execute("SELECT id, name FROM itemz ORDER BY id")\n')

    monkeypatch.setattr("core.verifier.compose_config_check", lambda: {"returncode": 0, "stdout": "", "stderr": ""})
    monkeypatch.setattr(
        "core.verifier.resolve_repo_path",
        lambda path_value: target if path_value == "app/main.py" else Path(path_value),
    )

    result = run_precheck(
        {
            "summary": "test",
            "actions": [
                {
                    "type": "edit_file",
                    "path": "app/main.py",
                    "operation": "replace_text",
                    "old_text": "itemz",
                    "new_text": "items",
                }
            ],
        },
        {"allowed_files": ["app/main.py"], "allowed_actions": ["edit_file"], "success_checks": []},
        observation={"file_snippets": {"app/main.py": 'cursor.execute("SELECT id, name FROM itemz ORDER BY id")'}},
        scope_policy={"files": ["app/main.py"], "services": [], "allowed_actions": ["edit_file"]},
    )
    assert result["ok"] is False
    assert any("single-token code replacements" in error for error in result["action_validation_errors"])


def test_precheck_accepts_contextual_code_replacement_from_visible_snippet(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "main.py"
    target.write_text('cursor.execute("SELECT id, name FROM itemz ORDER BY id")\n')
    old_text = "FROM itemz ORDER BY id"

    monkeypatch.setattr("core.verifier.compose_config_check", lambda: {"returncode": 0, "stdout": "", "stderr": ""})
    monkeypatch.setattr(
        "core.verifier.resolve_repo_path",
        lambda path_value: target if path_value == "app/main.py" else Path(path_value),
    )

    result = run_precheck(
        {
            "summary": "test",
            "actions": [
                {
                    "type": "edit_file",
                    "path": "app/main.py",
                    "operation": "replace_text",
                    "old_text": old_text,
                    "new_text": "FROM items ORDER BY id",
                }
            ],
        },
        {"allowed_files": ["app/main.py"], "allowed_actions": ["edit_file"], "success_checks": []},
        observation={"file_snippets": {"app/main.py": 'cursor.execute("SELECT id, name FROM itemz ORDER BY id")'}},
        scope_policy={"files": ["app/main.py"], "services": [], "allowed_actions": ["edit_file"]},
    )
    assert result["ok"] is True


def test_precheck_requires_replace_text_to_be_visible_in_observed_snippet(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "main.py"
    target.write_text('cursor.execute("SELECT id, name FROM itemz ORDER BY id")\n')

    monkeypatch.setattr("core.verifier.compose_config_check", lambda: {"returncode": 0, "stdout": "", "stderr": ""})
    monkeypatch.setattr(
        "core.verifier.resolve_repo_path",
        lambda path_value: target if path_value == "app/main.py" else Path(path_value),
    )

    result = run_precheck(
        {
            "summary": "test",
            "actions": [
                {
                    "type": "edit_file",
                    "path": "app/main.py",
                    "operation": "replace_text",
                    "old_text": "FROM itemz ORDER BY id",
                    "new_text": "FROM items ORDER BY id",
                }
            ],
        },
        {"allowed_files": ["app/main.py"], "allowed_actions": ["edit_file"], "success_checks": []},
        observation={"file_snippets": {"app/main.py": '@app.get("/api/items")\n...\ndef list_items():'}},
        scope_policy={"files": ["app/main.py"], "services": [], "allowed_actions": ["edit_file"]},
    )
    assert result["ok"] is False
    assert any("not present in the current observed file snippet" in error for error in result["action_validation_errors"])


def test_precheck_rejects_show_file(monkeypatch) -> None:
    monkeypatch.setattr("core.verifier.compose_config_check", lambda: {"returncode": 0, "stdout": "", "stderr": ""})
    result = run_precheck(
        {
            "summary": "test",
            "actions": [
                {
                    "type": "show_file",
                    "path": "app/main.py",
                }
            ],
        },
        {"allowed_files": ["app/main.py"], "allowed_actions": ["show_file"], "success_checks": []},
        scope_policy={"files": ["app/main.py"], "services": [], "allowed_actions": ["show_file"]},
    )
    assert result["ok"] is False
    assert any("show_file" in error for error in result["action_validation_errors"])


def test_precheck_blocks_initial_code_restore_for_hard_scenario(monkeypatch) -> None:
    monkeypatch.setattr("core.verifier.compose_config_check", lambda: {"returncode": 0, "stdout": "", "stderr": ""})
    definitions = yaml.safe_load(Path("scenarios/definitions.yaml").read_text())["scenarios"]
    result = run_precheck(
        {
            "summary": "unsafe restore",
            "actions": [
                {"type": "edit_file", "path": "app/main.py", "operation": "restore_from_base"},
                {"type": "rebuild_compose_service", "service": "app"},
            ],
        },
        definitions["i2"],
        internal_scenario_definition=definitions["i2"],
        scope_policy={
            "files": ["app/main.py", "app/app.env", "nginx/nginx.conf"],
            "services": ["app", "nginx"],
            "allowed_actions": ["edit_file", "rebuild_compose_service", "restart_compose_service", "run_config_test"],
        },
    )
    assert result["ok"] is False
    assert result["restore_from_base_blocked"] is True
    assert "forbidden" in result["restore_from_base_block_reason"]


def test_precheck_blocks_restore_from_base_for_env_by_default(monkeypatch) -> None:
    monkeypatch.delenv("RESTORE_FROM_BASE_MODE", raising=False)
    monkeypatch.setattr("core.verifier.compose_config_check", lambda: {"returncode": 0, "stdout": "", "stderr": ""})

    result = run_precheck(
        {
            "summary": "unsafe restore",
            "actions": [
                {"type": "edit_file", "path": "app/app.env", "operation": "restore_from_base"},
                {"type": "rebuild_compose_service", "service": "app"},
            ],
        },
        {"allowed_files": ["app/app.env"], "allowed_actions": ["edit_file", "rebuild_compose_service"], "success_checks": []},
        scope_policy={
            "files": ["app/app.env"],
            "services": ["app"],
            "allowed_actions": ["edit_file", "rebuild_compose_service"],
        },
    )

    assert result["ok"] is False
    assert result["restore_from_base_blocked"] is True
    assert "forbidden" in result["restore_from_base_block_reason"]
