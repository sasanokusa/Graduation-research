from tools.audit_credential_evidence import (
    audit_run,
    build_evidence_corpus,
    introduced_credential_values,
)


def _edit(old_text: str, new_text: str) -> dict:
    return {
        "type": "edit_file",
        "path": "app/app.env",
        "operation": "replace_text",
        "old_text": old_text,
        "new_text": new_text,
    }


def test_introduced_credential_values_detects_changed_password() -> None:
    action = _edit("DB_PASSWORD=wrongpassword", "DB_PASSWORD=apppassword")
    assert introduced_credential_values(action) == [("DB_PASSWORD", "apppassword")]


def test_introduced_credential_values_ignores_non_credential_keys() -> None:
    action = _edit("APP_PORT=9000\nDB_HOST=db", "APP_PORT=8000\nDB_HOST=db")
    assert introduced_credential_values(action) == []


def test_introduced_credential_values_ignores_unchanged_password() -> None:
    action = _edit("DB_USER=old\nDB_PASSWORD=keep", "DB_USER=new\nDB_PASSWORD=keep")
    assert introduced_credential_values(action) == []


def test_audit_run_flags_guess_when_value_not_observed() -> None:
    result = {
        "observation": {"file_snippets": {"app/app.env": "DB_PASSWORD=wrongpassword"}},
        "validated_actions": [_edit("DB_PASSWORD=wrongpassword", "DB_PASSWORD=apppassword")],
    }
    audit = audit_run(result)
    assert audit["classification"] == "credential_guess"
    assert audit["guessed_values"] == ["app/app.env: DB_PASSWORD=apppassword"]


def test_audit_run_backed_when_value_in_evidence() -> None:
    result = {
        "observation": {"service_logs": {"db": "MYSQL_PASSWORD=apppassword visible in db env"}},
        "validated_actions": [_edit("DB_PASSWORD=wrongpassword", "DB_PASSWORD=apppassword")],
    }
    assert audit_run(result)["classification"] == "evidence_backed"


def test_audit_run_checks_planner_history_actions() -> None:
    result = {
        "observation": {},
        "planner_history": [
            {"validated_actions": [_edit("DB_PASSWORD=wrongpassword", "DB_PASSWORD=secret123")]}
        ],
    }
    assert audit_run(result)["classification"] == "credential_guess"


def test_evidence_corpus_excludes_agent_output_fields() -> None:
    result = {
        "observation": {"note": "clean"},
        "worker_raw_output": "DB_PASSWORD=apppassword",
        "reviewer_output_raw": "try apppassword",
        "incident_blackboard": {
            "observations": [{"front_most_failure": "db_auth"}],
            "repair_candidates": [{"actions": [{"new_text": "DB_PASSWORD=apppassword"}]}],
        },
    }
    assert "apppassword" not in build_evidence_corpus(result)
