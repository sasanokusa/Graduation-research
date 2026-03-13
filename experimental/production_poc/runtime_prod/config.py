from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

try:
    from dotenv import load_dotenv
except ModuleNotFoundError:  # pragma: no cover - fallback for minimal test environments
    def load_dotenv(*args: object, **kwargs: object) -> bool:
        return False


DEFAULT_WEB_SYSTEMD_CANDIDATES = ["nginx", "apache2", "caddy"]
DEFAULT_WEB_HEALTH_URLS = [
    "http://127.0.0.1/healthz",
    "http://127.0.0.1/",
    "http://localhost/healthz",
    "http://localhost/",
]
DEFAULT_WEB_ACCESS_LOGS = [
    "/var/log/nginx/access.log",
    "/var/log/apache2/access.log",
    "/var/log/caddy/access.log",
]
DEFAULT_WEB_ERROR_LOGS = [
    "/var/log/nginx/error.log",
    "/var/log/apache2/error.log",
    "/var/log/caddy/error.log",
]
DEFAULT_MINECRAFT_LOGS = [
    "/opt/minecraft/logs/latest.log",
    "/srv/minecraft/logs/latest.log",
    "/var/log/minecraft/latest.log",
]
DEFAULT_MINECRAFT_HINTS = [
    "minecraft",
    "paper",
    "spigot",
    "forge",
    "fabric",
    "server.jar",
]


def _to_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_path_list(values: Any, *, base_dir: Path) -> list[Path]:
    if not isinstance(values, list):
        return []
    resolved: list[Path] = []
    for value in values:
        if not value:
            continue
        path = Path(str(value))
        resolved.append(path if path.is_absolute() else (base_dir / path).resolve())
    return resolved


def _expand_env_in_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _expand_env_in_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand_env_in_value(item) for item in value]
    if not isinstance(value, str):
        return value

    def _replace(match: re.Match[str]) -> str:
        return os.getenv(match.group(1), "")

    return re.sub(r"\$\{([A-Z0-9_]+)\}", _replace, value)


@dataclass(frozen=True)
class HostConfig:
    host_label: str
    state_dir: Path
    snapshot_refresh_seconds: int


@dataclass(frozen=True)
class MonitoringConfig:
    poll_interval_seconds: int
    journal_lookback_minutes: int
    disk_percent_threshold: int
    memory_percent_threshold: int
    cpu_percent_threshold: int
    web_5xx_threshold: int
    anomaly_cooldown_seconds: int
    max_related_log_lines: int
    journal_keywords: list[str]


@dataclass(frozen=True)
class WebServiceConfig:
    service_name: str
    port: int | None
    tcp_host: str
    health_urls: list[str]
    access_log_paths: list[Path]
    error_log_paths: list[Path]
    systemd_candidates: list[str]


@dataclass(frozen=True)
class MinecraftServiceConfig:
    service_name: str
    port: int
    tcp_host: str
    log_paths: list[Path]
    process_hints: list[str]


@dataclass(frozen=True)
class ActionsConfig:
    mode: str
    allowed_restart_services: list[str]
    dangerous_action_policy: str
    max_auto_actions_per_incident: int


@dataclass(frozen=True)
class NotificationConfig:
    discord_webhook_url: str
    username: str
    send_startup_summary: bool
    send_monitoring_started: bool


@dataclass(frozen=True)
class LlmConfig:
    enabled: bool
    provider: str
    model: str
    timeout_seconds: int
    api_key_env: str
    max_context_lines: int


@dataclass(frozen=True)
class EscalationConfig:
    require_human_for_medium_risk: bool
    notify_on_verification_failure: bool


@dataclass(frozen=True)
class ProductionPocConfig:
    path: Path
    host: HostConfig
    monitoring: MonitoringConfig
    web: WebServiceConfig
    minecraft: MinecraftServiceConfig
    actions: ActionsConfig
    notifications: NotificationConfig
    llm: LlmConfig
    escalation: EscalationConfig


