import os
import time
from pathlib import Path

from experimental.production_poc.adapters.backup_provider import LocalSnapshotBackupProvider


def test_local_snapshot_backup_provider_reports_fresh_snapshot(tmp_path: Path) -> None:
    snapshot_dir = tmp_path / "snapshots"
    snapshot_dir.mkdir()
    (snapshot_dir / "snapshot.marker").write_text("ok", encoding="utf-8")

    status = LocalSnapshotBackupProvider(
        snapshot_paths=[snapshot_dir],
        max_age_seconds=3600,
        minimum_count=1,
    ).status()

    assert status.ready is True
    assert status.provider_name == "local-snapshot"
    assert "1/1" in status.summary


def test_local_snapshot_backup_provider_rejects_stale_snapshot(tmp_path: Path) -> None:
    snapshot_file = tmp_path / "snapshot.marker"
    snapshot_file.write_text("old", encoding="utf-8")
    stale_time = time.time() - 7200
    os.utime(snapshot_file, (stale_time, stale_time))

    status = LocalSnapshotBackupProvider(
        snapshot_paths=[snapshot_file],
        max_age_seconds=60,
        minimum_count=1,
    ).status()

    assert status.ready is False
    assert "stale" in status.summary
