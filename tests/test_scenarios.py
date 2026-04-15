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


def test_scenario_definitions_include_s_t_u() -> None:
    definitions = yaml.safe_load(Path("scenarios/definitions.yaml").read_text())["scenarios"]
    assert {"s", "t", "u"}.issubset(definitions)
    assert definitions["s"]["name"] == "bilateral_port_contract_violation"
    assert "port_contract_matches_baseline" in definitions["s"]["success_checks"]
    assert definitions["t"]["name"] == "network_topology_fault"
    assert "app/app.env" in definitions["t"]["allowed_files"]
    assert definitions["u"]["name"] == "network_topology_masks_query_cascade"
    assert "app/main.py" in definitions["u"]["allowed_files"]
    assert definitions["u"].get("restore_policy", {}).get("disallow_initial_restore_for") == ["app/main.py"]


def test_break_script_includes_s_t_u_cases() -> None:
    text = Path("break.sh").read_text()
    for pattern in ["apply_s()", "apply_t()", "apply_u()", "pattern-s", "pattern-t", "pattern-u"]:
        assert pattern in text
    for legacy in ["apply_a()", "apply_r()", "pattern-a", "pattern-r"]:
        assert legacy in text


def test_scenario_definitions_include_phase2_v_w_x() -> None:
    payload = yaml.safe_load(Path("scenarios/definitions.yaml").read_text())
    definitions = payload["scenarios"]
    fault_classes = payload["fault_classes"]
    assert {"v", "w", "x"}.issubset(definitions)
    assert {"v", "w", "x"}.issubset(set(fault_classes["topology_fault"]))
    assert "u" in fault_classes["masked_cascade"]
    assert definitions["v"]["name"] == "cache_name_resolution_fault"
    assert definitions["w"]["name"] == "failover_target_mismatch"
    assert definitions["x"]["name"] == "bilateral_dependency_drift"
    for scenario_id in ["v", "w", "x"]:
        definition = definitions[scenario_id]
        assert definition["fault_class"] == "topology_fault"
        assert "dc_topology_contract_ok" in definition["success_checks"]
        assert "dc_no_degraded_mode" in definition["success_checks"]
        assert definition["dc_topology"]["dependencies"] == ["cache", "queue", "metrics"]


def test_break_script_includes_phase2_v_w_x_cases() -> None:
    text = Path("break.sh").read_text()
    for pattern in ["apply_v()", "apply_w()", "apply_x()", "pattern-v", "pattern-w", "pattern-x"]:
        assert pattern in text
    for legacy in ["apply_a()", "apply_u()", "pattern-a", "pattern-u"]:
        assert legacy in text
