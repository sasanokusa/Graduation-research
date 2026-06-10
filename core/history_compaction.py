"""Tail-limited history views for reviewer / judge prompt contexts.

Multi-turn runs re-send every prior turn's full planner attempts and
critiques to the reviewer and judge, which makes their input grow by
several thousand tokens per turn. ``MULTI_AGENT_HISTORY_TAIL`` bounds
that growth: the newest N history entries are embedded verbatim and
older entries are replaced with compact digests. ``0`` (default) keeps
the current full-history behavior so controlled experiments are not
affected unless the variable is set explicitly.
"""

from __future__ import annotations

import os
from typing import Any

_PLANNER_DIGEST_KEYS = (
    "turn",
    "summary",
    "precheck_ok",
    "execution_ok",
    "postcheck_ok",
    "rollback_used",
    "planner_escalation_used",
)

_REVIEWER_DIGEST_KEYS = (
    "turn",
    "decision",
    "summary",
    "feedback_for_planner",
)


def history_tail() -> int:
    raw = os.environ.get("MULTI_AGENT_HISTORY_TAIL", "0")
    try:
        return max(int(raw), 0)
    except ValueError:
        return 0


def _digest(entry: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    compacted: dict[str, Any] = {key: entry.get(key) for key in keys if key in entry}
    compacted["compacted"] = True
    return compacted


def _compact(entries: list[dict[str, Any]], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    tail = history_tail()
    if tail <= 0 or len(entries) <= tail:
        return entries
    digests = [_digest(entry, keys) for entry in entries[:-tail]]
    return [*digests, *entries[-tail:]]


def compact_planner_history(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compacted = _compact(entries, _PLANNER_DIGEST_KEYS)
    if compacted is entries:
        return entries
    for digest, original in zip(compacted, entries):
        if digest.get("compacted"):
            digest["proposed_action_count"] = len(original.get("proposed_actions", []))
    return compacted


def compact_reviewer_history(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _compact(entries, _REVIEWER_DIGEST_KEYS)


# Heavy lists carry full evidence / scope / reasoning per entry; their old
# entries digest to these keys. Lists absent here (turn_events,
# failure_history, additional_observation_requests, ...) stay untouched
# because they are already compact.
_BLACKBOARD_DIGEST_KEYS: dict[str, tuple[str, ...]] = {
    "observations": (
        "turn",
        "source",
        "front_most_failure",
        "healthz_status",
        "api_items_status",
        "topology_status",
        "additional_observation_count",
    ),
    "hypotheses": (
        "turn",
        "detected_fault_class",
        "detection_confidence",
        "ambiguity_level",
        "summary",
    ),
    "repair_candidates": ("turn", "summary", "planner_error_type"),
    "execution_results": ("turn", "ok", "rollback_used"),
    "verification_results": ("turn", "stage", "ok", "front_most_failure"),
    "reviewer_guidance": ("turn", "decision", "feedback_for_planner"),
    "judge_decisions": ("turn", "decision", "override"),
}


def compact_incident_blackboard(blackboard: dict[str, Any]) -> dict[str, Any]:
    tail = history_tail()
    if tail <= 0 or not blackboard:
        return blackboard
    compacted = dict(blackboard)
    for key, digest_keys in _BLACKBOARD_DIGEST_KEYS.items():
        entries = blackboard.get(key)
        if isinstance(entries, list) and len(entries) > tail:
            compacted[key] = _compact(entries, digest_keys)
    return compacted
