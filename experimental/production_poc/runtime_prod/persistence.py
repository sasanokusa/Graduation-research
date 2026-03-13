from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from experimental.production_poc.runtime_prod.models import DiscoverySnapshot, MonitorOutcome


class StateStore:
    """Stores discovery snapshots and incident records outside the baseline flow."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.snapshots_dir = base_dir / "snapshots"
        self.incidents_dir = base_dir / "incidents"
        self.state_dir = base_dir / "state"
        for directory in (self.base_dir, self.snapshots_dir, self.incidents_dir, self.state_dir):
            directory.mkdir(parents=True, exist_ok=True)

    def save_snapshot(self, snapshot: DiscoverySnapshot, markdown_summary: str) -> dict[str, Path]:
        timestamp = snapshot.captured_at.replace(":", "").replace("+00:00", "Z")
        json_path = self.snapshots_dir / f"{timestamp}.json"
        md_path = self.snapshots_dir / f"{timestamp}.md"
        context_path = self.snapshots_dir / f"{timestamp}.context.json"
        latest_json = self.state_dir / "latest_snapshot.json"
        latest_md = self.state_dir / "latest_snapshot.md"
        latest_context = self.state_dir / "latest_context.json"
        payload = snapshot.to_dict()
        self._write_json(json_path, payload)
        md_path.write_text(markdown_summary, encoding="utf-8")
        self._write_json(context_path, snapshot.lightweight_context)
        self._write_json(latest_json, payload)
        latest_md.write_text(markdown_summary, encoding="utf-8")
        self._write_json(latest_context, snapshot.lightweight_context)
        return {"json": json_path, "markdown": md_path, "context": context_path}

    def load_latest_snapshot(self) -> dict[str, Any] | None:
        path = self.state_dir / "latest_snapshot.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def save_incident(self, outcome: MonitorOutcome) -> Path:
        path = self.incidents_dir / f"{outcome.correlation_id}.json"
        self._write_json(path, outcome.to_dict())
        self._write_json(self.state_dir / "latest_incident.json", outcome.to_dict())
        return path

    def notification_is_suppressed(self, fingerprint: str, *, checked_at_epoch: int, cooldown_seconds: int) -> bool:
        state = self._load_alert_state()
        last_seen = int(state.get(fingerprint, 0))
        if checked_at_epoch - last_seen < cooldown_seconds:
            return True
        state[fingerprint] = checked_at_epoch
        self._write_json(self.state_dir / "alert_state.json", state)
        return False

    def monitor_started(self) -> bool:
        path = self.state_dir / "monitor_started.json"
        return path.exists()

    def mark_monitor_started(self) -> None:
        self._write_json(self.state_dir / "monitor_started.json", {"started": True})

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_alert_state(self) -> dict[str, Any]:
        path = self.state_dir / "alert_state.json"
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))


def build_snapshot_markdown(snapshot: DiscoverySnapshot) -> str:
    """Human-readable discovery summary kept alongside the raw JSON snapshot."""

    disk_lines = [
        f"- {row.get('mountpoint', '?')}: {row.get('used_percent', '?')}"
        for row in snapshot.disk_usage[:6]
    ]
    return "\n".join(
        [
            "# Production PoC Startup Snapshot",
            "",
            f"- captured_at: {snapshot.captured_at}",
            f"- hostname: {snapshot.host.get('hostname', 'unknown')}",
            f"- uptime: {snapshot.host.get('uptime', 'unknown')}",
            f"- kernel: {snapshot.host.get('kernel', 'unknown')}",
            f"- web_service: {snapshot.detected_web.get('service_name') or snapshot.detected_web.get('server_type') or 'unknown'}",
            f"- minecraft_launch: {snapshot.detected_minecraft.get('launch_method', 'unknown')}",
            f"- web_health: {snapshot.inferred_health_checks.get('web', {}).get('selected_target', '')}",
            f"- minecraft_health: {snapshot.inferred_health_checks.get('minecraft', {}).get('selected_target', '')}",
            f"- memory_used_percent: {snapshot.memory_usage.get('used_percent', 'n/a')}",
            f"- cpu_used_percent: {snapshot.cpu_usage.get('used_percent', 'n/a')}",
            "- disk_usage:",
            *disk_lines,
            "",
            "## Journal Keywords",
            json.dumps(snapshot.journal_summary.get("keyword_counts", {}), ensure_ascii=False, indent=2),
        ]
    )
