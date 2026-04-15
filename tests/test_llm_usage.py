from types import SimpleNamespace

from core.llm_usage import collect_llm_usage, extract_token_usage


def test_extract_token_usage_from_usage_metadata() -> None:
    response = SimpleNamespace(
        usage_metadata={
            "input_tokens": 10,
            "output_tokens": 4,
            "total_tokens": 14,
            "output_token_details": {"reasoning": 2},
        },
        response_metadata={},
    )

    usage = extract_token_usage(response)

    assert usage["input_tokens"] == 10
    assert usage["output_tokens"] == 4
    assert usage["total_tokens"] == 14
    assert usage["reasoning_tokens"] == 2


def test_extract_token_usage_from_openai_response_metadata() -> None:
    response = SimpleNamespace(
        usage_metadata={},
        response_metadata={
            "token_usage": {
                "prompt_tokens": 12,
                "completion_tokens": 5,
                "total_tokens": 17,
                "completion_tokens_details": {"reasoning_tokens": 3},
            }
        },
    )

    usage = extract_token_usage(response)

    assert usage["input_tokens"] == 12
    assert usage["output_tokens"] == 5
    assert usage["total_tokens"] == 17
    assert usage["reasoning_tokens"] == 3


def test_collect_llm_usage_from_state_histories() -> None:
    usage = collect_llm_usage(
        {
            "planner_history": [
                {
                    "planner_attempts": [
                        {"token_usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12}},
                        {"token_usage": {"input_tokens": 3, "output_tokens": 1, "total_tokens": 4}},
                    ]
                }
            ],
            "reviewer_history": [
                {"token_usage": {"input_tokens": 5, "output_tokens": 2, "total_tokens": 7}},
            ],
            "judge_history": [
                {"token_usage": {"input_tokens": 6, "output_tokens": 1, "total_tokens": 7}},
            ],
        }
    )

    assert usage["by_role"]["planner"]["total_tokens"] == 16
    assert usage["by_role"]["reviewer"]["total_tokens"] == 7
    assert usage["by_role"]["judge"]["total_tokens"] == 7
    assert usage["totals"]["total_tokens"] == 30
