from agents.triage_agent import VALID_DOMAIN_KEYS, parse_triage_llm_output


def test_parse_valid_json_array() -> None:
    text = '[{"domain":"query_or_code_bug","confidence":0.9,"evidence":["broken table name"]}]'
    ranked, errors = parse_triage_llm_output(text)
    assert not errors
    assert len(ranked) == 1
    assert ranked[0]["domain"] == "query_or_code_bug"
    assert ranked[0]["confidence"] == 0.9


def test_parse_multiple_domains_sorted_by_confidence() -> None:
    text = (
        '[{"domain":"database_auth_or_connectivity_issue","confidence":0.7,"evidence":["auth error"]},'
        '{"domain":"query_or_code_bug","confidence":0.95,"evidence":["broken query"]}]'
    )
    ranked, errors = parse_triage_llm_output(text)
    assert not errors
    assert len(ranked) == 2
    assert ranked[0]["domain"] == "query_or_code_bug"
    assert ranked[1]["domain"] == "database_auth_or_connectivity_issue"


def test_parse_rejects_invalid_domain_key() -> None:
    text = '[{"domain":"nonexistent_domain","confidence":0.8,"evidence":["something"]}]'
    ranked, errors = parse_triage_llm_output(text)
    assert len(ranked) == 0
    assert any("unknown domain key" in e for e in errors)


def test_parse_handles_code_fence_wrapper() -> None:
    text = '```json\n[{"domain":"unknown","confidence":0.5,"evidence":["weak signal"]}]\n```'
    ranked, errors = parse_triage_llm_output(text)
    assert not errors
    assert len(ranked) == 1
    assert ranked[0]["domain"] == "unknown"


def test_parse_handles_invalid_json() -> None:
    text = "this is not json at all"
    ranked, errors = parse_triage_llm_output(text)
    assert len(ranked) == 0
    assert any("not valid JSON" in e for e in errors)


def test_parse_clamps_confidence() -> None:
    text = '[{"domain":"unknown","confidence":1.5,"evidence":["over"]}]'
    ranked, errors = parse_triage_llm_output(text)
    assert not errors
    assert ranked[0]["confidence"] == 1.0


def test_all_valid_domain_keys_are_accepted() -> None:
    items = [{"domain": key, "confidence": 0.5, "evidence": ["test"]} for key in VALID_DOMAIN_KEYS]
    ranked, errors = parse_triage_llm_output(str(items).replace("'", '"'))
    assert not errors
    assert len(ranked) == len(VALID_DOMAIN_KEYS)
