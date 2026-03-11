from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
SCENARIO_DEFINITIONS_PATH = ROOT_DIR / "scenarios" / "definitions.yaml"
RESULTS_DIR = ROOT_DIR / "results"

ALLOWED_EDIT_FILES: dict[str, str] = {
    "nginx/nginx.conf": "nginx/nginx.conf.base",
    "app/main.py": "app/main.py.base",
    "app/requirements.txt": "app/requirements.txt.base",
    "app/app.env": "app/app.env.base",
}
ALLOWED_ACTION_TYPES = {
    "edit_file",
    "restart_compose_service",
    "rebuild_compose_service",
    "run_config_test",
    "run_health_check",
    "show_file",
}
ALLOWED_SERVICES = {"nginx", "app", "db"}
ALLOWED_CONFIG_TEST_TARGETS = {"compose", "nginx"}
SUPPORTED_SUCCESS_CHECKS = {
    "healthz_200",
    "api_items_200",
    "app_running",
    "nginx_running",
    "db_running",
}
ALLOWED_HEALTH_CHECKS = SUPPORTED_SUCCESS_CHECKS
MAX_CHANGED_LINES = 20
MAX_ACTIONS_PER_PLAN = 6
CODE_FILES = {"app/main.py"}
HARD_SCENARIO_IDS = {"i2", "m", "n", "o"}
ROLLBACK_REFRESH_POLICY: dict[str, list[dict[str, str]]] = {
    "nginx/nginx.conf": [
        {"type": "run_config_test", "target": "nginx"},
        {"type": "restart_compose_service", "service": "nginx"},
    ],
    "app/app.env": [
        {"type": "rebuild_compose_service", "service": "app"},
    ],
    "app/main.py": [
        {"type": "rebuild_compose_service", "service": "app"},
    ],
    "app/requirements.txt": [
        {"type": "rebuild_compose_service", "service": "app"},
    ],
}


def normalize_repo_path(path_value: str) -> str:
    path = Path(path_value)
    if path.is_absolute():
        raise ValueError("absolute paths are not allowed")

    normalized = path.as_posix()
    if normalized.startswith("../") or normalized == "..":
        raise ValueError("paths outside the repository are not allowed")
    return normalized


def resolve_repo_path(path_value: str) -> Path:
    normalized = normalize_repo_path(path_value)
    resolved = (ROOT_DIR / normalized).resolve()
    if ROOT_DIR.resolve() not in resolved.parents and resolved != ROOT_DIR.resolve():
        raise ValueError("resolved path escapes the repository")
    return resolved


def get_base_file_for(path_value: str) -> str | None:
    normalized = normalize_repo_path(path_value)
    return ALLOWED_EDIT_FILES.get(normalized)


def is_code_file(path_value: str) -> bool:
    return normalize_repo_path(path_value) in CODE_FILES


def is_hard_scenario(scenario_id: str) -> bool:
    return scenario_id in HARD_SCENARIO_IDS


def get_restore_policy(scenario_definition: dict | None) -> dict[str, list[str]]:
    if not scenario_definition:
        return {}
    restore_policy = scenario_definition.get("restore_policy", {})
    if not isinstance(restore_policy, dict):
        return {}
    return restore_policy


def rollback_actions_for_paths(paths: list[str]) -> list[dict[str, str]]:
    planned: list[dict[str, str]] = []
    seen: set[tuple[tuple[str, str], ...]] = set()
    for path_value in paths:
        for action in ROLLBACK_REFRESH_POLICY.get(normalize_repo_path(path_value), []):
            signature = tuple(sorted(action.items()))
            if signature in seen:
                continue
            planned.append(dict(action))
            seen.add(signature)
    return planned
