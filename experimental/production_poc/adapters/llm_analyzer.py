from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from importlib import import_module
from typing import Any, Protocol

from experimental.production_poc.runtime_prod.config import LlmConfig
from experimental.production_poc.runtime_prod.models import IncidentAnalysis, ProposedAction


SUPPORTED_ACTION_KINDS = {
    "restart_service",
    "service_status",
    "service_active_check",
    "service_logs",
    "http_health_check",
    "tcp_port_check",
    "listen_port_check",
}


class IncidentAnalyzer(Protocol):
    """Pluggable analyzer used by the single-agent production flow."""

    def analyze(self, incident_context: dict[str, Any]) -> IncidentAnalysis:
        """Analyze an anomaly and propose safe next steps."""


def build_incident_analyzer(config: LlmConfig) -> IncidentAnalyzer:
    fallback = RuleBasedIncidentAnalyzer()
    if not config.enabled:
        return fallback
    return LangChainIncidentAnalyzer(config=config, fallback=fallback)


class RuleBasedIncidentAnalyzer:
    """Cheap fallback used when LLM access is disabled or unavailable."""

    def analyze(self, incident_context: dict[str, Any]) -> IncidentAnalysis:
        findings = incident_context.get("findings", [])
        detected_web = incident_context.get("snapshot_context", {}).get("detected_web", {})
        detected_minecraft = incident_context.get("snapshot_context", {}).get("detected_minecraft", {})
        likely_causes: list[dict[str, Any]] = []
        proposed_actions: list[ProposedAction] = []

        for finding in findings:
            finding_id = str(finding.get("id", ""))
            title = str(finding.get("title", ""))
            evidence = list(finding.get("evidence") or [])
            if finding_id in {"web_service_inactive", "web_http_failed", "web_listen_missing"}:
                likely_causes.append(
                    {
                        "cause": "The local web service appears unavailable or is no longer listening on its expected path.",
                        "confidence": "medium",
                        "evidence": evidence[:3],
                    }
                )
                service_name = str(detected_web.get("service_name", "")).strip()
                if service_name:
                    proposed_actions.append(
                        ProposedAction(
                            kind="restart_service",
                            service=service_name,
                            reason=f"{title} suggests the web service may be recoverable with a restart.",
                            expected_impact="Restarts the allowlisted web service if execute mode is enabled.",
                            evidence=evidence[:3],
                        )
                    )
            elif finding_id in {"minecraft_process_missing", "minecraft_port_failed"}:
                likely_causes.append(
                    {
                        "cause": "The Minecraft server process or listener appears to have stopped unexpectedly.",
                        "confidence": "medium",
                        "evidence": evidence[:3],
                    }
                )
                service_name = str(detected_minecraft.get("service_name", "")).strip()
                if service_name:
                    proposed_actions.append(
                        ProposedAction(
                            kind="restart_service",
                            service=service_name,
                            reason=f"{title} suggests the Minecraft service may be recoverable with a restart.",
                            expected_impact="Restarts the allowlisted Minecraft service if execute mode is enabled.",
                            evidence=evidence[:3],
                        )
                    )
            elif finding_id in {"disk_pressure", "memory_pressure", "systemd_failed", "journal_critical"}:
                likely_causes.append(
                    {
                        "cause": "A host-level issue is present. Automatic recovery remains intentionally conservative.",
                        "confidence": "high",
                        "evidence": evidence[:3],
                    }
                )

        if not likely_causes:
            likely_causes.append(
                {
                    "cause": "The anomaly did not match a safe auto-remediation pattern.",
                    "confidence": "low",
                    "evidence": [],
                }
            )

        summary = "; ".join(str(finding.get("summary", "")) for finding in findings[:3]) or "No findings detected."
        escalation_reason = ""
        if not proposed_actions:
            escalation_reason = "No low-risk allowlisted action was derived from the current findings."

        return IncidentAnalysis(
            analyzer="rule_based",
            summary=summary,
            likely_causes=likely_causes,
            proposed_actions=proposed_actions[:2],
            escalation_reason=escalation_reason,
            raw_response="",
        )


@dataclass
class _AnalyzerClient:
    client: Any | None
    error: str = ""


