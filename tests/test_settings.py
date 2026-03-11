from core.agent_factory import build_chat_model_binding
from core.agent_roles import AgentRole
from core.settings import get_role_model_settings, refresh_role_settings_cache


def test_single_agent_settings_resolve_from_role_env(monkeypatch) -> None:
    monkeypatch.setenv("SINGLE_AGENT_PROVIDER", "google")
    monkeypatch.setenv("SINGLE_AGENT_MODEL", "gemini-test-model")
    monkeypatch.setenv("SINGLE_AGENT_TIMEOUT_SECONDS", "88")
    monkeypatch.setenv("SINGLE_AGENT_MAX_ATTEMPTS", "4")
    monkeypatch.setenv("SINGLE_AGENT_THINKING_LEVEL", "medium")
    monkeypatch.setenv("GOOGLE_API_KEY", "dummy-key")
    refresh_role_settings_cache()

    settings = get_role_model_settings(AgentRole.SINGLE_AGENT)
    assert settings.provider == "google"
    assert settings.model == "gemini-test-model"
    assert settings.timeout_seconds == 88
    assert settings.max_attempts == 4
    assert settings.thinking_level == "medium"
    assert settings.api_key_env_name == "GOOGLE_API_KEY"


def test_reviewer_settings_use_role_default_provider(monkeypatch) -> None:
    monkeypatch.delenv("REVIEWER_PROVIDER", raising=False)
    monkeypatch.delenv("REVIEWER_MODEL", raising=False)
    monkeypatch.setenv("ANTHROPIC_DEFAULT_MODEL", "claude-test-model")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy-key")
    refresh_role_settings_cache()

    settings = get_role_model_settings(AgentRole.REVIEWER)
    assert settings.provider == "anthropic"
    assert settings.model == "claude-test-model"
    assert settings.api_key_env_name == "ANTHROPIC_API_KEY"


def test_model_binding_reports_missing_api_key(monkeypatch) -> None:
    monkeypatch.setenv("SINGLE_AGENT_PROVIDER", "openai")
    monkeypatch.setenv("SINGLE_AGENT_MODEL", "gpt-test-model")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    refresh_role_settings_cache()

    binding = build_chat_model_binding(AgentRole.SINGLE_AGENT)
    assert binding.client is None
    assert binding.initialization_error_type == "api_key_missing"
    assert "OPENAI_API_KEY" in binding.initialization_error_message


def test_role_settings_load_from_dotenv_file(monkeypatch, tmp_path) -> None:
    (tmp_path / ".env").write_text(
        "SINGLE_AGENT_PROVIDER=openai\n"
        "SINGLE_AGENT_MODEL=gpt-from-dotenv\n"
        "OPENAI_API_KEY=dummy-key\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("core.settings.ROOT_DIR", tmp_path)
    monkeypatch.delenv("SINGLE_AGENT_PROVIDER", raising=False)
    monkeypatch.delenv("SINGLE_AGENT_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    refresh_role_settings_cache()

    settings = get_role_model_settings(AgentRole.SINGLE_AGENT)
    assert settings.provider == "openai"
    assert settings.model == "gpt-from-dotenv"
    assert settings.api_key == "dummy-key"
