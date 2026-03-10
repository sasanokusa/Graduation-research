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
