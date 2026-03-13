from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class CommandPreview:
    """Display-safe command preview for notifications and audit logs."""

    args: list[str]
    summary: str
    expected_impact: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProposedAction:
    """Structured remediation candidate that can be screened by the guard."""

    kind: str
    service: str = ""
    reason: str = ""
    expected_impact: str = ""
    evidence: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class GuardedAction:
    """Guard decision for a proposed action."""

    action: ProposedAction
    risk_class: str
    allowed: bool
    executable: bool
    requires_human_approval: bool
    command_preview: CommandPreview | None
    reason: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.command_preview is None:
            payload["command_preview"] = None
        return payload


@dataclass(frozen=True)
class Finding:
    """Rule-based monitoring finding."""

    id: str
    severity: str
    service: str
    title: str
    summary: str
    evidence: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def fingerprint(self) -> str:
        return f"{self.id}:{self.service}:{self.title}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class IncidentAnalysis:
    """Analyzer output kept intentionally small for safe PoC behavior."""

    analyzer: str
    summary: str
    likely_causes: list[dict[str, Any]]
    proposed_actions: list[ProposedAction]
    escalation_reason: str = ""
    raw_response: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "analyzer": self.analyzer,
            "summary": self.summary,
            "likely_causes": self.likely_causes,
            "proposed_actions": [action.to_dict() for action in self.proposed_actions],
            "escalation_reason": self.escalation_reason,
            "raw_response": self.raw_response,
        }


@dataclass(frozen=True)
class ActionExecutionResult:
    """Audit trail for a guard-approved action execution attempt."""

    action: GuardedAction
    executed: bool
    ok: bool
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.to_dict(),
            "executed": self.executed,
            "ok": self.ok,
            "details": self.details,
        }


@dataclass(frozen=True)
class DiscoverySnapshot:
    """Structured startup snapshot used for low-cost later analysis."""

    captured_at: str
    host: dict[str, Any]
    systemd_services: list[dict[str, Any]]
    process_summary: list[dict[str, Any]]
    open_ports: list[dict[str, Any]]
    disk_usage: list[dict[str, Any]]
    memory_usage: dict[str, Any]
    cpu_usage: dict[str, Any]
    journal_summary: dict[str, Any]
    detected_web: dict[str, Any]
    detected_minecraft: dict[str, Any]
    inferred_health_checks: dict[str, Any]
    backup_status: dict[str, Any]
    lightweight_context: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MonitorOutcome:
    """Single monitor iteration result."""

    correlation_id: str
    checked_at: str
    findings: list[Finding]
    probe_details: dict[str, Any]
    related_logs: dict[str, Any]
    analysis: IncidentAnalysis | None = None
    guard_results: list[GuardedAction] = field(default_factory=list)
    execution_results: list[ActionExecutionResult] = field(default_factory=list)
    verification: dict[str, Any] = field(default_factory=dict)
    escalated: bool = False
    escalation_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "correlation_id": self.correlation_id,
            "checked_at": self.checked_at,
            "findings": [finding.to_dict() for finding in self.findings],
            "probe_details": self.probe_details,
            "related_logs": self.related_logs,
            "analysis": self.analysis.to_dict() if self.analysis else None,
            "guard_results": [result.to_dict() for result in self.guard_results],
            "execution_results": [result.to_dict() for result in self.execution_results],
            "verification": self.verification,
            "escalated": self.escalated,
            "escalation_reason": self.escalation_reason,
        }


def compact_context(snapshot: DiscoverySnapshot) -> dict[str, Any]:
    """Context intentionally kept small so it can be sent to an LLM on demand."""

    return {
        "captured_at": snapshot.captured_at,
        "host": snapshot.host,
        "detected_web": snapshot.detected_web,
        "detected_minecraft": snapshot.detected_minecraft,
        "inferred_health_checks": snapshot.inferred_health_checks,
        "top_processes": snapshot.process_summary[:5],
        "open_ports": snapshot.open_ports[:10],
        "journal_keywords": snapshot.journal_summary.get("keyword_counts", {}),
    }
