"""LLM-based triage agent that replaces the rule-based _rank_domains()."""

from __future__ import annotations

import json
import time
from typing import Any

from core.agent_factory import build_chat_model_binding
from core.agent_roles import AgentRole
from core.llm_usage import extract_token_usage

VALID_DOMAIN_KEYS = [
    "reverse_proxy_or_upstream_mismatch",
    "app_startup_or_dependency_failure",
    "app_config_or_env_mismatch",
    "database_auth_or_connectivity_issue",
    "query_or_code_bug",
    "schema_drift",
    "healthcheck_only_failure",
    "ambiguous_service_disagreement",
    "topology_or_service_discovery_fault",
    "failover_contract_mismatch",
    "degraded_mode_leak",
    "unknown",
]

TRIAGE_SYSTEM_PROMPT = (
    "You are an SRE triage agent for a Docker Compose service stack "
    "(nginx reverse proxy -> FastAPI app -> MySQL database plus cache, queue, worker, and metrics services). "
    "Your job is to rank the most likely fault domains given the observation evidence.\n\n"
    "Available fault domain keys (use ONLY these exact strings):\n"
    + "\n".join(f"- {key}" for key in VALID_DOMAIN_KEYS)
    + "\n\n"
    "Return a JSON array of objects, each with:\n"
    '  {"domain": "<key>", "confidence": <0.0-1.0>, "evidence": ["<reason>"]}\n\n'
    "Order by confidence descending. Only include domains with confidence > 0.\n"
    "Reason only from the provided evidence. Do not assume hidden labels.\n"
    "Return ONLY the JSON array, no surrounding text."
)


def _build_triage_user_prompt(observation: dict[str, Any]) -> str:
    context: dict[str, Any] = {}

    health_checks = observation.get("health_checks", {})
    context["healthz_status"] = health_checks.get("healthz", {}).get("status")
    context["api_items_status"] = health_checks.get("api_items", {}).get("status")
    if health_checks.get("topology"):
        context["topology_check"] = health_checks.get("topology")

    http_error_evidence = observation.get("http_error_evidence", {})
    if http_error_evidence:
        context["http_error_evidence"] = http_error_evidence

    suspicious_patterns = observation.get("suspicious_patterns", {})
    active_patterns = {k: v for k, v in suspicious_patterns.items() if v}
    if active_patterns:
        context["suspicious_patterns"] = active_patterns

    file_snippets = observation.get("file_snippets", {})
    if file_snippets:
        context["file_snippets"] = file_snippets

    log_excerpts = observation.get("relevant_log_excerpts", {})
    active_excerpts = {k: v for k, v in log_excerpts.items() if v}
    if active_excerpts:
        context["relevant_log_excerpts"] = active_excerpts

    static_obs = observation.get("static_observations", {})
    if static_obs:
        context["static_observations"] = static_obs

    current_evidence = observation.get("current_state_evidence", [])
    if current_evidence:
        context["current_state_evidence"] = current_evidence

    historical_evidence = observation.get("historical_evidence", [])
    if historical_evidence:
        context["historical_evidence"] = historical_evidence

    return (
        "Rank fault domains for the following observation.\n"
        + json.dumps(context, ensure_ascii=False, indent=2)
    )


def parse_triage_llm_output(text: str) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        start = 1 if lines[0].startswith("```") else 0
        end = len(lines)
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].strip() == "```":
                end = i
                break
        text = "\n".join(lines[start:end])

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        errors.append(f"triage LLM output is not valid JSON: {exc}")
        return [], errors

    if not isinstance(payload, list):
        errors.append("triage LLM output is not a JSON array")
        return [], errors

    ranked: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            errors.append(f"triage LLM output contains a non-object item: {item}")
            continue
        domain = str(item.get("domain", "")).strip()
        if domain not in VALID_DOMAIN_KEYS:
            errors.append(f"unknown domain key: {domain}")
            continue
        confidence = item.get("confidence", 0.0)
        if not isinstance(confidence, (int, float)):
            confidence = 0.0
        confidence = max(0.0, min(1.0, float(confidence)))
        evidence = item.get("evidence", [])
        if not isinstance(evidence, list):
            evidence = [str(evidence)]
        ranked.append({
            "domain": domain,
            "confidence": confidence,
            "evidence": [str(e) for e in evidence],
        })

    ranked.sort(key=lambda x: x["confidence"], reverse=True)
    return ranked, errors


def rank_domains_llm(observation: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Call the LLM to rank fault domains. Returns (ranked_domains, metadata)."""
    binding = build_chat_model_binding(AgentRole.TRIAGE)
    settings = binding.settings
    metadata: dict[str, Any] = {
        "provider": settings.provider,
        "model": settings.model,
        "fallback_used": False,
        "error": "",
    }

    if binding.client is None:
        metadata["error"] = binding.initialization_error_message
        metadata["fallback_used"] = True
        return [], metadata

    last_error = ""
    for attempt in range(1, settings.max_attempts + 1):
        try:
            print(
                f"[triage_agent] invoking {settings.provider}/{settings.model} "
                f"attempt={attempt}/{settings.max_attempts} timeout={settings.timeout_seconds}s"
            )
            response = binding.client.invoke([
                ("system", TRIAGE_SYSTEM_PROMPT),
                ("human", _build_triage_user_prompt(observation)),
            ])
            raw = response.content if isinstance(response.content, str) else str(response.content)
            metadata["raw_output"] = raw
            metadata["token_usage"] = extract_token_usage(response)
            ranked, parse_errors = parse_triage_llm_output(raw)
            if parse_errors:
                metadata["parse_errors"] = parse_errors
            if ranked:
                return ranked, metadata
            last_error = "; ".join(parse_errors) if parse_errors else "empty ranking"
        except Exception as exc:
            last_error = str(exc)
            if attempt < settings.max_attempts:
                time.sleep(min(settings.backoff_cap_seconds, settings.backoff_base_seconds * attempt))

    metadata["error"] = last_error
    metadata["fallback_used"] = True
    return [], metadata
