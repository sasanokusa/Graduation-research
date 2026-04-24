from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from experimental.production_poc.runtime_prod.config import BackupConfig


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


class LocalSnapshotBackupProvider:
    """Checks local snapshot markers before medium-risk actions are allowed."""

    def __init__(self, *, snapshot_paths: list[Path], max_age_seconds: int, minimum_count: int = 1) -> None:
        self._snapshot_paths = snapshot_paths
        self._max_age_seconds = max_age_seconds
        self._minimum_count = max(1, minimum_count)

    def status(self) -> BackupStatus:
        if not self._snapshot_paths:
            return BackupStatus(
                provider_name="local-snapshot",
                ready=False,
                summary="No snapshot_paths configured for the local snapshot provider.",
            )

        ready_count = 0
        details: list[str] = []
        now = time.time()
        for path in self._snapshot_paths:
            try:
                snapshot_mtime = self._newest_snapshot_mtime(path)
            except OSError as exc:
                details.append(f"{path}: unreadable {exc.__class__.__name__}")
                continue
            if snapshot_mtime is None:
                details.append(f"{path}: missing or empty")
                continue
            age_seconds = int(now - snapshot_mtime)
            if age_seconds <= self._max_age_seconds:
                ready_count += 1
                details.append(f"{path}: ready age_seconds={age_seconds}")
            else:
                details.append(f"{path}: stale age_seconds={age_seconds}")

        ready = ready_count >= self._minimum_count
        return BackupStatus(
            provider_name="local-snapshot",
            ready=ready,
            summary=(
                f"{ready_count}/{len(self._snapshot_paths)} configured snapshot locations are fresh "
                f"(minimum_count={self._minimum_count}, max_age_seconds={self._max_age_seconds}). "
                + "; ".join(details[:4])
            ),
        )

    @staticmethod
    def _newest_snapshot_mtime(path: Path) -> float | None:
        if not path.exists():
            return None
        if path.is_file():
            return path.stat().st_mtime
        candidates = [item for item in path.iterdir() if item.exists()]
        if not candidates:
            return None
        return max(item.stat().st_mtime for item in candidates)


def build_backup_provider(config: BackupConfig) -> BackupProvider:
    if config.provider in {"local-snapshot", "filesystem", "local"}:
        return LocalSnapshotBackupProvider(
            snapshot_paths=config.snapshot_paths,
            max_age_seconds=config.max_age_seconds,
            minimum_count=config.minimum_count,
        )
    return NullBackupProvider()
