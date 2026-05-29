from agents.sensor import (
    _canonical_observation_requests,
    _narrower_snippet,
    _should_mask_app_main_query_snippet,
)


def test_canonical_observation_requests_normalizes_app_main_natural_language() -> None:
    requested = [
        "Open app/main.py and locate the /api/items handler and its SQL/query definition.",
        "Search app/main.py for 'itemz'.",
    ]

    assert _canonical_observation_requests(requested) == [
        "extract narrower relevant snippet from app/main.py"
    ]


def test_canonical_observation_requests_normalizes_logs_and_env() -> None:
    requested = [
        "Collect recent app service logs or traceback for /api/items.",
        "Inspect app/app.env for DB_PASSWORD.",
    ]

    assert _canonical_observation_requests(requested) == [
        "expand app log excerpt",
        "extract narrower relevant snippet from app/app.env",
    ]


def test_query_missing_table_error_does_not_keep_app_main_masked() -> None:
    assert (
        _should_mask_app_main_query_snippet(
            {"app": ""},
            {"status": 200, "body": '{"status":"ok"}'},
            {
                "status": 500,
                "body": "{\"detail\":\"database error: (1146, \\\"Table 'appdb.itemz' doesn't exist\\\")\"}",
            },
        )
        is False
    )


def test_db_auth_error_still_masks_app_main_query_snippet() -> None:
    assert (
        _should_mask_app_main_query_snippet(
            {"app": ""},
            {"status": 500, "body": "Access denied for user appuser"},
            {"status": 500, "body": "Access denied for user appuser"},
        )
        is True
    )


def test_topology_degraded_app_env_observation_exposes_contract_lines(tmp_path, monkeypatch) -> None:
    env_file = tmp_path / "app.env"
    env_file.write_text(
        "\n".join(
            [
                "APP_PORT=8000",
                "DB_HOST=db",
                "DB_PASSWORD=apppassword",
                "CACHE_HOST=queue",
                "CACHE_EXPECTED_HOST=cache",
                "QUEUE_HOST=cache",
                "QUEUE_EXPECTED_HOST=queue",
                "METRICS_HOST=metrics",
                "METRICS_EXPECTED_HOST=metrics",
                "DEGRADED_MODE=true",
            ]
        )
    )

    monkeypatch.setattr("agents.sensor.resolve_repo_path", lambda _path: env_file)

    snippet = _narrower_snippet(
        "app/app.env",
        service_logs={},
        healthz={"status": 200},
        api_items={"status": 200},
        topology={
            "status": 200,
            "body": (
                '{"status":"degraded","checks":{"dependencies_reachable":true,'
                '"expected_hosts_ok":false,"expected_groups_ok":true,'
                '"degraded_mode_ok":false},"dependencies":{}}'
            ),
        },
    )

    assert "CACHE_HOST=queue" in snippet
    assert "QUEUE_HOST=cache" in snippet
    assert "QUEUE_EXPECTED_HOST=queue" in snippet
    assert "DEGRADED_MODE=true" in snippet
