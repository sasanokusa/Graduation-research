from agents.sensor import (
    _canonical_observation_requests,
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