class LangChainIncidentAnalyzer:
    """Optional LLM-backed analyzer that only runs after an anomaly occurs."""

    def __init__(self, *, config: LlmConfig, fallback: IncidentAnalyzer) -> None:
        self._config = config
        self._fallback = fallback
        self._client = self._build_client()

    def analyze(self, incident_context: dict[str, Any]) -> IncidentAnalysis:
        if self._client.client is None:
            fallback = self._fallback.analyze(incident_context)
            return IncidentAnalysis(
                analyzer=f"{fallback.analyzer}_fallback",
                summary=fallback.summary,
                likely_causes=fallback.likely_causes,
                proposed_actions=fallback.proposed_actions,
                escalation_reason=self._client.error or fallback.escalation_reason,
                raw_response="",
            )

        prompt = self._build_prompt(incident_context)
        try:
            response = self._client.client.invoke(prompt)
            raw_text = self._response_text(response)
            parsed = self._parse_json_payload(raw_text)
            return IncidentAnalysis(
                analyzer=f"llm:{self._config.provider}",
                summary=str(parsed.get("summary", "")).strip() or "LLM returned no summary.",
                likely_causes=list(parsed.get("likely_causes") or []),
                proposed_actions=self._normalize_actions(parsed.get("proposed_actions") or []),
                escalation_reason=str(parsed.get("escalation_reason", "")).strip(),
                raw_response=raw_text[:4000],
            )
        except Exception as exc:
            fallback = self._fallback.analyze(incident_context)
            return IncidentAnalysis(
                analyzer=f"{fallback.analyzer}_fallback",
                summary=fallback.summary,
                likely_causes=fallback.likely_causes,
                proposed_actions=fallback.proposed_actions,
                escalation_reason=f"LLM analysis failed: {exc}",
                raw_response="",
            )

    def _build_client(self) -> _AnalyzerClient:
        api_key = os.getenv(self._config.api_key_env, "").strip()
        if not api_key:
            return _AnalyzerClient(client=None, error=f"{self._config.api_key_env} is not set")
        try:
            if self._config.provider == "openai":
                module = import_module("langchain_openai")
                client = module.ChatOpenAI(
                    model=self._config.model,
                    api_key=api_key,
                    temperature=0,
                    timeout=self._config.timeout_seconds,
                    max_retries=0,
                )
            elif self._config.provider == "anthropic":
                module = import_module("langchain_anthropic")
                client = module.ChatAnthropic(
                    model=self._config.model,
                    api_key=api_key,
                    temperature=0,
                    timeout=self._config.timeout_seconds,
                    max_retries=0,
                )
            elif self._config.provider == "google":
                module = import_module("langchain_google_genai")
                client = module.ChatGoogleGenerativeAI(
                    model=self._config.model,
                    google_api_key=api_key,
                    temperature=0,
                    timeout=self._config.timeout_seconds,
                    max_retries=0,
                    response_mime_type="application/json",
                    transport="rest",
                )
            else:
                return _AnalyzerClient(client=None, error=f"unsupported LLM provider: {self._config.provider}")
            return _AnalyzerClient(client=client)
        except Exception as exc:
            return _AnalyzerClient(client=None, error=str(exc))

    def _build_prompt(self, incident_context: dict[str, Any]) -> str:
        filtered_logs = self._truncate_logs(incident_context.get("related_logs", {}))
        payload = {
            "snapshot_context": incident_context.get("snapshot_context", {}),
            "findings": incident_context.get("findings", []),
            "probe_details": incident_context.get("probe_details", {}),
            "related_logs": filtered_logs,
        }
        return (
            "You are a cautious incident triage assistant for a personal Ubuntu server.\n"
            "Return JSON only.\n"
            "Never suggest package upgrades, file edits, firewall changes, reboot, chmod, chown, rm, database changes, or arbitrary shell.\n"
            "Use only these action kinds when strictly justified: "
            + ", ".join(sorted(SUPPORTED_ACTION_KINDS))
            + ".\n"
            "If no safe action fits, return an empty proposed_actions list and explain the escalation_reason.\n"
            "Output schema:\n"
            '{"summary":"...","likely_causes":[{"cause":"...","confidence":"low|medium|high","evidence":["..."]}],"proposed_actions":[{"kind":"restart_service","service":"nginx","reason":"...","expected_impact":"...","evidence":["..."],"metadata":{}}],"escalation_reason":"..."}\n'
            "Incident context:\n"
            + json.dumps(payload, ensure_ascii=False, indent=2)
        )

    def _truncate_logs(self, related_logs: dict[str, Any]) -> dict[str, Any]:
        limit = self._config.max_context_lines
        filtered: dict[str, Any] = {}
        for key, value in related_logs.items():
            if isinstance(value, list):
                filtered[key] = value[-limit:]
            elif isinstance(value, dict):
                filtered[key] = {
                    inner_key: inner_value[-limit:] if isinstance(inner_value, list) else inner_value
                    for inner_key, inner_value in value.items()
                }
            else:
                filtered[key] = value
        return filtered

    @staticmethod
    def _response_text(response: Any) -> str:
        content = getattr(response, "content", response)
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            fragments: list[str] = []
            for item in content:
                if isinstance(item, dict) and "text" in item:
                    fragments.append(str(item["text"]))
                else:
                    fragments.append(str(item))
            return "\n".join(fragments)
        return str(content)

    @staticmethod
    def _parse_json_payload(text: str) -> dict[str, Any]:
        cleaned = text.strip()
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            raise ValueError("LLM did not return a JSON object")
        payload = json.loads(match.group(0))
        if not isinstance(payload, dict):
            raise ValueError("LLM JSON payload must be an object")
        return payload

    @staticmethod
    def _normalize_actions(raw_actions: list[Any]) -> list[ProposedAction]:
        actions: list[ProposedAction] = []
        for item in raw_actions:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind", "")).strip()
            if kind not in SUPPORTED_ACTION_KINDS:
                continue
            actions.append(
                ProposedAction(
                    kind=kind,
                    service=str(item.get("service", "")).strip(),
                    reason=str(item.get("reason", "")).strip(),
                    expected_impact=str(item.get("expected_impact", "")).strip(),
                    evidence=list(item.get("evidence") or []),
                    metadata=dict(item.get("metadata") or {}),
                )
            )
        return actions[:2]
