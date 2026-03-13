import urllib.error

from core.healthchecks import (
    classify_front_most_failure,
    evaluate_api_items_nonempty,
    evaluate_api_items_schema_ok,
    evaluate_port_contract_matches_baseline,
    http_check,
    run_fixed_command,
    service_running,
)


def test_service_running_handles_json_and_raw() -> None:
    assert service_running({"services": [{"Service": "app", "State": "running"}]}, "app") is True
    assert service_running({"services": [], "raw": {"stdout": "target-nginx   Up 10 seconds"}}, "nginx") is True
    assert service_running({"services": [], "raw": {"stdout": "target-app   Exited (1)"}}, "app") is False


def test_run_fixed_command_timeout() -> None:
    result = run_fixed_command(["python3", "-c", "import time; time.sleep(2)"], timeout_seconds=1)
    assert result["timed_out"] is True
    assert result["timeout_seconds"] == 1
    assert result["exception_class"] == "TimeoutExpired"


def test_http_check_connection_refused_is_classified(monkeypatch) -> None:
    def _raise(*args, **kwargs):
        raise urllib.error.URLError(ConnectionRefusedError("refused"))

    monkeypatch.setattr("urllib.request.urlopen", _raise)
    result = http_check("/healthz", timeout_seconds=1)
    assert result["ok"] is False
    assert result["error_type"] == "connection_refused"
    assert result["timed_out"] is False


def test_api_items_nonempty_passes_for_nonempty_payload() -> None:
    result = evaluate_api_items_nonempty(
        {
            "status": 200,
            "body": '{"items":[{"id":1,"name":"seed-item","description":"initial record"}]}',
        }
    )
    assert result["ok"] is True
    assert result["item_count"] == 1


def test_api_items_nonempty_fails_for_empty_payload() -> None:
    result = evaluate_api_items_nonempty({"status": 200, "body": "[]"})
    assert result["ok"] is False
    assert result["item_count"] == 0


def test_api_items_schema_ok_passes_for_healthy_schema() -> None:
    result = evaluate_api_items_schema_ok(
        {
            "status": 200,
            "body": '{"items":[{"id":1,"name":"seed-item","description":"initial record"}]}',
        }
    )
    assert result["ok"] is True
    assert result["missing_key_rows"] == []


def test_api_items_schema_ok_fails_for_missing_keys() -> None:
    result = evaluate_api_items_schema_ok(
        {
            "status": 200,
            "body": '{"items":[{"id":1,"name":"seed-item"}]}',
        }
    )
    assert result["ok"] is False
    assert result["missing_key_rows"][0]["missing_keys"] == ["description"]


def test_port_contract_matches_baseline_passes_for_healthy_contract(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.healthchecks.get_baseline_port_contract",
        lambda: {"app_port": "8000", "nginx_upstream_port": "8000"},
    )
    monkeypatch.setattr(
        "core.healthchecks.get_current_port_contract",
        lambda: {"app_port": "8000", "nginx_upstream_port": "8000"},
    )
    result = evaluate_port_contract_matches_baseline()
    assert result["ok"] is True


def test_port_contract_matches_baseline_fails_when_nginx_follows_drift(monkeypatch) -> None:
    monkeypatch.setattr(
        "core.healthchecks.get_baseline_port_contract",
        lambda: {"app_port": "8000", "nginx_upstream_port": "8000"},
    )
    monkeypatch.setattr(
        "core.healthchecks.get_current_port_contract",
        lambda: {"app_port": "9100", "nginx_upstream_port": "9100"},
    )
    result = evaluate_port_contract_matches_baseline()
    assert result["ok"] is False
    assert result["current"]["app_port"] == "9100"


def test_classify_front_most_failure_marks_semantic_green_hidden_red() -> None:
    front = classify_front_most_failure(
        healthz={"status": 200, "body": '{"status":"ok"}'},
        api_items={"status": 200, "body": "[]"},
        service_logs={"app": "", "nginx": ""},
        file_snippets={"app/main.py": "return []"},
    )
    assert front == "semantic_items_front"
