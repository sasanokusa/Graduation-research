from __future__ import annotations

from typing import Any


TOKEN_USAGE_KEYS = (
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "reasoning_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)


def empty_token_usage() -> dict[str, int]:
    return {key: 0 for key in TOKEN_USAGE_KEYS}


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if value is None:
        return {}
    result: dict[str, Any] = {}
    for key in dir(value):
        if key.startswith("_"):
            continue
        try:
            item = getattr(value, key)
        except Exception:
            continue
        if not callable(item):
            result[key] = item
    return result


def _to_int(value: Any) -> int:
    if value is None or value == "":
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return 0


def _first_int(source: dict[str, Any], keys: tuple[str, ...]) -> int:
    for key in keys:
        if key in source:
            value = _to_int(source.get(key))
            if value:
                return value
    return 0


def _merge_usage(target: dict[str, int], source: dict[str, Any]) -> None:
    input_tokens = _first_int(
        source,
        ("input_tokens", "prompt_tokens", "prompt_token_count", "input_token_count"),
    )
    output_tokens = _first_int(
        source,
        ("output_tokens", "completion_tokens", "candidates_token_count", "output_token_count"),
    )
    total_tokens = _first_int(
        source,
        ("total_tokens", "total_token_count"),
    )

    if input_tokens:
        target["input_tokens"] = max(target["input_tokens"], input_tokens)
    if output_tokens:
        target["output_tokens"] = max(target["output_tokens"], output_tokens)
    if total_tokens:
        target["total_tokens"] = max(target["total_tokens"], total_tokens)

    input_details = _as_dict(source.get("input_token_details"))
    output_details = _as_dict(source.get("output_token_details"))
    completion_details = _as_dict(source.get("completion_tokens_details"))
    prompt_details = _as_dict(source.get("prompt_tokens_details"))

    target["reasoning_tokens"] = max(
        target["reasoning_tokens"],
        _first_int(output_details, ("reasoning", "reasoning_tokens", "thinking_tokens"))
        or _first_int(completion_details, ("reasoning_tokens", "reasoning"))
        or _first_int(source, ("reasoning_tokens", "thinking_tokens", "thoughts_token_count")),
    )
    target["cache_read_input_tokens"] = max(
        target["cache_read_input_tokens"],
        _first_int(input_details, ("cache_read", "cache_read_input_tokens"))
        or _first_int(prompt_details, ("cached_tokens", "cache_read_input_tokens"))
        or _first_int(source, ("cache_read_input_tokens", "cached_tokens")),
    )
    target["cache_creation_input_tokens"] = max(
        target["cache_creation_input_tokens"],
        _first_int(input_details, ("cache_creation", "cache_creation_input_tokens"))
        or _first_int(source, ("cache_creation_input_tokens",)),
    )


def extract_token_usage(response: Any) -> dict[str, int]:
    usage = empty_token_usage()
    candidates: list[dict[str, Any]] = []

    usage_metadata = _as_dict(getattr(response, "usage_metadata", None))
    if usage_metadata:
        candidates.append(usage_metadata)

    response_metadata = _as_dict(getattr(response, "response_metadata", None))
    if response_metadata:
        candidates.append(response_metadata)
        for key in ("token_usage", "usage", "usage_metadata"):
            nested = _as_dict(response_metadata.get(key))
            if nested:
                candidates.append(nested)

    for candidate in candidates:
        _merge_usage(usage, candidate)

    if not usage["total_tokens"] and (usage["input_tokens"] or usage["output_tokens"]):
        usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
    return usage


def sum_token_usage(records: list[dict[str, Any]]) -> dict[str, int]:
    total = empty_token_usage()
    for record in records:
        usage = record.get("token_usage", record)
        if not isinstance(usage, dict):
            continue
        for key in TOKEN_USAGE_KEYS:
            total[key] += _to_int(usage.get(key))
    return total


def collect_llm_usage(state: dict[str, Any]) -> dict[str, Any]:
    planner_records: list[dict[str, Any]] = []
    planner_history = state.get("planner_history", [])
    if planner_history:
        for entry in planner_history:
            planner_records.extend(entry.get("planner_attempts", []) or [])
    else:
        planner_records.extend(state.get("planner_attempts", []) or [])

    reviewer_records = state.get("reviewer_history", []) or []
    judge_records = state.get("judge_history", []) or []

    triage_records: list[dict[str, Any]] = []
    for iteration in state.get("triage_iterations", []) or []:
        if iteration.get("token_usage"):
            triage_records.append(iteration)
        elif iteration.get("llm_metadata", {}):
            triage_records.append(iteration["llm_metadata"])

    by_role = {
        "planner": sum_token_usage(planner_records),
        "reviewer": sum_token_usage(reviewer_records),
        "judge": sum_token_usage(judge_records),
        "triage": sum_token_usage(triage_records),
    }
    totals = empty_token_usage()
    for role_total in by_role.values():
        for key in TOKEN_USAGE_KEYS:
            totals[key] += role_total[key]

    return {
        "totals": totals,
        "by_role": by_role,
    }
