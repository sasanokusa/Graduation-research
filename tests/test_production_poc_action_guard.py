from pathlib import Path

from experimental.production_poc.adapters.approval_store import FileApprovalStore, approval_id_for_action
from experimental.production_poc.adapters.action_guard import ActionGuard
from experimental.production_poc.adapters.backup_provider import LocalSnapshotBackupProvider
from experimental.production_poc.adapters.command_runner import CommandResult
from experimental.production_poc.runtime_prod.config import ActionsConfig, RunbookConfig
from experimental.production_poc.runtime_prod.models import ProposedAction


class _Runner:
    def run(self, args: list[str], *, timeout_seconds: int) -> CommandResult:
        return CommandResult(
            args=args,
            returncode=0,
            stdout="ok",
            stderr="",
            timed_out=False,
            timeout_seconds=timeout_seconds,
            duration_ms=5,
        )


def test_allowlisted_restart_is_executable_only_in_execute_mode() -> None:
    action = ProposedAction(kind="restart_service", service="nginx", reason="recover")

    guard_execute = ActionGuard(
        ActionsConfig(
            mode="execute",
            allowed_restart_services=["nginx"],
            restart_command_prefix=[],
            dangerous_action_policy="require-human-approval",
            max_auto_actions_per_incident=1,
        ),
        _Runner(),
    )
    execute_result = guard_execute.evaluate(action)
    assert execute_result.allowed is True
    assert execute_result.executable is True
    assert execute_result.risk_class == "low"

    guard_propose = ActionGuard(
        ActionsConfig(
            mode="propose-only",
            allowed_restart_services=["nginx"],
            restart_command_prefix=[],
            dangerous_action_policy="require-human-approval",
            max_auto_actions_per_incident=1,
        ),
        _Runner(),
    )
    propose_result = guard_propose.evaluate(action)
    assert propose_result.allowed is True
    assert propose_result.executable is False


def test_non_allowlisted_restart_requires_human_approval() -> None:
    guard = ActionGuard(
        ActionsConfig(
            mode="execute",
            allowed_restart_services=["nginx"],
            restart_command_prefix=[],
            dangerous_action_policy="require-human-approval",
            max_auto_actions_per_incident=1,
        ),
        _Runner(),
    )

    result = guard.evaluate(ProposedAction(kind="restart_service", service="apache2"))
    assert result.allowed is False
    assert result.requires_human_approval is True
    assert "allowed_restart_services" in result.reason


def test_read_only_action_is_allowed_in_dry_run() -> None:
    guard = ActionGuard(
        ActionsConfig(
            mode="dry-run",
            allowed_restart_services=[],
            restart_command_prefix=[],
            dangerous_action_policy="require-human-approval",
            max_auto_actions_per_incident=1,
        ),
        _Runner(),
    )
    result = guard.evaluate(ProposedAction(kind="service_status", service="nginx"))
    assert result.allowed is True
    assert result.executable is True
    assert result.risk_class == "read-only"


def test_restart_preview_can_use_sudo_prefix() -> None:
    guard = ActionGuard(
        ActionsConfig(
            mode="execute",
            allowed_restart_services=["apache2"],
            restart_command_prefix=["sudo", "-n"],
            dangerous_action_policy="require-human-approval",
            max_auto_actions_per_incident=1,
        ),
        _Runner(),
    )

    result = guard.evaluate(ProposedAction(kind="restart_service", service="apache2"))

    assert result.allowed is True
    assert result.executable is True
    assert result.command_preview is not None
    assert result.command_preview.args == ["sudo", "-n", "systemctl", "restart", "apache2"]


def test_low_risk_allowlisted_runbook_is_executable_in_execute_mode() -> None:
    guard = ActionGuard(
        ActionsConfig(
            mode="execute",
            allowed_restart_services=[],
            restart_command_prefix=[],
            dangerous_action_policy="require-human-approval",
            max_auto_actions_per_incident=1,
            allowed_runbooks={
                "reload_nginx": RunbookConfig(
                    id="reload_nginx",
                    command=["systemctl", "reload", "nginx"],
                    summary="Reload nginx",
                    expected_impact="Reloads nginx configuration without a full restart.",
                    risk_class="low",
                )
            },
        ),
        _Runner(),
    )

    result = guard.evaluate(ProposedAction(kind="runbook", metadata={"runbook_id": "reload_nginx"}))

    assert result.allowed is True
    assert result.executable is True
    assert result.risk_class == "low"
    assert result.command_preview is not None
    assert result.command_preview.args == ["systemctl", "reload", "nginx"]


def test_medium_risk_runbook_requires_fresh_backup_and_file_approval(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    approval_dir = tmp_path / "approvals"
    snapshot_dir.mkdir()
    approval_dir.mkdir()
    (snapshot_dir / "snapshot.marker").write_text("ok", encoding="utf-8")
    action = ProposedAction(kind="service_failover", metadata={"runbook_id": "failover_web"})
    config = ActionsConfig(
        mode="execute",
        allowed_restart_services=[],
        restart_command_prefix=[],
        dangerous_action_policy="require-human-approval",
        max_auto_actions_per_incident=1,
        allowed_runbooks={
            "failover_web": RunbookConfig(
                id="failover_web",
                command=["/usr/local/sbin/failover-web", "--to", "standby"],
                summary="Fail over web traffic",
                expected_impact="Switches web traffic to the preconfigured standby target.",
                risk_class="medium",
                allowed_kinds=["service_failover"],
            )
        },
        approval_dir=approval_dir,
    )

    guard_without_backup = ActionGuard(config, _Runner())
    missing_backup_result = guard_without_backup.evaluate(action)
    assert missing_backup_result.allowed is False
    assert "backup provider is not ready" in missing_backup_result.reason

    backup_provider = LocalSnapshotBackupProvider(
        snapshot_paths=[snapshot_dir],
        max_age_seconds=3600,
        minimum_count=1,
    )
    guard_without_approval = ActionGuard(
        config,
        _Runner(),
        backup_provider=backup_provider,
        approval_store=FileApprovalStore(approval_dir),
    )
    missing_approval_result = guard_without_approval.evaluate(action)
    assert missing_approval_result.allowed is False
    assert missing_approval_result.requires_human_approval is True
    assert approval_id_for_action(action) in missing_approval_result.reason

    (approval_dir / f"{approval_id_for_action(action)}.approved").write_text("approved", encoding="utf-8")
    approved_result = guard_without_approval.evaluate(action)
    assert approved_result.allowed is True
    assert approved_result.executable is True
    assert approved_result.risk_class == "medium"


def test_additional_read_only_diagnosis_action_is_allowed() -> None:
    guard = ActionGuard(
        ActionsConfig(
            mode="dry-run",
            allowed_restart_services=[],
            restart_command_prefix=[],
            dangerous_action_policy="require-human-approval",
            max_auto_actions_per_incident=1,
        ),
        _Runner(),
    )

    result = guard.evaluate(ProposedAction(kind="disk_usage_check"))

    assert result.allowed is True
    assert result.executable is True
    assert result.risk_class == "read-only"
    assert result.command_preview is not None
    assert result.command_preview.args[:2] == ["df", "-P"]
