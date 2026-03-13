from experimental.production_poc.adapters.action_guard import ActionGuard
from experimental.production_poc.adapters.command_runner import CommandResult
from experimental.production_poc.runtime_prod.config import ActionsConfig
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
