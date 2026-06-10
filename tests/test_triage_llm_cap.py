import pytest

from core.triage import resolve_effective_triage_mode, triage_llm_max_calls_per_run


def _state(mode: str, llm_iterations: int, rule_iterations: int = 0) -> dict:
    iterations = [{"iteration": i + 1, "triage_mode": "llm"} for i in range(llm_iterations)]
    iterations += [
        {"iteration": llm_iterations + i + 1, "triage_mode": "rule"} for i in range(rule_iterations)
    ]
    return {"triage_mode": mode, "triage_iterations": iterations}


def test_cap_defaults_to_unlimited(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TRIAGE_LLM_MAX_CALLS_PER_RUN", raising=False)
    assert triage_llm_max_calls_per_run() == 0
    assert resolve_effective_triage_mode(_state("llm", llm_iterations=10)) == ("llm", False)


def test_cap_rejects_invalid_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRIAGE_LLM_MAX_CALLS_PER_RUN", "abc")
    assert triage_llm_max_calls_per_run() == 0
    monkeypatch.setenv("TRIAGE_LLM_MAX_CALLS_PER_RUN", "-1")
    assert triage_llm_max_calls_per_run() == 0


def test_rule_mode_never_caps(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRIAGE_LLM_MAX_CALLS_PER_RUN", "1")
    assert resolve_effective_triage_mode(_state("rule", llm_iterations=0)) == ("rule", False)


def test_llm_mode_caps_after_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRIAGE_LLM_MAX_CALLS_PER_RUN", "2")
    assert resolve_effective_triage_mode(_state("llm", llm_iterations=0)) == ("llm", False)
    assert resolve_effective_triage_mode(_state("llm", llm_iterations=1)) == ("llm", False)
    assert resolve_effective_triage_mode(_state("llm", llm_iterations=2)) == ("rule", True)
    assert resolve_effective_triage_mode(_state("llm", llm_iterations=3)) == ("rule", True)


def test_fallback_iterations_count_against_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRIAGE_LLM_MAX_CALLS_PER_RUN", "1")
    state = {
        "triage_mode": "llm",
        "triage_iterations": [{"iteration": 1, "triage_mode": "llm_fallback_to_rule"}],
    }
    assert resolve_effective_triage_mode(state) == ("rule", True)


def test_capped_rule_iterations_do_not_count(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TRIAGE_LLM_MAX_CALLS_PER_RUN", "2")
    assert resolve_effective_triage_mode(_state("llm", llm_iterations=1, rule_iterations=3)) == (
        "llm",
        False,
    )
