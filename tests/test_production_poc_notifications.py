import json
import urllib.error
from dataclasses import dataclass

from experimental.production_poc.notifications.discord import DiscordWebhookNotifier
from experimental.production_poc.runtime_prod.models import (
    DiscoverySnapshot,
    Finding,
    IncidentAnalysis,
    MonitorOutcome,
    ProposedAction,
)


@dataclass
class _DummyResponse:
    def __enter__(self) -> "_DummyResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None


def test_discord_notifier_formats_startup_and_incident(monkeypatch) -> None:
    sent_payloads: list[dict[str, str]] = []

    def _fake_urlopen(request, timeout=10):  # noqa: ANN001
        sent_payloads.append(json.loads(request.data.decode("utf-8")))
        return _DummyResponse()

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    notifier = DiscordWebhookNotifier("https://example.invalid/webhook")

    snapshot = DiscoverySnapshot(
        captured_at="2026-03-13T00:00:00+00:00",
        host={"hostname": "homebox", "uptime": "up 2 hours"},
        systemd_services=[],
        process_summary=[],
        open_ports=[],
        disk_usage=[{"mountpoint": "/", "used_percent": "42%"}],
        memory_usage={"used_percent": 55.0},
        cpu_usage={"used_percent": 11.0},
        journal_summary={"keyword_counts": {}},
        detected_web={"service_name": "nginx", "server_type": "nginx"},
        detected_minecraft={"launch_method": "systemd"},
        inferred_health_checks={},
        backup_status={"summary": "none"},
        lightweight_context={},
    )
    outcome = MonitorOutcome(
        correlation_id="abc123",
        checked_at="2026-03-13T00:01:00+00:00",
        findings=[
            Finding(
                id="web_service_inactive",
                severity="critical",
                service="nginx",
                title="Web service is not active",
                summary="nginx is down",
                evidence=["inactive"],
            )
        ],
        probe_details={},
        related_logs={
            "web_access_logs": {"/var/log/nginx/access.log": ["web access line"]},
            "minecraft_logs": {"/srv/minecraft/latest.log": ["minecraft line"]},
            "web_status": {"stdout": "● nginx.service - running\nmore"},
        },
        analysis=IncidentAnalysis(
            analyzer="rule_based",
            summary="nginx is down",
            likely_causes=[{"cause": "service stopped", "confidence": "medium", "evidence": ["inactive"]}],
            proposed_actions=[ProposedAction(kind="restart_service", service="nginx", reason="recover")],
        ),
        verification={"ok": True, "skipped": True, "reason": "no executable action selected"},
    )

    notifier.send_startup_summary(snapshot)
    notifier.send_incident(outcome, host_label="homebox", mode="propose-only")

    assert len(sent_payloads) == 4
    assert "起動サマリ" in sent_payloads[0]["content"]
    assert "監視開始" not in sent_payloads[0]["content"]
    assert "相関ID=abc123" in sent_payloads[2]["content"]
    assert "ログ抜粋" in sent_payloads[3]["content"]
    assert "検証: スキップ" in sent_payloads[3]["content"]
    assert "web_status: ● nginx.service - running" in sent_payloads[3]["content"]
    assert sent_payloads[3]["content"].find("web access line") < sent_payloads[3]["content"].find("minecraft line")


def test_discord_notifier_ignores_http_error_and_continues(monkeypatch, capsys) -> None:
    def _raise_http_error(request, timeout=10):  # noqa: ANN001
        raise urllib.error.HTTPError(
            url=request.full_url,
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr("urllib.request.urlopen", _raise_http_error)
    notifier = DiscordWebhookNotifier("https://example.invalid/webhook")

    snapshot = DiscoverySnapshot(
        captured_at="2026-03-13T00:00:00+00:00",
        host={"hostname": "homebox", "uptime": "up 2 hours"},
        systemd_services=[],
        process_summary=[],
        open_ports=[],
        disk_usage=[],
        memory_usage={"used_percent": 55.0},
        cpu_usage={"used_percent": 11.0},
        journal_summary={"keyword_counts": {}},
        detected_web={"service_name": "nginx", "server_type": "nginx"},
        detected_minecraft={"launch_method": "systemd"},
        inferred_health_checks={},
        backup_status={"summary": "none"},
        lightweight_context={},
    )

    notifier.send_startup_summary(snapshot)

    captured = capsys.readouterr()
    assert "HTTP 403" in captured.err


def test_discord_notifier_prioritizes_finding_related_logs(monkeypatch) -> None:
    sent_payloads: list[dict[str, str]] = []

    def _fake_urlopen(request, timeout=10):  # noqa: ANN001
        sent_payloads.append(json.loads(request.data.decode("utf-8")))
        return _DummyResponse()

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    notifier = DiscordWebhookNotifier("https://example.invalid/webhook")

    outcome = MonitorOutcome(
        correlation_id="mc123",
        checked_at="2026-03-13T00:01:00+00:00",
        findings=[
            Finding(
                id="minecraft_port_failed",
                severity="critical",
                service="minecraft",
                title="Minecraft TCP check failed",
                summary="The Minecraft TCP probe failed.",
                evidence=["ConnectionRefusedError"],
            )
        ],
        probe_details={},
        related_logs={
            "web_access_logs": {"/var/log/apache2/access.log": ["web access line"]},
            "minecraft_logs": {"/srv/minecraft/latest.log": ["minecraft line"]},
            "web_status": {"stdout": "● apache2.service - running"},
        },
        analysis=IncidentAnalysis(
            analyzer="rule_based",
            summary="The Minecraft TCP probe failed.",
            likely_causes=[{"cause": "minecraft unavailable", "confidence": "medium", "evidence": []}],
            proposed_actions=[],
            escalation_reason="manual recovery required",
        ),
        verification={"ok": True, "skipped": True, "reason": "no executable action selected"},
        escalated=True,
        escalation_reason="manual recovery required",
    )

    notifier.send_incident(outcome, host_label="homebox", mode="propose-only")

    detail = sent_payloads[1]["content"]
    assert detail.find("minecraft line") < detail.find("web access line")
    assert "検証: スキップ" in detail
