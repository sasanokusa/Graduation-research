from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Protocol


@dataclass(frozen=True)
class BackupStatus:
    """Small status object surfaced in startup summaries and escalations."""

    provider_name: str
    ready: bool
    summary: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class BackupProvider(Protocol):
    """Future-facing snapshot interface kept separate from the PoC runner."""

    def status(self) -> BackupStatus:
        """Report whether snapshots are available before risky actions."""


class NullBackupProvider:
    """Default provider used while backup automation is not yet available."""

    def status(self) -> BackupStatus:
        return BackupStatus(
            provider_name="none",
            ready=False,
            summary="No snapshot or backup provider configured. Only low-risk allowlisted actions should run.",
        )