def load_config(config_path: str | Path, *, env_file: str | Path | None = None) -> ProductionPocConfig:
    """Load the isolated production PoC configuration from YAML."""

    config_path = Path(config_path).resolve()
    if env_file:
        load_dotenv(Path(env_file).resolve(), override=False)

    raw_payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    payload = _expand_env_in_value(raw_payload)
    base_dir = config_path.parent

    host_payload = payload.get("host", {})
    monitoring_payload = payload.get("monitoring", {})
    web_payload = payload.get("services", {}).get("web", {})
    minecraft_payload = payload.get("services", {}).get("minecraft", {})
    action_payload = payload.get("actions", {})
    notification_payload = payload.get("notifications", {})
    llm_payload = payload.get("llm", {})
    escalation_payload = payload.get("escalation", {})

    host = HostConfig(
        host_label=str(host_payload.get("host_label") or os.getenv("HOSTNAME", "unknown-host")),
        state_dir=(base_dir / str(host_payload.get("state_dir", "../../results/production_poc"))).resolve()
        if not Path(str(host_payload.get("state_dir", "../../results/production_poc"))).is_absolute()
        else Path(str(host_payload.get("state_dir", "../../results/production_poc"))),
        snapshot_refresh_seconds=_to_int(host_payload.get("snapshot_refresh_seconds"), 21600),
    )
    monitoring = MonitoringConfig(
        poll_interval_seconds=_to_int(monitoring_payload.get("poll_interval_seconds"), 60),
        journal_lookback_minutes=_to_int(monitoring_payload.get("journal_lookback_minutes"), 15),
        disk_percent_threshold=_to_int(monitoring_payload.get("disk_percent_threshold"), 90),
        memory_percent_threshold=_to_int(monitoring_payload.get("memory_percent_threshold"), 90),
        cpu_percent_threshold=_to_int(monitoring_payload.get("cpu_percent_threshold"), 95),
        web_5xx_threshold=_to_int(monitoring_payload.get("web_5xx_threshold"), 5),
        anomaly_cooldown_seconds=_to_int(monitoring_payload.get("anomaly_cooldown_seconds"), 300),
        max_related_log_lines=_to_int(monitoring_payload.get("max_related_log_lines"), 40),
        journal_keywords=list(monitoring_payload.get("journal_keywords") or ["error", "failed", "oom", "segfault"]),
    )
    web = WebServiceConfig(
        service_name=str(web_payload.get("service_name", "")).strip(),
        port=_to_int(web_payload.get("port"), 0) or None,
        tcp_host=str(web_payload.get("tcp_host", "127.0.0.1")),
        health_urls=list(web_payload.get("health_urls") or DEFAULT_WEB_HEALTH_URLS),
        access_log_paths=_to_path_list(web_payload.get("access_log_paths") or DEFAULT_WEB_ACCESS_LOGS, base_dir=base_dir),
        error_log_paths=_to_path_list(web_payload.get("error_log_paths") or DEFAULT_WEB_ERROR_LOGS, base_dir=base_dir),
        systemd_candidates=list(web_payload.get("systemd_candidates") or DEFAULT_WEB_SYSTEMD_CANDIDATES),
    )
    minecraft = MinecraftServiceConfig(
        service_name=str(minecraft_payload.get("service_name", "")).strip(),
        port=_to_int(minecraft_payload.get("port"), 25565),
        tcp_host=str(minecraft_payload.get("tcp_host", "127.0.0.1")),
        log_paths=_to_path_list(minecraft_payload.get("log_paths") or DEFAULT_MINECRAFT_LOGS, base_dir=base_dir),
        process_hints=list(minecraft_payload.get("process_hints") or DEFAULT_MINECRAFT_HINTS),
    )
    actions = ActionsConfig(
        mode=str(action_payload.get("mode", "propose-only")).strip().lower(),
        allowed_restart_services=list(action_payload.get("allowed_restart_services") or []),
        dangerous_action_policy=str(action_payload.get("dangerous_action_policy", "require-human-approval")),
        max_auto_actions_per_incident=_to_int(action_payload.get("max_auto_actions_per_incident"), 1),
    )
    notifications = NotificationConfig(
        discord_webhook_url=str(notification_payload.get("discord_webhook_url", "")).strip(),
        username=str(notification_payload.get("username", "infra-emergency-poc")).strip(),
        send_startup_summary=_to_bool(notification_payload.get("send_startup_summary"), True),
        send_monitoring_started=_to_bool(notification_payload.get("send_monitoring_started"), True),
    )
    llm = LlmConfig(
        enabled=_to_bool(llm_payload.get("enabled"), False),
        provider=str(llm_payload.get("provider", "openai")).strip().lower(),
        model=str(llm_payload.get("model", "gpt-4.1-mini")).strip(),
        timeout_seconds=_to_int(llm_payload.get("timeout_seconds"), 45),
        api_key_env=str(llm_payload.get("api_key_env", "OPENAI_API_KEY")).strip(),
        max_context_lines=_to_int(llm_payload.get("max_context_lines"), 40),
    )
    escalation = EscalationConfig(
        require_human_for_medium_risk=_to_bool(
            escalation_payload.get("require_human_for_medium_risk"),
            True,
        ),
        notify_on_verification_failure=_to_bool(
            escalation_payload.get("notify_on_verification_failure"),
            True,
        ),
    )
    return ProductionPocConfig(
        path=config_path,
        host=host,
        monitoring=monitoring,
        web=web,
        minecraft=minecraft,
        actions=actions,
        notifications=notifications,
        llm=llm,
        escalation=escalation,
    )
