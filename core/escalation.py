from __future__ import annotations

import os
from typing import Any


def planner_escalation_enabled() -> bool:
    value = os.getenv("PLANNER_ESCALATION_MODE", "disabled").strip().lower()
    return value not in {"", "0", "false", "no", "off", "disabled", "none"}


def planner_escalation_mode() -> str:
    return os.getenv("PLANNER_ESCALATION_MODE", "disabled").strip().lower()


def planner_escalation_on_retry_enabled() -> bool:
    return planner_escalation_mode() in {"on_retry", "retry", "retry_only"}


def planner_escalation_triggers() -> set[str]:
    raw = os.getenv(
        "PLANNER_ESCALATION_TRIGGERS",
        "reviewer_request,judge_request",
    )
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def planner_escalation_request_from_review(review: dict[str, Any]) -> tuple[bool, str]:
    requested = bool(review.get("escalate_planner", False))
    reason = str(review.get("escalation_reason", "")).strip()
    return requested, reason


def planner_escalation_request_from_judge(judge_result: dict[str, Any]) -> tuple[bool, str]:
    requested = bool(judge_result.get("escalate_planner", False))
    reason = str(judge_result.get("escalation_reason", "")).strip()
    return requested, reason


def should_use_requested_planner_escalation(state: dict[str, Any], *, source: str) -> tuple[bool, str]:
    if not planner_escalation_enabled():
        return False, "planner escalation is disabled"
    if not state.get("planner_escalation_requested", False):
        return False, "planner escalation was not requested"
    trigger = f"{source}_request"
    if trigger not in planner_escalation_triggers():
        return False, f"planner escalation trigger is disabled: {trigger}"
    max_per_run = _env_int("PLANNER_ESCALATION_MAX_PER_RUN", 1)
    if len(state.get("planner_escalation_history", [])) >= max_per_run:
        return False, "planner escalation budget is exhausted"
    return True, str(state.get("planner_escalation_reason", "")).strip()


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return int(float(value))
    except ValueError:
        return default
