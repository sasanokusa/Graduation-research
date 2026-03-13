from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol

from experimental.production_poc.runtime_prod.models import DiscoverySnapshot, MonitorOutcome


MAX_DISCORD_MESSAGE_LEN = 1900


class Notifier(Protocol):
    """Notification interface used by the orchestrator."""

    def send_startup_summary(self, snapshot: DiscoverySnapshot) -> None:
        """Send a startup summary."""

    def send_monitoring_started(self, *, host_label: str, mode: str) -> None:
        """Send a monitoring start notification."""

    def send_incident(self, outcome: MonitorOutcome, *, host_label: str, mode: str) -> None:
        """Send anomaly detection and execution outcome notifications."""


@dataclass
class DiscordWebhookNotifier:
    """Simple webhook notifier focused on readable operations messages."""

    webhook_url: str
    username: str = "infra-emergency-poc"

    def send_startup_summary(self, snapshot: DiscoverySnapshot) -> None:
        if not self.webhook_url:
            return
        detected_web = snapshot.detected_web.get("service_name") or snapshot.detected_web.get("server_type") or "unknown"
        detected_mc = snapshot.detected_minecraft.get("launch_method", "unknown")
        disk_summary = ", ".join(
            f"{row.get('mountpoint', '?')}={row.get('used_percent', '?')}"
            for row in snapshot.disk_usage[:4]
        ) or "n/a"
        summary = (
            f"[情報] 起動サマリ | ホスト={snapshot.host.get('hostname','unknown')} "
            f"| 時刻={snapshot.captured_at} | Web={detected_web} | Minecraft={detected_mc}"
        )
        detail = self._format_code_block(
            "\n".join(
                [
                    f"稼働時間: {snapshot.host.get('uptime', 'unknown')}",
                    f"ディスク: {disk_summary}",
                    f"メモリ使用率: {snapshot.memory_usage.get('used_percent', 'n/a')}",
                    f"CPU使用率: {snapshot.cpu_usage.get('used_percent', 'n/a')}",
                    f"バックアップ状態: {snapshot.backup_status.get('summary', 'unknown')}",
                ]
            )
        )
        self._send_text(summary)
        self._send_text(detail)

    def send_monitoring_started(self, *, host_label: str, mode: str) -> None:
        if not self.webhook_url:
            return
        self._send_text(f"[情報] 監視開始 | ホスト={host_label} | モード={mode}")

    def send_incident(self, outcome: MonitorOutcome, *, host_label: str, mode: str) -> None:
        if not self.webhook_url:
            return
        highest = self._severity_label(self._highest_severity(outcome))
        services = ",".join(sorted({finding.service for finding in outcome.findings if finding.service})) or "host"
        summary = (
            f"[{highest}] 障害検知 | ホスト={host_label} | 対象={services} "
            f"| 時刻={outcome.checked_at} | 相関ID={outcome.correlation_id} | モード={mode}"
        )
        summary_line = outcome.analysis.summary if outcome.analysis else "; ".join(
            finding.summary for finding in outcome.findings[:2]
        )
        self._send_text(f"{summary}\n{summary_line}")

        detail_lines = []
        for finding in outcome.findings[:4]:
            detail_lines.append(
                f"- {self._severity_label(finding.severity)}: {finding.title} ({finding.service or 'host'})"
            )
            for evidence in finding.evidence[:2]:
                detail_lines.append(f"  根拠: {evidence}")
        if outcome.analysis and outcome.analysis.likely_causes:
            detail_lines.append("原因候補:")
            for cause in outcome.analysis.likely_causes[:2]:
                detail_lines.append(
                    f"- {self._confidence_label(str(cause.get('confidence', 'unknown')))}: {cause.get('cause','')}"
                )
        for guard in outcome.guard_results[:2]:
            prefix = "承認要求" if guard.requires_human_approval else "提案操作"
            detail_lines.append(
                f"{prefix}: {guard.action.kind} service={guard.action.service or '-'} "
                f"risk={self._risk_label(guard.risk_class)} 理由={guard.reason or guard.action.reason}"
            )
        for execution in outcome.execution_results[:1]:
            detail_lines.append(f"実行結果: ok={execution.ok} kind={execution.action.action.kind}")
        if outcome.verification:
            detail_lines.append(f"検証成功: {outcome.verification.get('ok')}")
        if outcome.escalation_reason:
            detail_lines.append(f"エスカレーション: {outcome.escalation_reason}")
        if outcome.related_logs:
            excerpt = self._related_log_excerpt(outcome.related_logs)
            if excerpt:
                detail_lines.append("ログ抜粋:")
                detail_lines.extend(excerpt)
        self._send_text(self._format_code_block("\n".join(detail_lines)))

    def _send_text(self, content: str) -> None:
        trimmed = content[:MAX_DISCORD_MESSAGE_LEN]
        payload = json.dumps({"username": self.username, "content": trimmed}).encode("utf-8")
        request = urllib.request.Request(
            self.webhook_url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "infra-emergency-poc/0.1",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10):
                return
        except urllib.error.HTTPError as exc:
            body = ""
            if exc.fp is not None:
                try:
                    body = exc.fp.read(200).decode("utf-8", errors="replace").strip()
                except Exception:  # pragma: no cover - best effort diagnostics only
                    body = ""
            detail = f" | body={body}" if body else ""
            self._warn_notification_failure(f"Discord webhook returned HTTP {exc.code}: {exc.reason}{detail}")
        except Exception as exc:  # pragma: no cover - defensive runtime safeguard
            self._warn_notification_failure(f"Discord webhook send failed: {exc}")

    @staticmethod
    def _highest_severity(outcome: MonitorOutcome) -> str:
        order = {"info": 0, "warning": 1, "critical": 2}
        severity = "info"
        for finding in outcome.findings:
            if order.get(finding.severity, 0) > order.get(severity, 0):
                severity = finding.severity
        return severity

    @staticmethod
    def _format_code_block(text: str) -> str:
        return f"```text\n{text[:1700]}\n```"

    @staticmethod
    def _severity_label(value: str) -> str:
        return {
            "info": "情報",
            "warning": "警告",
            "critical": "重大",
        }.get(value, value)

    @staticmethod
    def _confidence_label(value: str) -> str:
        return {
            "low": "低",
            "medium": "中",
            "high": "高",
        }.get(value, value)

    @staticmethod
    def _risk_label(value: str) -> str:
        return {
            "read-only": "読み取り専用",
            "low": "低",
            "medium": "中",
            "high": "高",
            "blocked": "禁止",
        }.get(value, value)

    @staticmethod
    def _related_log_excerpt(related_logs: dict[str, object]) -> list[str]:
        excerpt: list[str] = []
        for key, value in related_logs.items():
            if isinstance(value, list):
                excerpt.extend(f"{key}: {line}" for line in value[:4])
            elif isinstance(value, dict):
                for inner_key, inner_value in value.items():
                    if isinstance(inner_value, list):
                        excerpt.extend(f"{inner_key}: {line}" for line in inner_value[:2])
                    elif isinstance(inner_value, str) and inner_value:
                        excerpt.append(f"{inner_key}: {inner_value[:160]}")
            if len(excerpt) >= 8:
                break
        return excerpt[:8]

    @staticmethod
    def _warn_notification_failure(message: str) -> None:
        print(f"[production_poc] {message}", file=sys.stderr)


class NullNotifier:
    """No-op notifier used when webhook configuration is absent."""

    def send_startup_summary(self, snapshot: DiscoverySnapshot) -> None:
        return

    def send_monitoring_started(self, *, host_label: str, mode: str) -> None:
        return

    def send_incident(self, outcome: MonitorOutcome, *, host_label: str, mode: str) -> None:
        return


def build_notifier(webhook_url: str, *, username: str) -> Notifier:
    if webhook_url:
        return DiscordWebhookNotifier(webhook_url=webhook_url, username=username)
    return NullNotifier()
