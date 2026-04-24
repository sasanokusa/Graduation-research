from __future__ import annotations

from dataclasses import asdict
from experimental.production_poc.adapters.approval_store import ApprovalStore, NullApprovalStore
from experimental.production_poc.adapters.backup_provider import BackupProvider, NullBackupProvider
from experimental.production_poc.adapters.command_runner import CommandRunner
from experimental.production_poc.runtime_prod.config import ActionsConfig, RunbookConfig
from experimental.production_poc.runtime_prod.models import (
    ActionExecutionResult,
    CommandPreview,
    GuardedAction,
    ProposedAction,
)


READ_ONLY_KINDS = {
    "service_status",
    "service_active_check",
    "service_logs",
    "http_health_check",
    "tcp_port_check",
    "listen_port_check",
    "disk_usage_check",
    "memory_pressure_check",
    "failed_units_check",
    "journal_keyword_search",
    "file_stat",
}

RUNBOOK_BACKED_KINDS = {
    "runbook",
    "service_failover",
    "config_toggle_rollback",
    "dependency_rollback",
}
RISK_CLASSES = {"read-only", "low", "medium", "blocked"}


class ActionGuard:
    """Enforces the production PoC allowlist and execution safety policy."""

    def __init__(
        self,
        config: ActionsConfig,
        runner: CommandRunner,
        *,
        command_timeout_seconds: int = 15,
        backup_provider: BackupProvider | None = None,
        approval_store: ApprovalStore | None = None,
    ) -> None:
        self._config = config
        self._runner = runner
        self._command_timeout_seconds = command_timeout_seconds
        self._backup_provider = backup_provider or NullBackupProvider()
        self._approval_store = approval_store or NullApprovalStore()

    def evaluate(self, action: ProposedAction) -> GuardedAction:
        if action.kind in READ_ONLY_KINDS:
            preview = self._preview_for(action)
            return GuardedAction(
                action=action,
                risk_class="read-only",
                allowed=preview is not None,
                executable=preview is not None,
                requires_human_approval=False,
                command_preview=preview,
                reason="" if preview is not None else "unsupported read-only action payload",
            )

        if action.kind in RUNBOOK_BACKED_KINDS:
            return self._evaluate_runbook_backed_action(action)

        if action.kind == "restart_service":
            preview = self._preview_for(action)
            if preview is None:
                return GuardedAction(
                    action=action,
                    risk_class="blocked",
                    allowed=False,
                    executable=False,
                    requires_human_approval=True,
                    command_preview=None,
                    reason="restart_service requires a concrete service name",
                )
            if action.service not in self._config.allowed_restart_services:
                return GuardedAction(
                    action=action,
                    risk_class="medium",
                    allowed=False,
                    executable=False,
                    requires_human_approval=True,
                    command_preview=preview,
                    reason=f"service {action.service} is not present in allowed_restart_services",
                )
            return GuardedAction(
                action=action,
                risk_class="low",
                allowed=True,
                executable=self._config.mode == "execute",
                requires_human_approval=False,
                command_preview=preview,
                reason=(
                    ""
                    if self._config.mode == "execute"
                    else f"execution mode is {self._config.mode}; action will be proposed but not executed"
                ),
            )

        return GuardedAction(
            action=action,
            risk_class="blocked",
            allowed=False,
            executable=False,
            requires_human_approval=True,
            command_preview=None,
            reason=f"unsupported action kind: {action.kind}",
        )

    def _evaluate_runbook_backed_action(self, action: ProposedAction) -> GuardedAction:
        runbook_id = self._runbook_id_for(action)
        if not runbook_id:
            return self._blocked(action, f"{action.kind} requires metadata.runbook_id")
        runbook = self._config.allowed_runbooks.get(runbook_id)
        if runbook is None:
            return self._blocked(action, f"runbook {runbook_id} is not present in allowed_runbooks")
        if action.kind not in runbook.allowed_kinds:
            return self._blocked(action, f"runbook {runbook_id} does not allow action kind {action.kind}")

        risk_class = runbook.risk_class if runbook.risk_class in RISK_CLASSES else "blocked"
        if risk_class == "blocked":
            return self._blocked(action, f"runbook {runbook_id} is configured as blocked or has an invalid risk_class")

        preview = self._preview_for_runbook(runbook)
        if risk_class == "medium":
            backup_status = self._backup_provider.status()
            if not backup_status.ready:
                return GuardedAction(
                    action=action,
                    risk_class="medium",
                    allowed=False,
                    executable=False,
                    requires_human_approval=True,
                    command_preview=preview,
                    reason=f"backup provider is not ready for medium-risk action: {backup_status.summary}",
                )
            approval = self._approval_store.check(action)
            if not approval.approved:
                return GuardedAction(
                    action=action,
                    risk_class="medium",
                    allowed=False,
                    executable=False,
                    requires_human_approval=True,
                    command_preview=preview,
                    reason=approval.reason,
                )

        return GuardedAction(
            action=action,
            risk_class=risk_class,
            allowed=True,
            executable=self._config.mode == "execute",
            requires_human_approval=False,
            command_preview=preview,
            reason=(
                ""
                if self._config.mode == "execute"
                else f"execution mode is {self._config.mode}; action will be proposed but not executed"
            ),
        )

    def execute(self, guarded: GuardedAction) -> ActionExecutionResult:
        if not guarded.allowed or not guarded.executable or guarded.command_preview is None:
            return ActionExecutionResult(
                action=guarded,
                executed=False,
                ok=False,
                details={
                    "reason": guarded.reason or "action is not executable under the current policy",
                    "mode": self._config.mode,
                },
            )
        result = self._runner.run(guarded.command_preview.args, timeout_seconds=self._command_timeout_seconds)
        return ActionExecutionResult(
            action=guarded,
            executed=True,
            ok=result.ok,
            details=asdict(result),
        )

    def evaluate_all(self, actions: list[ProposedAction]) -> list[GuardedAction]:
        return [self.evaluate(action) for action in actions]

    @staticmethod
    def first_executable(actions: list[GuardedAction]) -> GuardedAction | None:
        for action in actions:
            if action.allowed and action.executable:
                return action
        return None

    @staticmethod
    def _runbook_id_for(action: ProposedAction) -> str:
        return str(action.metadata.get("runbook_id", "")).strip()

    @staticmethod
    def _preview_for_runbook(runbook: RunbookConfig) -> CommandPreview:
        return CommandPreview(
            args=runbook.command,
            summary=runbook.summary,
            expected_impact=runbook.expected_impact,
        )

    @staticmethod
    def _blocked(action: ProposedAction, reason: str) -> GuardedAction:
        return GuardedAction(
            action=action,
            risk_class="blocked",
            allowed=False,
            executable=False,
            requires_human_approval=True,
            command_preview=None,
            reason=reason,
        )

    def _preview_for(self, action: ProposedAction) -> CommandPreview | None:
        service = action.service.strip()
        if action.kind == "restart_service" and service:
            args = [*self._config.restart_command_prefix, "systemctl", "restart", service]
            prefix_summary = " via command prefix" if self._config.restart_command_prefix else ""
            return CommandPreview(
                args=args,
                summary=f"Restart allowlisted service {service}{prefix_summary}",
                expected_impact=action.expected_impact or "Service restart may restore a stopped but otherwise healthy process.",
            )
        if action.kind == "service_status" and service:
            return CommandPreview(
                args=["systemctl", "status", service, "--no-pager", "--lines=25"],
                summary=f"Inspect systemd status for {service}",
                expected_impact="Read-only diagnostic command.",
            )
        if action.kind == "service_active_check" and service:
            return CommandPreview(
                args=["systemctl", "is-active", service],
                summary=f"Check active state for {service}",
                expected_impact="Read-only diagnostic command.",
            )
        if action.kind == "service_logs" and service:
            lines = str(action.metadata.get("lines", 40))
            return CommandPreview(
                args=["journalctl", "-u", service, "-n", lines, "--no-pager"],
                summary=f"Collect recent journal logs for {service}",
                expected_impact="Read-only diagnostic command.",
            )
        if action.kind == "listen_port_check":
            port = action.metadata.get("port")
            if port:
                return CommandPreview(
                    args=["ss", "-ltnpH"],
                    summary=f"Check whether port {port} is listening",
                    expected_impact="Read-only diagnostic command.",
                )
        if action.kind == "http_health_check":
            url = str(action.metadata.get("url", "")).strip()
            if url:
                return CommandPreview(
                    args=["curl", "--fail", "--silent", "--show-error", "--max-time", "5", url],
                    summary=f"Probe HTTP health endpoint {url}",
                    expected_impact="Read-only diagnostic command.",
                )
        if action.kind == "tcp_port_check":
            host = str(action.metadata.get("host", "127.0.0.1"))
            port = action.metadata.get("port")
            if port:
                return CommandPreview(
                    args=["python3", "-c", f"import socket; socket.create_connection(('{host}', {int(port)}), 5).close()"],
                    summary=f"Check TCP connectivity to {host}:{port}",
                    expected_impact="Read-only diagnostic command.",
                )
        if action.kind == "disk_usage_check":
            return CommandPreview(
                args=["df", "-P", "-x", "tmpfs", "-x", "devtmpfs"],
                summary="Check filesystem usage",
                expected_impact="Read-only diagnostic command.",
            )
        if action.kind == "memory_pressure_check":
            return CommandPreview(
                args=["cat", "/proc/meminfo"],
                summary="Inspect kernel memory counters",
                expected_impact="Read-only diagnostic command.",
            )
        if action.kind == "failed_units_check":
            return CommandPreview(
                args=["systemctl", "--failed", "--no-legend", "--plain"],
                summary="List failed systemd units",
                expected_impact="Read-only diagnostic command.",
            )
        if action.kind == "journal_keyword_search":
            minutes = self._int_metadata(action, "lookback_minutes", 15)
            lines = str(action.metadata.get("lines", 80))
            return CommandPreview(
                args=["journalctl", "--since", f"-{minutes}m", "--no-pager", "-n", lines],
                summary="Collect recent journal lines for keyword review",
                expected_impact="Read-only diagnostic command.",
            )
        if action.kind == "file_stat":
            path = str(action.metadata.get("path", "")).strip()
            if path:
                return CommandPreview(
                    args=["stat", "--", path],
                    summary=f"Inspect file metadata for {path}",
                    expected_impact="Read-only diagnostic command.",
                )
        return None

    @staticmethod
    def _int_metadata(action: ProposedAction, key: str, default: int) -> int:
        try:
            return int(action.metadata.get(key, default))
        except (TypeError, ValueError):
            return default
