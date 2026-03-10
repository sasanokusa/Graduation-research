import json

from core.actions import format_actions, parse_plan_text
from core.state import SingleAgentState


def _section(title: str) -> None:
    divider = "=" * 50
    print(divider)
    print(title)
    print(divider)


def _build_mock_plan(state: SingleAgentState) -> dict:
    if state["scenario"] == "a":
        return {
            "summary": "Restore nginx upstream port and restart nginx.",
            "actions": [
                {
                    "type": "edit_file",
                    "path": "nginx/nginx.conf",
                    "operation": "replace_text",
                    "old_text": "server app:8001 resolve;",
                    "new_text": "server app:8000 resolve;",
                },
                {
                    "type": "restart_compose_service",
                    "service": "nginx",
                },
            ],
        }
    if state["scenario"] == "b":
        return {
            "summary": "Restore uvicorn to requirements and rebuild the app service.",
            "actions": [
                {
                    "type": "edit_file",
                    "path": "app/requirements.txt",
                    "operation": "replace_text",
                    "old_text": "fastapi==0.116.1\nPyMySQL==1.1.1",
                    "new_text": "fastapi==0.116.1\nuvicorn[standard]==0.35.0\nPyMySQL==1.1.1",
                },
                {
                    "type": "rebuild_compose_service",
                    "service": "app",
                },
            ],
        }
    if state["scenario"] == "c":
        return {
            "summary": "Restore the app env file from base and rebuild the app service.",
            "actions": [
                {
                    "type": "edit_file",
                    "path": "app/app.env",
                    "operation": "restore_from_base",
                },
                {
                    "type": "rebuild_compose_service",
                    "service": "app",
                },
            ],
        }
    if state["scenario"] == "d":
        return {
            "summary": "Restore the broken items table reference and rebuild the app service.",
            "actions": [
                {
                    "type": "edit_file",
                    "path": "app/main.py",
                    "operation": "replace_text",
                    "old_text": 'cursor.execute("SELECT id, name, description FROM itemz ORDER BY id")',
                    "new_text": 'cursor.execute("SELECT id, name, description FROM items ORDER BY id")',
                },
                {
                    "type": "rebuild_compose_service",
                    "service": "app",
                },
            ],
        }
    if state["scenario"] == "e":
        return {
            "summary": "Restore the app listen port to the baseline value and rebuild the app service.",
            "actions": [
                {
                    "type": "edit_file",
                    "path": "app/app.env",
                    "operation": "restore_from_base",
                },
                {
                    "type": "rebuild_compose_service",
                    "service": "app",
                },
            ],
        }
    if state["scenario"] == "f":
        return {
            "summary": "Restore the missing description column reference and rebuild the app service.",
            "actions": [
                {
                    "type": "edit_file",
                    "path": "app/main.py",
                    "operation": "replace_text",
                    "old_text": 'cursor.execute("SELECT id, name, details FROM items ORDER BY id")',
                    "new_text": 'cursor.execute("SELECT id, name, description FROM items ORDER BY id")',
                },
                {
                    "type": "rebuild_compose_service",
                    "service": "app",
                },
            ],
        }
    if state["scenario"] == "g":
        return {
            "summary": "Restore the broken health query and rebuild the app service.",
            "actions": [
                {
                    "type": "edit_file",
                    "path": "app/main.py",
                    "operation": "replace_text",
                    "old_text": 'cursor.execute("SELECT missing FROM health_checks")',
                    "new_text": 'cursor.execute("SELECT 1 AS ok")',
                },
                {
                    "type": "rebuild_compose_service",
                    "service": "app",
                },
            ],
        }
    if state["scenario"] == "h":
        return {
            "summary": "Restore the nginx upstream host name and restart nginx.",
            "actions": [
                {
                    "type": "edit_file",
                    "path": "nginx/nginx.conf",
                    "operation": "replace_text",
                    "old_text": "server backend:8000 resolve;",
                    "new_text": "server app:8000 resolve;",
                },
                {
                    "type": "restart_compose_service",
                    "service": "nginx",
                },
            ],
        }
    if state["scenario"] == "i":
        return {
            "summary": "Apply the smallest visible first-stage env fix by restoring the app listen port and rebuilding app.",
            "actions": [
                {
                    "type": "edit_file",
                    "path": "app/app.env",
                    "operation": "replace_text",
                    "old_text": "APP_PORT=9000",
                    "new_text": "APP_PORT=8000",
                },
                {
                    "type": "rebuild_compose_service",
                    "service": "app",
                },
            ],
        }
    if state["scenario"] == "k":
        return {
            "summary": "Restore app/main.py from base and rebuild the app service.",
            "actions": [
                {
                    "type": "edit_file",
                    "path": "app/main.py",
                    "operation": "restore_from_base",
                },
                {
                    "type": "rebuild_compose_service",
                    "service": "app",
                },
            ],
        }
    if state["scenario"] == "l":
        return {
            "summary": "Restore the current app query bug and rebuild the app service instead of touching nginx.",
            "actions": [
                {
                    "type": "edit_file",
                    "path": "app/main.py",
                    "operation": "replace_text",
                    "old_text": 'cursor.execute("SELECT id, name, description FROM itemz ORDER BY id")',
                    "new_text": 'cursor.execute("SELECT id, name, description FROM items ORDER BY id")',
                },
                {
                    "type": "rebuild_compose_service",
                    "service": "app",
                },
            ],
        }

    return {
        "summary": f"No mock plan is implemented for scenario {state['scenario']}.",
        "actions": [],
    }


def mock_worker_node(state: SingleAgentState) -> SingleAgentState:
    raw_output = json.dumps(_build_mock_plan(state), ensure_ascii=False)
    plan, parse_errors = parse_plan_text(
        raw_output,
        forbidden_action_types={"show_file"},
    )
    _section("🧠 [PHASE 3] WORKER")
    print(f"mode: {state['worker_mode']}")
    print(format_actions(plan["actions"]))
    print()
    return {
        **state,
        "planner_error_type": "none",
        "planner_retry_count": 0,
        "planner_timeout_seconds": 0,
        "planner_output_raw": raw_output,
        "planner_summary": plan["summary"],
        "normalized_actions": plan["actions"],
        "proposed_actions": plan["actions"],
        "verifier_precheck_result": {
            **state["verifier_precheck_result"],
            "planner_errors": parse_errors,
        },
    }
