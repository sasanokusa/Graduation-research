import json

from core.actions import format_actions, parse_plan_text
from core.state import SingleAgentState


def _section(title: str) -> None:
    divider = "=" * 50
    print(divider)
    print(title)
    print(divider)


def build_mock_plan(state: SingleAgentState, *, turn: int = 1, mode: str = "single_agent") -> dict:
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
    if state["scenario"] == "i2":
        if turn >= 2:
            return {
                "summary": "Fix the now-visible query bug and rebuild the app service.",
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
            "summary": "Apply the visible first-stage listen-port fix and rebuild the app service.",
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
    if state["scenario"] == "m":
        if turn == 2:
            return {
                "summary": "Repair the exposed DB credential drift and rebuild the app service.",
                "actions": [
                    {
                        "type": "edit_file",
                        "path": "app/app.env",
                        "operation": "replace_text",
                        "old_text": "DB_PASSWORD=wrongpassword",
                        "new_text": "DB_PASSWORD=apppassword",
                    },
                    {
                        "type": "rebuild_compose_service",
                        "service": "app",
                    },
                ],
            }
        if turn >= 3:
            return {
                "summary": "Repair the exposed query bug and rebuild the app service.",
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
            "summary": "Repair the visible nginx upstream host mismatch and restart nginx.",
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
    if state["scenario"] == "n":
        if turn >= 2:
            return {
                "summary": "Fix the now-visible query bug and rebuild the app service.",
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
    if state["scenario"] == "o":
        if turn >= 2:
            return {
                "summary": "Repair the now-visible query bug and rebuild the app service.",
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
            "summary": "Repair the visible DB credential drift and rebuild the app service.",
            "actions": [
                {
                    "type": "edit_file",
                    "path": "app/app.env",
                    "operation": "replace_text",
                    "old_text": "DB_PASSWORD=wrongpassword",
                    "new_text": "DB_PASSWORD=apppassword",
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
    raw_output = json.dumps(build_mock_plan(state, turn=1, mode="single_agent"), ensure_ascii=False)
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
        "planner_error_stage": "none",
        "planner_retry_count": 0,
        "planner_timeout_seconds": 0,
        "planner_attempts": [],
        "planner_transport_failure": False,
        "planner_reasoning_failure": False,
        "planner_fallback_used": False,
        "planner_fallback_reason": "",
        "planner_fallback_type": "",
        "planner_output_raw": raw_output,
        "planner_summary": plan["summary"],
        "normalized_actions": plan["actions"],
        "proposed_actions": plan["actions"],
        "verifier_precheck_result": {
            **state["verifier_precheck_result"],
            "planner_errors": parse_errors,
        },
    }


def mock_planner_node(state: SingleAgentState) -> SingleAgentState:
    turn = state.get("planner_turn", 1)
    raw_output = json.dumps(build_mock_plan(state, turn=turn, mode="multi_agent"), ensure_ascii=False)
    plan, parse_errors = parse_plan_text(
        raw_output,
        forbidden_action_types={"show_file"},
    )
    _section(f"🧠 [PHASE 4] PLANNER (TURN {turn})")
    print(f"mode: {state['worker_mode']}")
    print(format_actions(plan["actions"]))
    print()
    return {
        **state,
        "planner_provider": "mock",
        "planner_model": "mock-planner",
        "planner_error_type": "none",
        "planner_error_stage": "none",
        "planner_retry_count": 0,
        "planner_timeout_seconds": 0,
        "planner_attempts": [],
        "planner_transport_failure": False,
        "planner_reasoning_failure": False,
        "planner_fallback_used": False,
        "planner_fallback_reason": "",
        "planner_fallback_type": "",
        "planner_output_raw": raw_output,
        "planner_summary": plan["summary"],
        "normalized_actions": plan["actions"],
        "proposed_actions": plan["actions"],
        "agent_role_trace": [*state.get("agent_role_trace", []), f"planner:{turn}"],
        "role_model_trace": [
            *state.get("role_model_trace", []),
            *([] if {"role": "planner", "provider": "mock", "model": "mock-planner"} in state.get("role_model_trace", []) else [{"role": "planner", "provider": "mock", "model": "mock-planner"}]),
        ],
        "verifier_precheck_result": {
            **state["verifier_precheck_result"],
            "planner_errors": parse_errors,
        },
    }
