from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from dotenv import load_dotenv

from core.agent_roles import AgentRole, role_env_prefix
from core.policies import ROOT_DIR


DEFAULT_PROVIDER_BY_ROLE: dict[AgentRole, str] = {
    AgentRole.SINGLE_AGENT: "google",
    AgentRole.PLANNER: "google",
    AgentRole.REVIEWER: "anthropic",
    AgentRole.JUDGE: "openai",
    AgentRole.TRIAGE: "google",
}

DEFAULT_MODEL_BY_PROVIDER = {
    "google": "gemini-3-flash-preview",
    "openai": "gpt-4.1-mini",
    "anthropic": "claude-sonnet-4-6",
}

DEFAULT_TIMEOUT_BY_PROVIDER = {
    "google": 75,
    "openai": 60,
    "anthropic": 60,
}

DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_BACKOFF_BASE_SECONDS = 2.0
DEFAULT_BACKOFF_CAP_SECONDS = 20.0
DEFAULT_THINKING_LEVEL = "low"

PROVIDER_API_KEY_ENV = {
    "google": "GOOGLE_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


@dataclass(frozen=True)
class RoleModelSettings:
    role: AgentRole
    provider: str
    model: str
    api_key_env_name: str
    api_key: str
    timeout_seconds: int
    max_attempts: int
    backoff_base_seconds: float
    backoff_cap_seconds: float
    thinking_level: str
    thinking_budget: int | None
    extra_options: dict[str, Any]


def _env_str(name: str, default: str = "") -> str:
    value = os.getenv(name, "").strip()
    return value if value else default


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return int(float(value))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _thinking_budget_from_level(level: str) -> int | None:
    normalized = level.strip().lower()
    if normalized in {"", "default", "auto"}:
        return None
    if normalized in {"off", "none", "minimal"}:
        return 0
    if normalized == "low":
        return 256
    if normalized == "medium":
        return 1024
    if normalized == "high":
        return 2048
    if normalized.isdigit():
        return int(normalized)
    return None


def load_repo_env() -> None:
    load_dotenv(ROOT_DIR / ".env", override=False)


def _provider_default_model(provider: str) -> str:
    env_name = f"{provider.upper()}_DEFAULT_MODEL"
    return _env_str(env_name, DEFAULT_MODEL_BY_PROVIDER[provider])


def _legacy_google_model(role: AgentRole) -> str:
    if role in {AgentRole.SINGLE_AGENT, AgentRole.PLANNER, AgentRole.TRIAGE}:
        return _env_str("GEMINI_MODEL")
    return ""


def _legacy_google_timeout(role: AgentRole) -> int | None:
    if role in {AgentRole.SINGLE_AGENT, AgentRole.PLANNER, AgentRole.TRIAGE}:
        value = _env_str("GEMINI_PLANNER_TIMEOUT_SECONDS")
        if value:
            return _env_int("GEMINI_PLANNER_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_BY_PROVIDER["google"])
    return None


def _legacy_google_max_attempts(role: AgentRole) -> int | None:
    if role in {AgentRole.SINGLE_AGENT, AgentRole.PLANNER, AgentRole.TRIAGE}:
        value = _env_str("GEMINI_PLANNER_MAX_ATTEMPTS")
        if value:
            return _env_int("GEMINI_PLANNER_MAX_ATTEMPTS", DEFAULT_MAX_ATTEMPTS)
    return None


def _legacy_google_backoff_base(role: AgentRole) -> float | None:
    if role in {AgentRole.SINGLE_AGENT, AgentRole.PLANNER, AgentRole.TRIAGE}:
        value = _env_str("GEMINI_PLANNER_BACKOFF_BASE_SECONDS")
        if value:
            return _env_float("GEMINI_PLANNER_BACKOFF_BASE_SECONDS", DEFAULT_BACKOFF_BASE_SECONDS)
    return None


def _legacy_google_backoff_cap(role: AgentRole) -> float | None:
    if role in {AgentRole.SINGLE_AGENT, AgentRole.PLANNER, AgentRole.TRIAGE}:
        value = _env_str("GEMINI_PLANNER_BACKOFF_CAP_SECONDS")
        if value:
            return _env_float("GEMINI_PLANNER_BACKOFF_CAP_SECONDS", DEFAULT_BACKOFF_CAP_SECONDS)
    return None


def _legacy_google_thinking_level(role: AgentRole) -> str:
    if role in {AgentRole.SINGLE_AGENT, AgentRole.PLANNER, AgentRole.TRIAGE}:
        return _env_str("GEMINI_THINKING_LEVEL")
    return ""


@lru_cache(maxsize=None)
def get_role_model_settings(role: AgentRole) -> RoleModelSettings:
    load_repo_env()

    role_prefix = role_env_prefix(role)
    provider = _env_str(f"{role_prefix}_PROVIDER", DEFAULT_PROVIDER_BY_ROLE[role]).lower()
    if provider not in PROVIDER_API_KEY_ENV:
        provider = DEFAULT_PROVIDER_BY_ROLE[role]

    model = _env_str(f"{role_prefix}_MODEL")
    if not model and provider == "google":
        model = _legacy_google_model(role)
    if not model:
        model = _provider_default_model(provider)

    timeout_seconds = _env_int(f"{role_prefix}_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_BY_PROVIDER[provider])
    legacy_timeout = _legacy_google_timeout(role) if provider == "google" else None
    if provider == "google" and legacy_timeout is not None and not _env_str(f"{role_prefix}_TIMEOUT_SECONDS"):
        timeout_seconds = legacy_timeout

    max_attempts = _env_int(f"{role_prefix}_MAX_ATTEMPTS", DEFAULT_MAX_ATTEMPTS)
    legacy_max_attempts = _legacy_google_max_attempts(role) if provider == "google" else None
    if provider == "google" and legacy_max_attempts is not None and not _env_str(f"{role_prefix}_MAX_ATTEMPTS"):
        max_attempts = legacy_max_attempts

    backoff_base_seconds = _env_float(f"{role_prefix}_BACKOFF_BASE_SECONDS", DEFAULT_BACKOFF_BASE_SECONDS)
    legacy_backoff_base = _legacy_google_backoff_base(role) if provider == "google" else None
    if provider == "google" and legacy_backoff_base is not None and not _env_str(
        f"{role_prefix}_BACKOFF_BASE_SECONDS"
    ):
        backoff_base_seconds = legacy_backoff_base

    backoff_cap_seconds = _env_float(f"{role_prefix}_BACKOFF_CAP_SECONDS", DEFAULT_BACKOFF_CAP_SECONDS)
    legacy_backoff_cap = _legacy_google_backoff_cap(role) if provider == "google" else None
    if provider == "google" and legacy_backoff_cap is not None and not _env_str(f"{role_prefix}_BACKOFF_CAP_SECONDS"):
        backoff_cap_seconds = legacy_backoff_cap

    thinking_level = _env_str(f"{role_prefix}_THINKING_LEVEL", DEFAULT_THINKING_LEVEL)
    legacy_thinking_level = _legacy_google_thinking_level(role) if provider == "google" else ""
    if provider == "google" and legacy_thinking_level and not _env_str(f"{role_prefix}_THINKING_LEVEL"):
        thinking_level = legacy_thinking_level

    api_key_env_name = PROVIDER_API_KEY_ENV[provider]
    api_key = _env_str(api_key_env_name)

    return RoleModelSettings(
        role=role,
        provider=provider,
        model=model,
        api_key_env_name=api_key_env_name,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
        max_attempts=max_attempts,
        backoff_base_seconds=backoff_base_seconds,
        backoff_cap_seconds=backoff_cap_seconds,
        thinking_level=thinking_level,
        thinking_budget=_thinking_budget_from_level(thinking_level) if provider == "google" else None,
        extra_options={"temperature": 0},
    )


def refresh_role_settings_cache() -> None:
    get_role_model_settings.cache_clear()
    load_repo_env()
