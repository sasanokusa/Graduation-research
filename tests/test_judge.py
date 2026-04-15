from agents.judge import parse_judge_output


def test_parse_valid_accept() -> None:
    text = '{"decision":"retry","override":false,"reasoning":"reviewer is correct"}'
    result, errors = parse_judge_output(text)
    assert not errors
    assert result["decision"] == "retry"
    assert result["override"] is False
    assert result["reasoning"] == "reviewer is correct"


def test_parse_valid_override() -> None:
    text = '{"decision":"stop","override":true,"reasoning":"no evidence for retry"}'
    result, errors = parse_judge_output(text)
    assert not errors
    assert result["decision"] == "stop"
    assert result["override"] is True


def test_parse_handles_code_fence() -> None:
    text = '```json\n{"decision":"retry","override":true,"reasoning":"new fault exposed"}\n```'
    result, errors = parse_judge_output(text)
    assert not errors
    assert result["decision"] == "retry"
    assert result["override"] is True


def test_parse_invalid_json_defaults_to_stop() -> None:
    text = "not json"
    result, errors = parse_judge_output(text)
    assert result["decision"] == "stop"
    assert result["override"] is False
    assert any("not valid JSON" in e for e in errors)


def test_parse_invalid_decision_defaults_to_stop() -> None:
    text = '{"decision":"maybe","override":false,"reasoning":"unsure"}'
    result, errors = parse_judge_output(text)
    assert result["decision"] == "stop"
    assert any("unsupported judge decision" in e for e in errors)


def test_parse_string_override_true() -> None:
    text = '{"decision":"retry","override":"true","reasoning":"ok"}'
    result, errors = parse_judge_output(text)
    assert not errors
    assert result["override"] is True
