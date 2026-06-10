from agents.sensor import (
    _collect_static_observations,
    _extract_db_declared_credentials,
    _has_db_auth_failure_markers,
)
from core.verifier import _validate_replace_text_evidence


def test_db_auth_markers_detect_access_denied_in_log_and_body() -> None:
    assert _has_db_auth_failure_markers({"app": "Access denied for user 'appuser'"}, {}, {})
    assert _has_db_auth_failure_markers({}, {"body": "error 1045"}, {})
    assert _has_db_auth_failure_markers({}, {}, {"body": "using password: YES"})
    assert not _has_db_auth_failure_markers({"app": "Connection refused"}, {"body": ""}, {"body": ""})


def test_declared_credentials_exclude_root_password() -> None:
    declared = _extract_db_declared_credentials()
    assert declared["MYSQL_USER"] == "appuser"
    assert declared["MYSQL_PASSWORD"] == "apppassword"
    assert "MYSQL_ROOT_PASSWORD" not in declared


def test_static_observations_expose_credentials_only_on_auth_failure() -> None:
    with_auth_failure = _collect_static_observations(
        {"app": "Access denied for user 'appuser'@'%' (using password: YES)"},
        {},
        {"status": 500, "body": ""},
        {"status": 500, "body": "Access denied"},
    )
    assert with_auth_failure["db_declared_client_credentials"]["MYSQL_PASSWORD"] == "apppassword"

    healthy = _collect_static_observations({"app": ""}, {}, {"status": 200}, {"status": 200})
    assert "db_declared_client_credentials" not in healthy


def _credential_edit(new_value: str) -> dict:
    return {
        "type": "edit_file",
        "path": "app/app.env",
        "operation": "replace_text",
        "old_text": "DB_PASSWORD=wrongpassword",
        "new_text": f"DB_PASSWORD={new_value}",
    }


def test_verifier_blocks_unobserved_credential_value() -> None:
    observation = {
        "file_snippets": {"app/app.env": "DB_PASSWORD=wrongpassword"},
        "static_observations": {},
        "current_state_evidence": ["database authentication failure observed"],
    }
    errors = _validate_replace_text_evidence(_credential_edit("apppassword"), observation)
    assert any("do not guess secrets" in error for error in errors)


def test_verifier_allows_credential_value_backed_by_observation() -> None:
    observation = {
        "file_snippets": {"app/app.env": "DB_PASSWORD=wrongpassword"},
        "static_observations": {
            "db_declared_client_credentials": {"MYSQL_USER": "appuser", "MYSQL_PASSWORD": "apppassword"}
        },
    }
    assert _validate_replace_text_evidence(_credential_edit("apppassword"), observation) == []


def test_verifier_ignores_non_credential_env_edits() -> None:
    observation = {"file_snippets": {"app/app.env": "APP_PORT=9000"}}
    action = {
        "type": "edit_file",
        "path": "app/app.env",
        "operation": "replace_text",
        "old_text": "APP_PORT=9000",
        "new_text": "APP_PORT=8000",
    }
    assert _validate_replace_text_evidence(action, observation) == []
