from pathlib import Path

from experimental.production_poc.adapters.action_guard import ActionGuard
from experimental.production_poc.adapters.backup_provider import NullBackupProvider
from experimental.production_poc.adapters.command_runner import CommandResult
from experimental.production_poc.adapters.host_observer import HostObserver
from experimental.production_poc.adapters.llm_analyzer import RuleBasedIncidentAnalyzer
from experimental.production_poc.notifications.discord import NullNotifier
from experimental.production_poc.runtime_prod.config import (
    ActionsConfig,
    EscalationConfig,
    HostConfig,
    LlmConfig,
    MinecraftServiceConfig,
    MonitoringConfig,
    NotificationConfig,
    ProductionPocConfig,
    WebServiceConfig,
)
from experimental.production_poc.runtime_prod.controller import ProductionPocController
from experimental.production_poc.runtime_prod.models import DiscoverySnapshot, Finding, IncidentAnalysis, ProposedAction
from experimental.production_poc.runtime_prod.persistence import StateStore


class _Runner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def run(self, args: list[str], *, timeout_seconds: int) -> CommandResult:
        self.calls.append(args)
        return CommandResult(
            args=args,
            returncode=0,
            stdout="ok",
            stderr="",
            timed_out=False,
            timeout_seconds=timeout_seconds,
            duration_ms=1,
        )


class _Analyzer:
    def __init__(self, action: ProposedAction) -> None:
        self.action = action

    def analyze(self, incident_context):  # noqa: ANN001
        return IncidentAnalysis(
            analyzer="test",
            summary="detected",
            likely_causes=[{"cause": "service stopped", "confidence": "high", "evidence": []}],
            proposed_actions=[self.action],
            escalation_reason="",
        )


class _Notifier(NullNotifier):
    def __init__(self) -> None:
        self.started = 0
        self.incidents = 0

    def send_monitoring_started(self, *, host_label: str, mode: str) -> None:
        self.started += 1

    def send_incident(self, outcome, *, host_label: str, mode: str) -> None:  # noqa: ANN001
        self.incidents += 1


class _Observer(HostObserver):
    def __init__(self, runner) -> None:  # noqa: ANN001
        super().__init__(runner)


def _config(tmp_path: Path, mode: str) -> ProductionPocConfig:
    return ProductionPocConfig(
        path=tmp_path / "config.yaml",
        host=HostConfig(host_label="homebox", state_dir=tmp_path / "state", snapshot_refresh_seconds=3600),
        monitoring=MonitoringConfig(
            poll_interval_seconds=60,
            journal_lookback_minutes=15,
            disk_percent_threshold=90,
            memory_percent_threshold=90,
            cpu_percent_threshold=95,
            web_5xx_threshold=5,
            anomaly_cooldown_seconds=0,
            max_related_log_lines=10,
            journal_keywords=["error"],
        ),
        web=WebServiceConfig(
            service_name="nginx",
            port=80,
            tcp_host="127.0.0.1",
            health_urls=["http://127.0.0.1/healthz"],
            access_log_paths=[],
            error_log_paths=[],
            systemd_candidates=["nginx"],
        ),
        minecraft=MinecraftServiceConfig(
            management_mode="systemd",
            service_name="minecraft",
            port=25565,
            tcp_host="127.0.0.1",
            log_paths=[],
            process_hints=["minecraft"],
            working_directory=None,
            startup_script_path=None,
        ),
        actions=ActionsConfig(
            mode=mode,
            allowed_restart_services=["nginx"],
            dangerous_action_policy="require-human-approval",
            max_auto_actions_per_incident=1,
        ),
        notifications=NotificationConfig(
            discord_webhook_url="",
            username="test",
            send_startup_summary=False,
            send_monitoring_started=True,
        ),
        llm=LlmConfig(
            enabled=False,
            provider="openai",
            model="gpt-4.1-mini",
            timeout_seconds=30,
            api_key_env="OPENAI_API_KEY",
            max_context_lines=20,
        ),
        escalation=EscalationConfig(
            require_human_for_medium_risk=True,
            notify_on_verification_failure=True,
        ),
    )


def _snapshot() -> DiscoverySnapshot:
    return DiscoverySnapshot(
        captured_at="2026-03-13T00:00:00+00:00",
        host={"hostname": "homebox"},
        systemd_services=[],
        process_summary=[],
        open_ports=[{"port": 80}],
        disk_usage=[],
        memory_usage={"used_percent": 10.0},
        cpu_usage={"used_percent": 5.0},
        journal_summary={"keyword_counts": {}},
        detected_web={"service_name": "nginx", "server_type": "nginx"},
        detected_minecraft={
            "service_name": "minecraft",
            "launch_method": "systemd",
            "management_mode": "systemd",
            "port": 25565,
        },
        inferred_health_checks={"web": {"selected_target": "http://127.0.0.1/healthz"}},
        backup_status={"summary": "none"},
        lightweight_context={
            "detected_web": {"service_name": "nginx"},
            "detected_minecraft": {"service_name": "minecraft", "management_mode": "systemd"},
        },
    )


