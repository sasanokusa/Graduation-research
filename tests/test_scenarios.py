from pathlib import Path

import yaml

from core.policies import SUPPORTED_SUCCESS_CHECKS


def test_scenario_definitions_include_p_q_r() -> None:
    definitions = yaml.safe_load(Path("scenarios/definitions.yaml").read_text())["scenarios"]
    assert {"p", "q", "r"}.issubset(definitions)
    assert definitions["p"]["success_checks"] == [
        "healthz_200",
        "api_items_200",
        "api_items_nonempty",
        "api_items_schema_ok",
    ]
    assert "port_contract_matches_baseline" in definitions["q"]["success_checks"]


def test_all_defined_success_checks_are_supported() -> None:
    definitions = yaml.safe_load(Path("scenarios/definitions.yaml").read_text())["scenarios"]
    for scenario_id, definition in definitions.items():
        unsupported = set(definition.get("success_checks", [])) - SUPPORTED_SUCCESS_CHECKS
        assert not unsupported, f"{scenario_id} has unsupported checks: {sorted(unsupported)}"


def test_break_script_includes_p_q_r_cases_without_removing_existing_cases() -> None:
    text = Path("break.sh").read_text()
    for pattern in ["apply_p()", "apply_q()", "apply_r()", "pattern-p", "pattern-q", "pattern-r"]:
        assert pattern in text
    for legacy in ["apply_a()", "apply_o()", "pattern-a", "pattern-o"]:
        assert legacy in text
