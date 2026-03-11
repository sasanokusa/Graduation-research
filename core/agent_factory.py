from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Any

from core.agent_roles import AgentRole
from core.settings import RoleModelSettings, get_role_model_settings


@dataclass(frozen=True)
class ChatModelBinding:
    settings: RoleModelSettings
    client: Any | None
    initialization_error_type: str
    initialization_error_stage: str
    initialization_error_message: str


def _build_google_client(settings: RoleModelSettings) -> Any:
    chat_module = import_module("langchain_google_genai")
    client_kwargs: dict[str, Any] = {
        "model": settings.model,
        "google_api_key": settings.api_key,
        "temperature": 0,
        "timeout": settings.timeout_seconds,
        "max_retries": 0,
        "response_mime_type": "application/json",
        "transport": "rest",
    }
    if settings.thinking_budget is not None:
        client_kwargs["thinking_budget"] = settings.thinking_budget
    return chat_module.ChatGoogleGenerativeAI(**client_kwargs)


def _build_openai_client(settings: RoleModelSettings) -> Any:
    chat_module = import_module("langchain_openai")
    return chat_module.ChatOpenAI(
        model=settings.model,
        api_key=settings.api_key,
        temperature=0,
        timeout=settings.timeout_seconds,
        max_retries=0,
    )


def _build_anthropic_client(settings: RoleModelSettings) -> Any:
    chat_module = import_module("langchain_anthropic")
    return chat_module.ChatAnthropic(
        model=settings.model,
        api_key=settings.api_key,
        temperature=0,
        timeout=settings.timeout_seconds,
        max_retries=0,
    )


def build_chat_model_binding(role: AgentRole) -> ChatModelBinding:
    settings = get_role_model_settings(role)
    if not settings.api_key:
        return ChatModelBinding(
            settings=settings,
            client=None,
            initialization_error_type="api_key_missing",
            initialization_error_stage="config",
            initialization_error_message=f"{settings.api_key_env_name} is not set",
        )

    try:
        if settings.provider == "google":
            client = _build_google_client(settings)
        elif settings.provider == "openai":
            client = _build_openai_client(settings)
        elif settings.provider == "anthropic":
            client = _build_anthropic_client(settings)
        else:
            return ChatModelBinding(
                settings=settings,
                client=None,
                initialization_error_type="planner_provider_error",
                initialization_error_stage="config",
                initialization_error_message=f"unsupported provider: {settings.provider}",
            )
    except ModuleNotFoundError as exc:
        return ChatModelBinding(
            settings=settings,
            client=None,
            initialization_error_type="planner_provider_error",
            initialization_error_stage="config",
            initialization_error_message=f"provider package is missing for {settings.provider}: {exc}",
        )
    except Exception as exc:
        return ChatModelBinding(
            settings=settings,
            client=None,
            initialization_error_type="planner_provider_error",
            initialization_error_stage="config",
            initialization_error_message=str(exc),
        )

    return ChatModelBinding(
        settings=settings,
        client=client,
        initialization_error_type="none",
        initialization_error_stage="none",
        initialization_error_message="",
    )