def test_controller_in_dry_run_does_not_execute_auto_action(monkeypatch, tmp_path: Path) -> None:
    runner = _Runner()
    notifier = _Notifier()
    config = _config(tmp_path, mode="dry-run")
    controller = ProductionPocController(
        config=config,
        runner=runner,
        observer=_Observer(runner),
        analyzer=_Analyzer(ProposedAction(kind="restart_service", service="nginx", reason="recover")),
        guard=ActionGuard(config.actions, runner),
        notifier=notifier,
        store=StateStore(config.host.state_dir),
        backup_provider=NullBackupProvider(),
    )
    monkeypatch.setattr(controller, "_load_or_refresh_snapshot", _snapshot)
    monkeypatch.setattr(
        controller,
        "_run_rule_based_probes",
        lambda snapshot: (
            [
                Finding(
                    id="web_service_inactive",
                    severity="critical",
                    service="nginx",
                    title="Web service is not active",
                    summary="nginx is down",
                )
            ],
            {"web": {}},
            {},
        ),
    )

    outcome = controller.run_monitor_once()

    assert outcome.execution_results == []
    assert notifier.started == 1
    assert notifier.incidents == 1
    assert runner.calls == []


def test_controller_in_execute_mode_restarts_once_and_verifies(monkeypatch, tmp_path: Path) -> None:
    runner = _Runner()
    notifier = _Notifier()
    config = _config(tmp_path, mode="execute")
    controller = ProductionPocController(
        config=config,
        runner=runner,
        observer=_Observer(runner),
        analyzer=_Analyzer(ProposedAction(kind="restart_service", service="nginx", reason="recover")),
        guard=ActionGuard(config.actions, runner),
        notifier=notifier,
        store=StateStore(config.host.state_dir),
        backup_provider=NullBackupProvider(),
    )
    monkeypatch.setattr(controller, "_load_or_refresh_snapshot", _snapshot)
    monkeypatch.setattr(
        controller,
        "_run_rule_based_probes",
        lambda snapshot: (
            [
                Finding(
                    id="web_service_inactive",
                    severity="critical",
                    service="nginx",
                    title="Web service is not active",
                    summary="nginx is down",
                )
            ],
            {"web": {}},
            {},
        ),
    )
    monkeypatch.setattr(controller, "_verify_after_action", lambda snapshot, action: {"ok": True, "target": "nginx"})

    outcome = controller.run_monitor_once()

    assert len(outcome.execution_results) == 1
    assert outcome.execution_results[0].executed is True
    assert outcome.verification["ok"] is True
    assert runner.calls == [["systemctl", "restart", "nginx"]]
    assert notifier.incidents == 1


def test_controller_escalates_for_shell_script_managed_minecraft_without_auto_restart(monkeypatch, tmp_path: Path) -> None:
    runner = _Runner()
    notifier = _Notifier()
    config = _config(tmp_path, mode="propose-only")
    config = ProductionPocConfig(
        path=config.path,
        host=config.host,
        monitoring=config.monitoring,
        web=config.web,
        minecraft=MinecraftServiceConfig(
            management_mode="shell_script",
            service_name="",
            port=25565,
            tcp_host="127.0.0.1",
            log_paths=[],
            process_hints=["minecraft"],
            working_directory=tmp_path / "minecraft-server",
            startup_script_path=tmp_path / "minecraft-server" / "start-server.sh",
        ),
        actions=config.actions,
        notifications=config.notifications,
        llm=config.llm,
        escalation=config.escalation,
    )
    controller = ProductionPocController(
        config=config,
        runner=runner,
        observer=_Observer(runner),
        analyzer=RuleBasedIncidentAnalyzer(),
        guard=ActionGuard(config.actions, runner),
        notifier=notifier,
        store=StateStore(config.host.state_dir),
        backup_provider=NullBackupProvider(),
    )
    shell_snapshot = DiscoverySnapshot(
        captured_at="2026-03-13T00:00:00+00:00",
        host={"hostname": "homebox"},
        systemd_services=[],
        process_summary=[],
        open_ports=[{"port": 25565}],
        disk_usage=[],
        memory_usage={"used_percent": 10.0},
        cpu_usage={"used_percent": 5.0},
        journal_summary={"keyword_counts": {}},
        detected_web={"service_name": "nginx", "server_type": "nginx"},
        detected_minecraft={
            "service_name": "",
            "launch_method": "shell_script",
            "management_mode": "shell_script",
            "port": 25565,
            "working_directory": str(tmp_path / "minecraft-server"),
            "startup_script_path": str(tmp_path / "minecraft-server" / "start-server.sh"),
        },
        inferred_health_checks={"web": {"selected_target": "http://127.0.0.1/healthz"}},
        backup_status={"summary": "none"},
        lightweight_context={
            "detected_web": {"service_name": "nginx"},
            "detected_minecraft": {
                "management_mode": "shell_script",
                "working_directory": str(tmp_path / "minecraft-server"),
                "startup_script_path": str(tmp_path / "minecraft-server" / "start-server.sh"),
            },
        },
    )
    monkeypatch.setattr(controller, "_load_or_refresh_snapshot", lambda: shell_snapshot)
    monkeypatch.setattr(
        controller,
        "_run_rule_based_probes",
        lambda snapshot: (
            [
                Finding(
                    id="minecraft_process_missing",
                    severity="critical",
                    service="minecraft",
                    title="Minecraft process is missing",
                    summary="No Minecraft-like Java process is visible.",
                    evidence=["java process with Minecraft hints was not found"],
                )
            ],
            {"minecraft": {"management_mode": "shell_script"}},
            {},
        ),
    )

    outcome = controller.run_monitor_once()

    assert outcome.analysis is not None
    assert outcome.analysis.proposed_actions == []
    assert "shell_script" in outcome.analysis.escalation_reason
    assert "start-server.sh" in outcome.analysis.escalation_reason
    assert outcome.execution_results == []
    assert runner.calls == []
