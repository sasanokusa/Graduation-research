from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from experimental.production_poc.adapters.action_guard import ActionGuard
from experimental.production_poc.adapters.backup_provider import BackupProvider
from experimental.production_poc.adapters.command_runner import CommandRunner
from experimental.production_poc.adapters.host_observer import HostObserver
from experimental.production_poc.adapters.llm_analyzer import IncidentAnalyzer
from experimental.production_poc.adapters.service_probes import (
    count_recent_5xx,
    detect_crash_keywords,
    http_probe,
    journal_excerpt,
    listen_check,
    systemd_is_active,
    systemd_status_excerpt,
    tail_log_files,
    tcp_probe,
)
from experimental.production_poc.notifications.discord import Notifier
from experimental.production_poc.runtime_prod.config import ProductionPocConfig
from experimental.production_poc.runtime_prod.models import DiscoverySnapshot, Finding, MonitorOutcome, utc_now_iso
from experimental.production_poc.runtime_prod.persistence import StateStore, build_snapshot_markdown


class ProductionPocController:
    """Coordinates discovery, monitoring, analysis, and guarded execution."""

    def __init__(
        self,
        *,
        config: ProductionPocConfig,
        runner: CommandRunner,
        observer: HostObserver,
        analyzer: IncidentAnalyzer,
        guard: ActionGuard,
        notifier: Notifier,
        store: StateStore,
        backup_provider: BackupProvider,
    ) -> None:
        self._config = config
        self._runner = runner
        self._observer = observer
        self._analyzer = analyzer
        self._guard = guard
        self._notifier = notifier
        self._store = store
        self._backup_provider = backup_provider

    def run_discovery(self, *, notify: bool = True) -> DiscoverySnapshot:
        snapshot = self._observer.collect_snapshot(self._config, backup_provider=self._backup_provider)
        markdown = build_snapshot_markdown(snapshot)
        self._store.save_snapshot(snapshot, markdown)
        if notify and self._config.notifications.send_startup_summary:
            self._notifier.send_startup_summary(snapshot)
        return snapshot

    def run_monitor_once(self) -> MonitorOutcome:
        snapshot = self._load_or_refresh_snapshot()
        checked_at = utc_now_iso()
        if not self._store.monitor_started() and self._config.notifications.send_monitoring_started:
            self._notifier.send_monitoring_started(
                host_label=self._config.host.host_label,
                mode=self._config.actions.mode,
            )
            self._store.mark_monitor_started()
        findings, probe_details, related_logs = self._run_rule_based_probes(snapshot)
        correlation_id = self._build_correlation_id(checked_at, findings)

        if not findings:
            outcome = MonitorOutcome(
                correlation_id=correlation_id,
                checked_at=checked_at,
                findings=[],
                probe_details=probe_details,
                related_logs=related_logs,
            )
            return outcome

        incident_context = {
            "snapshot_context": snapshot.lightweight_context,
            "findings": [finding.to_dict() for finding in findings],
            "probe_details": probe_details,
            "related_logs": related_logs,
        }
        analysis = self._analyzer.analyze(incident_context)
        guard_results = self._guard.evaluate_all(analysis.proposed_actions)

        execution_results = []
        verification = {"ok": True, "skipped": True, "reason": "no executable action selected"}
        escalated = any(result.requires_human_approval for result in guard_results) or bool(analysis.escalation_reason)
        escalation_reason = analysis.escalation_reason

        executable = self._guard.first_executable(guard_results[: self._config.actions.max_auto_actions_per_incident])
        if executable is not None:
            execution = self._guard.execute(executable)
            execution_results.append(execution)
            verification = self._verify_after_action(snapshot, executable.action)
            if not execution.ok:
                escalated = True
                escalation_reason = execution.details.get("stderr") or "Automatic action execution failed."
            elif not verification.get("ok"):
                escalated = True
                escalation_reason = "Verification failed after the automatic action. Chained actions were blocked."

        outcome = MonitorOutcome(
            correlation_id=correlation_id,
            checked_at=checked_at,
            findings=findings,
            probe_details=probe_details,
            related_logs=related_logs,
            analysis=analysis,
            guard_results=guard_results,
            execution_results=execution_results,
            verification=verification,
            escalated=escalated,
            escalation_reason=escalation_reason,
        )
        self._store.save_incident(outcome)

        fingerprint = self._fingerprint_from_findings(findings)
        if not self._store.notification_is_suppressed(
            fingerprint,
            checked_at_epoch=int(time.time()),
            cooldown_seconds=self._config.monitoring.anomaly_cooldown_seconds,
        ):
            self._notifier.send_incident(
                outcome,
                host_label=self._config.host.host_label,
                mode=self._config.actions.mode,
            )
        return outcome

    def _load_or_refresh_snapshot(self) -> DiscoverySnapshot:
        latest = self._store.load_latest_snapshot()
        if latest is None or self._snapshot_is_stale(latest):
            return self.run_discovery(notify=False)
        return DiscoverySnapshot(**latest)

    def _snapshot_is_stale(self, snapshot: dict[str, Any]) -> bool:
        captured_at = str(snapshot.get("captured_at", ""))
        try:
            captured = datetime.fromisoformat(captured_at)
        except ValueError:
            return True
        age_seconds = int((datetime.now(timezone.utc) - captured).total_seconds())
        return age_seconds >= self._config.host.snapshot_refresh_seconds

    def _run_rule_based_probes(self, snapshot: DiscoverySnapshot) -> tuple[list[Finding], dict[str, Any], dict[str, Any]]:
        findings: list[Finding] = []
        probe_details: dict[str, Any] = {}
        related_logs: dict[str, Any] = {}

        web_details = self._probe_web(snapshot)
        probe_details["web"] = web_details
        related_logs.update(web_details.get("logs", {}))
        if web_details.get("service_active") is not None and not web_details["service_active"].get("ok"):
            findings.append(
                Finding(
                    id="web_service_inactive",
                    severity="critical",
                    service=str(web_details.get("service_name", "")),
                    title="Web service is not active",
                    summary="The detected web service is not active under systemd.",
                    evidence=[str(web_details["service_active"].get("state", "unknown"))],
                )
            )
        if web_details.get("listen_result") and not web_details["listen_result"].get("ok"):
            findings.append(
                Finding(
                    id="web_listen_missing",
                    severity="critical",
                    service=str(web_details.get("service_name", "")),
                    title="Web listener is missing",
                    summary="The expected web listener could not be found.",
                    evidence=[f"port={web_details['listen_result'].get('port')}"],
                )
            )
        if web_details.get("http_result") and not web_details["http_result"].get("ok"):
            findings.append(
                Finding(
                    id="web_http_failed",
                    severity="critical",
                    service=str(web_details.get("service_name", "")),
                    title="HTTP health check failed",
                    summary="The inferred web health endpoint failed.",
                    evidence=[
                        f"url={web_details['http_result'].get('url')}",
                        f"status={web_details['http_result'].get('status')}",
                        str(web_details["http_result"].get("error", "")),
                    ],
                )
            )
        if web_details.get("http_5xx", {}).get("count", 0) >= self._config.monitoring.web_5xx_threshold:
            findings.append(
                Finding(
                    id="web_5xx_spike",
                    severity="warning",
                    service=str(web_details.get("service_name", "")),
                    title="Recent web 5xx responses exceeded threshold",
                    summary="The access log shows repeated recent 5xx responses.",
                    evidence=[f"count={web_details['http_5xx']['count']}"] + web_details["http_5xx"].get("samples", [])[:2],
                )
            )

        minecraft_details = self._probe_minecraft(snapshot)
        minecraft_label = str(minecraft_details.get("service_name") or "minecraft")
        probe_details["minecraft"] = minecraft_details
        related_logs.update(minecraft_details.get("logs", {}))
        if minecraft_details.get("service_active") is not None and not minecraft_details["service_active"].get("ok"):
            findings.append(
                Finding(
                    id="minecraft_process_missing",
                    severity="critical",
                    service=minecraft_label,
                    title="Minecraft service is not active",
                    summary="The configured or detected Minecraft service is not active.",
                    evidence=[str(minecraft_details["service_active"].get("state", "unknown"))],
                )
            )
        if minecraft_details.get("process_present") is False:
            findings.append(
                Finding(
                    id="minecraft_process_missing",
                    severity="critical",
                    service=minecraft_label,
                    title="Minecraft process is missing",
                    summary="No Minecraft-like Java process is visible.",
                    evidence=["java process with Minecraft hints was not found"],
                )
            )
        if minecraft_details.get("tcp_result") and not minecraft_details["tcp_result"].get("ok"):
            findings.append(
                Finding(
                    id="minecraft_port_failed",
                    severity="critical",
                    service=minecraft_label,
                    title="Minecraft TCP check failed",
                    summary="The Minecraft TCP probe failed.",
                    evidence=[str(minecraft_details["tcp_result"].get("error", ""))],
                )
            )
        if minecraft_details.get("crash_signals", {}).get("count", 0) > 0:
            findings.append(
                Finding(
                    id="minecraft_crash_log",
                    severity="warning",
                    service=minecraft_label,
                    title="Minecraft crash keywords detected",
                    summary="Minecraft logs contain crash-like keywords.",
                    evidence=minecraft_details["crash_signals"].get("samples", [])[:3],
                )
            )

        host_details = self._probe_host()
        probe_details["host"] = host_details
        related_logs.update(host_details.get("logs", {}))
        if host_details.get("disk_pressure"):
            findings.append(
                Finding(
                    id="disk_pressure",
                    severity="critical",
                    service="host",
                    title="Disk usage exceeded threshold",
                    summary="At least one filesystem is over the configured disk usage threshold.",
                    evidence=host_details["disk_pressure"][:3],
                )
            )
        if host_details.get("memory_pressure"):
            findings.append(
                Finding(
                    id="memory_pressure",
                    severity="warning",
                    service="host",
                    title="Memory usage exceeded threshold",
                    summary="Host memory usage exceeded the configured threshold.",
                    evidence=[f"used_percent={host_details['memory_used_percent']}"],
                )
            )
        if host_details.get("cpu_pressure"):
            findings.append(
                Finding(
                    id="cpu_pressure",
                    severity="warning",
                    service="host",
                    title="CPU usage exceeded threshold",
                    summary="Host CPU usage exceeded the configured threshold.",
                    evidence=[f"used_percent={host_details['cpu_used_percent']}"],
                )
            )
        if host_details.get("failed_services"):
            findings.append(
                Finding(
                    id="systemd_failed",
                    severity="warning",
                    service="host",
                    title="systemd has failed units",
                    summary="One or more systemd units are in failed state.",
                    evidence=host_details["failed_services"][:4],
                )
            )
        if host_details.get("journal_matches"):
            findings.append(
                Finding(
                    id="journal_critical",
                    severity="warning",
                    service="host",
                    title="journalctl shows recent critical keywords",
                    summary="Recent journal lines matched configured critical keywords.",
                    evidence=host_details["journal_matches"][:4],
                )
            )
        return findings, probe_details, related_logs

    def _probe_web(self, snapshot: DiscoverySnapshot) -> dict[str, Any]:
        service_name = str(snapshot.detected_web.get("service_name") or self._config.web.service_name)
        health_url = str(snapshot.inferred_health_checks.get("web", {}).get("selected_target") or self._config.web.health_urls[0])
        port = self._config.web.port or self._first_detected_port(snapshot.open_ports, preferred={80, 443, 8080})
        service_active = (
            systemd_is_active(self._runner, service_name, timeout_seconds=5)
            if service_name
            else None
        )
        listen_result = listen_check(self._runner, port, timeout_seconds=5) if port else None
        http_result = http_probe(health_url, timeout_seconds=5) if health_url else None
        access_logs = tail_log_files(self._config.web.access_log_paths, max_lines=self._config.monitoring.max_related_log_lines)
        error_logs = tail_log_files(self._config.web.error_log_paths, max_lines=min(20, self._config.monitoring.max_related_log_lines))
        http_5xx = count_recent_5xx(access_logs)
        logs = {
            "web_access_logs": access_logs,
            "web_error_logs": error_logs,
        }
        if service_name:
            logs["web_status"] = systemd_status_excerpt(self._runner, service_name, timeout_seconds=5)
            logs["web_journal"] = journal_excerpt(
                self._runner,
                service_name=service_name,
                lookback_minutes=self._config.monitoring.journal_lookback_minutes,
                lines=self._config.monitoring.max_related_log_lines,
                timeout_seconds=8,
            )
        return {
            "service_name": service_name,
            "health_url": health_url,
            "port": port,
            "service_active": service_active,
            "listen_result": listen_result,
            "http_result": http_result,
            "http_5xx": http_5xx,
            "logs": logs,
        }

    def _probe_minecraft(self, snapshot: DiscoverySnapshot) -> dict[str, Any]:
        service_name = str(snapshot.detected_minecraft.get("service_name") or self._config.minecraft.service_name)
        management_mode = self._minecraft_management_mode(snapshot)
        port = int(snapshot.detected_minecraft.get("port") or self._config.minecraft.port)
        service_active = (
            systemd_is_active(self._runner, service_name, timeout_seconds=5)
            if service_name and management_mode == "systemd"
            else None
        )
        tcp_result = tcp_probe(self._config.minecraft.tcp_host, port, timeout_seconds=5)
        log_excerpt = tail_log_files(self._config.minecraft.log_paths, max_lines=self._config.monitoring.max_related_log_lines)
        crash_signals = detect_crash_keywords(
            log_excerpt,
            ["exception", "crash", "fatal", "oom", "outofmemory", "stopping server"],
        )
        logs = {"minecraft_logs": log_excerpt}
        if service_name and management_mode == "systemd":
            logs["minecraft_status"] = systemd_status_excerpt(self._runner, service_name, timeout_seconds=5)
            logs["minecraft_journal"] = journal_excerpt(
                self._runner,
                service_name=service_name,
                lookback_minutes=self._config.monitoring.journal_lookback_minutes,
                lines=self._config.monitoring.max_related_log_lines,
                timeout_seconds=8,
            )
        return {
            "service_name": service_name,
            "management_mode": management_mode,
            "port": port,
            "service_active": service_active,
            "process_present": self._minecraft_process_present(),
            "tcp_result": tcp_result,
            "crash_signals": crash_signals,
            "startup_script_path": str(
                snapshot.detected_minecraft.get("startup_script_path") or self._config.minecraft.startup_script_path or ""
            ),
            "working_directory": str(
                snapshot.detected_minecraft.get("working_directory") or self._config.minecraft.working_directory or ""
            ),
            "logs": logs,
        }

    def _probe_host(self) -> dict[str, Any]:
        disk_rows = self._runner.run(["df", "-P", "-x", "tmpfs", "-x", "devtmpfs"], timeout_seconds=5).stdout.splitlines()[1:]
        disk_pressure = []
        for line in disk_rows:
            parts = line.split()
            if len(parts) >= 6:
                used_percent = parts[4]
                try:
                    numeric = int(used_percent.rstrip("%"))
                except ValueError:
                    numeric = 0
                if numeric >= self._config.monitoring.disk_percent_threshold:
                    disk_pressure.append(f"{parts[5]}={used_percent}")

        memory_used_percent = self._memory_used_percent()
        cpu_used_percent = self._cpu_used_percent()

        failed_services_result = self._runner.run(
            ["systemctl", "--failed", "--no-legend", "--plain"],
            timeout_seconds=5,
        )
        failed_services = [line.strip() for line in failed_services_result.stdout.splitlines() if line.strip()]

        journal = journal_excerpt(
            self._runner,
            lookback_minutes=self._config.monitoring.journal_lookback_minutes,
            lines=self._config.monitoring.max_related_log_lines,
            timeout_seconds=8,
        )
        journal_lines = journal.get("stdout", "").splitlines()
        journal_matches = [
            line[:240]
            for line in journal_lines
            if any(keyword.lower() in line.lower() for keyword in self._config.monitoring.journal_keywords)
        ]
        return {
            "disk_pressure": disk_pressure,
            "memory_used_percent": memory_used_percent,
            "memory_pressure": memory_used_percent >= self._config.monitoring.memory_percent_threshold,
            "cpu_used_percent": cpu_used_percent,
            "cpu_pressure": cpu_used_percent >= self._config.monitoring.cpu_percent_threshold,
            "failed_services": failed_services,
            "journal_matches": journal_matches,
            "logs": {"host_journal": journal_lines[-10:]},
        }

    def _verify_after_action(self, snapshot: DiscoverySnapshot, action: Any) -> dict[str, Any]:
        if action.kind == "restart_service" and action.service in {
            snapshot.detected_web.get("service_name"),
            self._config.web.service_name,
        }:
            web_details = self._probe_web(snapshot)
            ok = bool(web_details.get("service_active", {}).get("ok")) and bool(web_details.get("http_result", {}).get("ok"))
            return {"ok": ok, "target": action.service, "web": web_details}
        if action.kind == "restart_service" and action.service in {
            snapshot.detected_minecraft.get("service_name"),
            self._config.minecraft.service_name,
        }:
            minecraft_details = self._probe_minecraft(snapshot)
            management_mode = str(minecraft_details.get("management_mode", "auto"))
            if management_mode == "systemd":
                ok = bool(minecraft_details.get("service_active", {}).get("ok")) and bool(
                    minecraft_details.get("tcp_result", {}).get("ok")
                )
            else:
                ok = bool(minecraft_details.get("process_present")) and bool(minecraft_details.get("tcp_result", {}).get("ok"))
            return {"ok": ok, "target": action.service, "minecraft": minecraft_details}
        return {"ok": False, "target": action.service, "reason": "No verification routine matched the action target."}

    def _memory_used_percent(self) -> float:
        meminfo = Path("/proc/meminfo")
        values: dict[str, int] = {}
        if meminfo.exists():
            for line in meminfo.read_text(encoding="utf-8", errors="replace").splitlines():
                if ":" not in line:
                    continue
                key, raw_value = line.split(":", 1)
                number = raw_value.strip().split()[0]
                if number.isdigit():
                    values[key] = int(number)
        total = values.get("MemTotal", 0)
        available = values.get("MemAvailable", 0)
        if total == 0:
            return 0.0
        return round(((total - available) / total) * 100, 1)

    def _cpu_used_percent(self) -> float:
        first = self._read_proc_stat()
        time.sleep(0.1)
        second = self._read_proc_stat()
        idle_delta = second["idle"] - first["idle"]
        total_delta = second["total"] - first["total"]
        if total_delta <= 0:
            return 0.0
        return round((1 - (idle_delta / total_delta)) * 100, 1)

    def _minecraft_process_present(self) -> bool:
        result = self._runner.run(
            ["ps", "-eo", "comm,args", "--no-headers"],
            timeout_seconds=5,
        )
        for line in result.stdout.splitlines():
            lowered = line.lower()
            if "java" not in lowered:
                continue
            if any(hint in lowered for hint in self._config.minecraft.process_hints):
                return True
        return False

    def _minecraft_management_mode(self, snapshot: DiscoverySnapshot) -> str:
        return str(
            snapshot.detected_minecraft.get("management_mode")
            or snapshot.detected_minecraft.get("launch_method")
            or self._config.minecraft.management_mode
            or "auto"
        ).strip().lower()

    @staticmethod
    def _read_proc_stat() -> dict[str, int]:
        path = Path("/proc/stat")
        if not path.exists():
            return {"idle": 0, "total": 0}
        fields = path.read_text(encoding="utf-8", errors="replace").splitlines()[0].split()[1:]
        values = [int(field) for field in fields]
        return {"idle": values[3] + values[4], "total": sum(values)}

    @staticmethod
    def _first_detected_port(open_ports: list[dict[str, Any]], *, preferred: set[int]) -> int | None:
        for row in open_ports:
            port = row.get("port")
            if isinstance(port, int) and port in preferred:
                return port
        return None

    @staticmethod
    def _build_correlation_id(checked_at: str, findings: list[Finding]) -> str:
        basis = checked_at + "|" + "|".join(sorted(finding.fingerprint() for finding in findings))
        return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:12]

    @staticmethod
    def _fingerprint_from_findings(findings: list[Finding]) -> str:
        fingerprint = "|".join(sorted(finding.fingerprint() for finding in findings))
        return hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()
