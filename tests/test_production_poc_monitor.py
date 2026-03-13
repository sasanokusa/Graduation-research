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
from experimental.production_poc.runtime_prod.models import DiscoverySnapshot
from experimental.production_poc.runtime_prod.persistence import StateStore


class _MappedRunner:
    def __init__(self, responses: dict[tuple[str, ...], CommandResult]) -> None:
        self._responses = responses
        self.calls: list[list[str]] = []

    def run(self, args: list[str], *, timeout_seconds: int) -> CommandResult:
        self.calls.append(args)
        key = tuple(args)
        if key in self._responses:
            return self._responses[key]
        return CommandResult(
            args=args,
            returncode=0,
            stdout="",
            stderr="",
            timed_out=False,
            timeout_seconds=timeout_seconds,
            duration_ms=1,
        )


def _config(tmp_path: Path, access_log: Path, mc_log: Path) -> ProductionPocConfig:
    return ProductionPocConfig(
        path=tmp_path / "config.yaml",
        host=HostConfig(host_label="homebox", state_dir=tmp_path / "state", snapshot_refresh_seconds=3600),
        monitoring=MonitoringConfig(
            poll_interval_seconds=60,
            journal_lookback_minutes=15,
            disk_percent_threshold=90,
            memory_percent_threshold=90,
            cpu_percent_threshold=95,
            web_5xx_threshold=2,
            anomaly_cooldown_seconds=0,
            max_related_log_lines=10,
            journal_keywords=["error", "failed"],
            ignored_failed_units=[],
            ignored_journal_patterns=[],
        ),
        web=WebServiceConfig(
            service_name="nginx",
            port=80,
            tcp_host="127.0.0.1",
            health_urls=["http://127.0.0.1/healthz"],
            access_log_paths=[access_log],
            error_log_paths=[],
            systemd_candidates=["nginx"],
        ),
        minecraft=MinecraftServiceConfig(
            management_mode="systemd",
            service_name="minecraft",
            port=25565,
            tcp_host="127.0.0.1",
            log_paths=[mc_log],
            process_hints=["minecraft", "paper", "server.jar"],
            working_directory=None,
            startup_script_path=None,
        ),
        actions=ActionsConfig(
            mode="propose-only",
            allowed_restart_services=["nginx", "minecraft"],
            dangerous_action_policy="require-human-approval",
            max_auto_actions_per_incident=1,
        ),
        notifications=NotificationConfig(
            discord_webhook_url="",
            username="test",
            send_startup_summary=False,
            send_monitoring_started=False,
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


def test_rule_based_probe_detects_service_and_host_anomalies(monkeypatch, tmp_path: Path) -> None:
    access_log = tmp_path / "access.log"
    access_log.write_text('127.0.0.1 - - [13/Mar/2026] "GET / HTTP/1.1" 500 1\n' * 3, encoding="utf-8")
    mc_log = tmp_path / "latest.log"
    mc_log.write_text("[00:00:00] [Server thread/ERROR]: Fatal crash\n", encoding="utf-8")

    responses = {
        ("systemctl", "is-active", "nginx"): CommandResult(
            args=["systemctl", "is-active", "nginx"],
            returncode=3,
            stdout="inactive",
            stderr="",
            timed_out=False,
            timeout_seconds=5,
            duration_ms=1,
        ),
        ("ss", "-ltnpH"): CommandResult(
            args=["ss", "-ltnpH"],
            returncode=0,
            stdout="LISTEN 0 511 127.0.0.1:22 0.0.0.0:* users:((\"sshd\",pid=1,fd=3))",
            stderr="",
            timed_out=False,
            timeout_seconds=5,
            duration_ms=1,
        ),
        ("systemctl", "status", "nginx", "--no-pager", "--lines=25"): CommandResult(
            args=["systemctl", "status", "nginx", "--no-pager", "--lines=25"],
            returncode=3,
            stdout="inactive",
            stderr="",
            timed_out=False,
            timeout_seconds=5,
            duration_ms=1,
        ),
        ("journalctl", "-u", "nginx", "--since", "-15m", "--no-pager", "-n", "10"): CommandResult(
            args=["journalctl", "-u", "nginx", "--since", "-15m", "--no-pager", "-n", "10"],
            returncode=0,
            stdout="error line",
            stderr="",
            timed_out=False,
            timeout_seconds=8,
            duration_ms=1,
        ),
        ("systemctl", "is-active", "minecraft"): CommandResult(
            args=["systemctl", "is-active", "minecraft"],
            returncode=0,
            stdout="active",
            stderr="",
            timed_out=False,
            timeout_seconds=5,
            duration_ms=1,
        ),
        ("systemctl", "status", "minecraft", "--no-pager", "--lines=25"): CommandResult(
            args=["systemctl", "status", "minecraft", "--no-pager", "--lines=25"],
            returncode=0,
            stdout="active",
            stderr="",
            timed_out=False,
            timeout_seconds=5,
            duration_ms=1,
        ),
        ("journalctl", "-u", "minecraft", "--since", "-15m", "--no-pager", "-n", "10"): CommandResult(
            args=["journalctl", "-u", "minecraft", "--since", "-15m", "--no-pager", "-n", "10"],
            returncode=0,
            stdout="warn",
            stderr="",
            timed_out=False,
            timeout_seconds=8,
            duration_ms=1,
        ),
        ("ps", "-eo", "comm,args", "--no-headers"): CommandResult(
            args=["ps", "-eo", "comm,args", "--no-headers"],
            returncode=0,
            stdout="python some-other-process",
            stderr="",
            timed_out=False,
            timeout_seconds=5,
            duration_ms=1,
        ),
        ("df", "-P", "-x", "tmpfs", "-x", "devtmpfs"): CommandResult(
            args=["df", "-P", "-x", "tmpfs", "-x", "devtmpfs"],
            returncode=0,
            stdout="Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/sda1 10 9 1 95% /\n",
            stderr="",
            timed_out=False,
            timeout_seconds=5,
            duration_ms=1,
        ),
        ("systemctl", "--failed", "--no-legend", "--plain"): CommandResult(
            args=["systemctl", "--failed", "--no-legend", "--plain"],
            returncode=0,
            stdout="dummy.service loaded failed failed Dummy\n",
            stderr="",
            timed_out=False,
            timeout_seconds=5,
            duration_ms=1,
        ),
        ("journalctl", "--since", "-15m", "--no-pager", "-n", "10"): CommandResult(
            args=["journalctl", "--since", "-15m", "--no-pager", "-n", "10"],
            returncode=0,
            stdout="segfault happened\nfailed dependency\n",
            stderr="",
            timed_out=False,
            timeout_seconds=8,
            duration_ms=1,
        ),
    }
    runner = _MappedRunner(responses)
    config = _config(tmp_path, access_log, mc_log)
    controller = ProductionPocController(
        config=config,
        runner=runner,
        observer=HostObserver(runner),
        analyzer=RuleBasedIncidentAnalyzer(),
        guard=ActionGuard(config.actions, runner),
        notifier=NullNotifier(),
        store=StateStore(config.host.state_dir),
        backup_provider=NullBackupProvider(),
    )
    snapshot = DiscoverySnapshot(
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
        inferred_health_checks={
            "web": {"selected_target": "http://127.0.0.1/healthz"},
            "minecraft": {"selected_target": "127.0.0.1:25565"},
        },
        backup_status={"summary": "none"},
        lightweight_context={
            "detected_web": {"service_name": "nginx"},
            "detected_minecraft": {"service_name": "minecraft", "management_mode": "systemd"},
        },
    )

    monkeypatch.setattr(
        "experimental.production_poc.runtime_prod.controller.http_probe",
        lambda url, timeout_seconds: {"ok": False, "url": url, "status": 503, "error": "HTTPError"},
    )
    monkeypatch.setattr(
        "experimental.production_poc.runtime_prod.controller.tcp_probe",
        lambda host, port, timeout_seconds: {"ok": False, "host": host, "port": port, "error": "ConnectionRefusedError"},
    )

    findings, probe_details, _ = controller._run_rule_based_probes(snapshot)

    ids = {finding.id for finding in findings}
    assert "web_service_inactive" in ids
    assert "web_http_failed" in ids
    assert "web_5xx_spike" in ids
    assert "minecraft_port_failed" in ids
    assert "systemd_failed" in ids
    assert "journal_critical" in ids
    assert probe_details["web"]["http_5xx"]["count"] == 3


def test_non_systemd_minecraft_skips_systemctl_and_relies_on_process_and_tcp(monkeypatch, tmp_path: Path) -> None:
    access_log = tmp_path / "access.log"
    access_log.write_text("", encoding="utf-8")
    mc_log = tmp_path / "latest.log"
    mc_log.write_text("[00:00:00] [Server thread/INFO]: Done\n", encoding="utf-8")

    responses = {
        ("systemctl", "is-active", "nginx"): CommandResult(
            args=["systemctl", "is-active", "nginx"],
            returncode=0,
            stdout="active",
            stderr="",
            timed_out=False,
            timeout_seconds=5,
            duration_ms=1,
        ),
        ("ss", "-ltnpH"): CommandResult(
            args=["ss", "-ltnpH"],
            returncode=0,
            stdout="LISTEN 0 511 *:80 *:*",
            stderr="",
            timed_out=False,
            timeout_seconds=5,
            duration_ms=1,
        ),
        ("systemctl", "status", "nginx", "--no-pager", "--lines=25"): CommandResult(
            args=["systemctl", "status", "nginx", "--no-pager", "--lines=25"],
            returncode=0,
            stdout="active",
            stderr="",
            timed_out=False,
            timeout_seconds=5,
            duration_ms=1,
        ),
        ("journalctl", "-u", "nginx", "--since", "-15m", "--no-pager", "-n", "10"): CommandResult(
            args=["journalctl", "-u", "nginx", "--since", "-15m", "--no-pager", "-n", "10"],
            returncode=0,
            stdout="",
            stderr="",
            timed_out=False,
            timeout_seconds=8,
            duration_ms=1,
        ),
        ("ps", "-eo", "comm,args", "--no-headers"): CommandResult(
            args=["ps", "-eo", "comm,args", "--no-headers"],
            returncode=0,
            stdout="java java @user_jvm_args.txt @libraries/net/minecraftforge/forge/1.20.1-47.4.10/unix_args.txt nogui",
            stderr="",
            timed_out=False,
            timeout_seconds=5,
            duration_ms=1,
        ),
        ("df", "-P", "-x", "tmpfs", "-x", "devtmpfs"): CommandResult(
            args=["df", "-P", "-x", "tmpfs", "-x", "devtmpfs"],
            returncode=0,
            stdout="Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/sda1 10 2 8 20% /\n",
            stderr="",
            timed_out=False,
            timeout_seconds=5,
            duration_ms=1,
        ),
        ("systemctl", "--failed", "--no-legend", "--plain"): CommandResult(
            args=["systemctl", "--failed", "--no-legend", "--plain"],
            returncode=0,
            stdout="",
            stderr="",
            timed_out=False,
            timeout_seconds=5,
            duration_ms=1,
        ),
        ("journalctl", "--since", "-15m", "--no-pager", "-n", "10"): CommandResult(
            args=["journalctl", "--since", "-15m", "--no-pager", "-n", "10"],
            returncode=0,
            stdout="",
            stderr="",
            timed_out=False,
            timeout_seconds=8,
            duration_ms=1,
        ),
    }
    runner = _MappedRunner(responses)
    config = _config(tmp_path, access_log, mc_log)
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
            log_paths=[mc_log],
            process_hints=["minecraft", "paper", "server.jar", "forge"],
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
        observer=HostObserver(runner),
        analyzer=RuleBasedIncidentAnalyzer(),
        guard=ActionGuard(config.actions, runner),
        notifier=NullNotifier(),
        store=StateStore(config.host.state_dir),
        backup_provider=NullBackupProvider(),
    )
    snapshot = DiscoverySnapshot(
        captured_at="2026-03-13T00:00:00+00:00",
        host={"hostname": "homebox"},
        systemd_services=[],
        process_summary=[],
        open_ports=[{"port": 80}, {"port": 25565}],
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
        inferred_health_checks={
            "web": {"selected_target": "http://127.0.0.1/healthz"},
            "minecraft": {"selected_target": "127.0.0.1:25565"},
        },
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

    monkeypatch.setattr(
        "experimental.production_poc.runtime_prod.controller.http_probe",
        lambda url, timeout_seconds: {"ok": True, "url": url, "status": 200, "error": ""},
    )
    monkeypatch.setattr(
        "experimental.production_poc.runtime_prod.controller.tcp_probe",
        lambda host, port, timeout_seconds: {"ok": True, "host": host, "port": port, "error": ""},
    )

    findings, probe_details, _ = controller._run_rule_based_probes(snapshot)

    ids = {finding.id for finding in findings}
    assert "minecraft_process_missing" not in ids
    assert "minecraft_port_failed" not in ids
    assert probe_details["minecraft"]["management_mode"] == "shell_script"
    assert ["systemctl", "is-active", "minecraft"] not in runner.calls
    assert "minecraft_status" not in probe_details["minecraft"]["logs"]


def test_host_ignorelist_suppresses_known_failed_units_and_journal_noise(monkeypatch, tmp_path: Path) -> None:
    access_log = tmp_path / "access.log"
    access_log.write_text("", encoding="utf-8")
    mc_log = tmp_path / "latest.log"
    mc_log.write_text("[00:00:00] [Server thread/INFO]: Done\n", encoding="utf-8")

    responses = {
        ("systemctl", "is-active", "nginx"): CommandResult(
            args=["systemctl", "is-active", "nginx"],
            returncode=0,
            stdout="active",
            stderr="",
            timed_out=False,
            timeout_seconds=5,
            duration_ms=1,
        ),
        ("ss", "-ltnpH"): CommandResult(
            args=["ss", "-ltnpH"],
            returncode=0,
            stdout="LISTEN 0 511 *:80 *:*",
            stderr="",
            timed_out=False,
            timeout_seconds=5,
            duration_ms=1,
        ),
        ("systemctl", "status", "nginx", "--no-pager", "--lines=25"): CommandResult(
            args=["systemctl", "status", "nginx", "--no-pager", "--lines=25"],
            returncode=0,
            stdout="active",
            stderr="",
            timed_out=False,
            timeout_seconds=5,
            duration_ms=1,
        ),
        ("journalctl", "-u", "nginx", "--since", "-15m", "--no-pager", "-n", "10"): CommandResult(
            args=["journalctl", "-u", "nginx", "--since", "-15m", "--no-pager", "-n", "10"],
            returncode=0,
            stdout="",
            stderr="",
            timed_out=False,
            timeout_seconds=8,
            duration_ms=1,
        ),
        ("systemctl", "is-active", "minecraft"): CommandResult(
            args=["systemctl", "is-active", "minecraft"],
            returncode=0,
            stdout="active",
            stderr="",
            timed_out=False,
            timeout_seconds=5,
            duration_ms=1,
        ),
        ("systemctl", "status", "minecraft", "--no-pager", "--lines=25"): CommandResult(
            args=["systemctl", "status", "minecraft", "--no-pager", "--lines=25"],
            returncode=0,
            stdout="active",
            stderr="",
            timed_out=False,
            timeout_seconds=5,
            duration_ms=1,
        ),
        ("journalctl", "-u", "minecraft", "--since", "-15m", "--no-pager", "-n", "10"): CommandResult(
            args=["journalctl", "-u", "minecraft", "--since", "-15m", "--no-pager", "-n", "10"],
            returncode=0,
            stdout="",
            stderr="",
            timed_out=False,
            timeout_seconds=8,
            duration_ms=1,
        ),
        ("ps", "-eo", "comm,args", "--no-headers"): CommandResult(
            args=["ps", "-eo", "comm,args", "--no-headers"],
            returncode=0,
            stdout="java minecraft-server.jar",
            stderr="",
            timed_out=False,
            timeout_seconds=5,
            duration_ms=1,
        ),
        ("df", "-P", "-x", "tmpfs", "-x", "devtmpfs"): CommandResult(
            args=["df", "-P", "-x", "tmpfs", "-x", "devtmpfs"],
            returncode=0,
            stdout="Filesystem 1024-blocks Used Available Capacity Mounted on\n/dev/sda1 10 2 8 20% /\n",
            stderr="",
            timed_out=False,
            timeout_seconds=5,
            duration_ms=1,
        ),
        ("systemctl", "--failed", "--no-legend", "--plain"): CommandResult(
            args=["systemctl", "--failed", "--no-legend", "--plain"],
            returncode=0,
            stdout=(
                "apt-daily.service loaded failed failed Daily apt download activities\n"
                "logrotate.service loaded failed failed Rotate log files\n"
            ),
            stderr="",
            timed_out=False,
            timeout_seconds=5,
            duration_ms=1,
        ),
        ("journalctl", "--since", "-15m", "--no-pager", "-n", "10"): CommandResult(
            args=["journalctl", "--since", "-15m", "--no-pager", "-n", "10"],
            returncode=0,
            stdout=(
                "Mar 13 22:35:34 saserver ssh[2288]: connect_to localhost port 25565: failed.\n"
                "Mar 13 22:36:33 saserver logrotate[434948]: error: stat of /var/log/playit/playit.log failed: No such file or directory\n"
            ),
            stderr="",
            timed_out=False,
            timeout_seconds=8,
            duration_ms=1,
        ),
    }
    runner = _MappedRunner(responses)
    base_config = _config(tmp_path, access_log, mc_log)
    config = ProductionPocConfig(
        path=base_config.path,
        host=base_config.host,
        monitoring=MonitoringConfig(
            poll_interval_seconds=base_config.monitoring.poll_interval_seconds,
            journal_lookback_minutes=base_config.monitoring.journal_lookback_minutes,
            disk_percent_threshold=base_config.monitoring.disk_percent_threshold,
            memory_percent_threshold=base_config.monitoring.memory_percent_threshold,
            cpu_percent_threshold=base_config.monitoring.cpu_percent_threshold,
            web_5xx_threshold=base_config.monitoring.web_5xx_threshold,
            anomaly_cooldown_seconds=base_config.monitoring.anomaly_cooldown_seconds,
            max_related_log_lines=base_config.monitoring.max_related_log_lines,
            journal_keywords=base_config.monitoring.journal_keywords,
            ignored_failed_units=["apt-daily.service", "logrotate.service"],
            ignored_journal_patterns=["connect_to localhost port 25565: failed", "/var/log/playit/playit.log"],
        ),
        web=base_config.web,
        minecraft=base_config.minecraft,
        actions=base_config.actions,
        notifications=base_config.notifications,
        llm=base_config.llm,
        escalation=base_config.escalation,
    )
    controller = ProductionPocController(
        config=config,
        runner=runner,
        observer=HostObserver(runner),
        analyzer=RuleBasedIncidentAnalyzer(),
        guard=ActionGuard(config.actions, runner),
        notifier=NullNotifier(),
        store=StateStore(config.host.state_dir),
        backup_provider=NullBackupProvider(),
    )
    snapshot = DiscoverySnapshot(
        captured_at="2026-03-13T00:00:00+00:00",
        host={"hostname": "homebox"},
        systemd_services=[],
        process_summary=[],
        open_ports=[{"port": 80}, {"port": 25565}],
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
        inferred_health_checks={
            "web": {"selected_target": "http://127.0.0.1/healthz"},
            "minecraft": {"selected_target": "127.0.0.1:25565"},
        },
        backup_status={"summary": "none"},
        lightweight_context={
            "detected_web": {"service_name": "nginx"},
            "detected_minecraft": {"service_name": "minecraft", "management_mode": "systemd"},
        },
    )

    monkeypatch.setattr(
        "experimental.production_poc.runtime_prod.controller.http_probe",
        lambda url, timeout_seconds: {"ok": True, "url": url, "status": 200, "error": ""},
    )
    monkeypatch.setattr(
        "experimental.production_poc.runtime_prod.controller.tcp_probe",
        lambda host, port, timeout_seconds: {"ok": True, "host": host, "port": port, "error": ""},
    )

    findings, _, _ = controller._run_rule_based_probes(snapshot)

    ids = {finding.id for finding in findings}
    assert "systemd_failed" not in ids
    assert "journal_critical" not in ids
