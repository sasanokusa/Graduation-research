import urllib.error

from core.healthchecks import http_check, run_fixed_command, service_running


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
