import re
from pathlib import Path

import yaml

import aggregate_observations


ROOT_DIR = Path(__file__).resolve().parents[1]
EXPECTED_STANDARD_SWEEP = ["a", "b", "c", "d", "e", "f", "g", "h", "i", "i2", "k", "l", "m", "n", "o", "p", "q", "r", "s", "t", "u", "v", "w", "x"]
EXPECTED_SHORT_SWEEP = ["a", "c", "d", "h", "i2", "p", "q", "r", "t", "u", "v", "w", "x"]


def _extract_bash_array(script_text: str, name: str) -> list[str]:
    match = re.search(rf"^{name}=\(([^)]*)\)", script_text, re.MULTILINE)
    assert match, f"{name} was not found"
    return match.group(1).split()


def test_observe_runs_standard_and_short_sweeps_are_synced() -> None:
    text = (ROOT_DIR / "observe_runs.sh").read_text(encoding="utf-8")
    assert _extract_bash_array(text, "SCENARIOS_STANDARD") == EXPECTED_STANDARD_SWEEP
    assert _extract_bash_array(text, "SCENARIOS_SHORT") == EXPECTED_SHORT_SWEEP


def test_aggregate_observations_tracks_s_t_u_domains() -> None:
    assert aggregate_observations.EXPECTED_DOMAINS_BY_SCENARIO["s"] == {
        "ambiguous_service_disagreement",
        "app_config_or_env_mismatch",
        "reverse_proxy_or_upstream_mismatch",
    }
    assert aggregate_observations.EXPECTED_DOMAINS_BY_SCENARIO["t"] == {
        "app_config_or_env_mismatch",
        "database_auth_or_connectivity_issue",
    }
    assert aggregate_observations.EXPECTED_DOMAINS_BY_SCENARIO["u"] == {
        "app_config_or_env_mismatch",
        "database_auth_or_connectivity_issue",
        "query_or_code_bug",
    }
    assert aggregate_observations.EXPECTED_DOMAINS_BY_SCENARIO["v"] == {
        "topology_or_service_discovery_fault",
    }
    assert aggregate_observations.EXPECTED_DOMAINS_BY_SCENARIO["w"] == {
        "failover_contract_mismatch",
        "topology_or_service_discovery_fault",
    }
    assert aggregate_observations.EXPECTED_DOMAINS_BY_SCENARIO["x"] == {
        "degraded_mode_leak",
        "failover_contract_mismatch",
        "topology_or_service_discovery_fault",
    }


def test_readme_phase0_docs_are_synced() -> None:
    text = (ROOT_DIR / "README.md").read_text(encoding="utf-8")
    assert "A-X" in text
    assert "A-R" not in text
    assert "/Users/ryoike/Documents/codex/" not in text
    for snippet in [
        "./break.sh s",
        "./break.sh t",
        "./break.sh u",
        "./observe_runs.sh all",
        "./observe_runs.sh short",
        "./.venv/bin/python -m pytest -q",
        "./check.sh",
        "./check.sh --all",
    ]:
        assert snippet in text


def test_docker_compose_uses_stable_project_name_without_container_names() -> None:
    compose = yaml.safe_load((ROOT_DIR / "docker-compose.yml").read_text(encoding="utf-8"))
    assert compose["name"] == "llm-recovery-lab"
    assert all("container_name" not in service for service in compose["services"].values())


def test_check_script_uses_repo_venv_pytest() -> None:
    text = (ROOT_DIR / "check.sh").read_text(encoding="utf-8")
    assert ".venv/bin/python" in text
    assert "-m pytest -q" in text
    assert "not integration" in text
    assert "--all" in text
