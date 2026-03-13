from pathlib import Path

from experimental.production_poc.runtime_prod.config import load_config


def test_load_config_expands_env_and_resolves_paths(monkeypatch, tmp_path: Path) -> None:
    config_path = tmp_path / "production_poc.yaml"
    config_path.write_text(
        "\n".join(
            [
                "host:",
                "  host_label: test-host",
                "  state_dir: state",
                "services:",
                "  web:",
                "    service_name: nginx",
                "    access_log_paths:",
                "      - logs/access.log",
                "notifications:",
                "  discord_webhook_url: ${DISCORD_WEBHOOK_URL}",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://example.invalid/webhook")

    config = load_config(config_path)

    assert config.host.host_label == "test-host"
    assert config.host.state_dir == (tmp_path / "state").resolve()
    assert config.web.access_log_paths == [(tmp_path / "logs" / "access.log").resolve()]
    assert config.notifications.discord_webhook_url == "https://example.invalid/webhook"
    assert config.actions.mode == "propose-only"
