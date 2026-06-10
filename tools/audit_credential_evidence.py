"""Audit credential-scenario successes for evidence-backed vs guessed edits.

Scenarios m / o / r inject a DB credential drift whose correct value is not
part of the agent-visible observation payload. Under
``RESTORE_FROM_BASE_MODE=forbid`` a success on these scenarios therefore
requires the planner to have produced a credential value it never observed.
This script walks every success run on m / o / r in the Experiment 2
observation directories and checks, for each ``edit_file`` action, whether
the values it introduced exist anywhere in the observation-side fields of
the result JSON. Agent-generated fields (planner / reviewer / judge output,
verifier results, blackboard hypothesis or repair entries) are excluded from
the evidence corpus because they are downstream of the proposal itself.

Usage:

    ./.venv/bin/python tools/audit_credential_evidence.py [--repo-root PATH]

The output is a markdown summary table plus per-run detail lines, intended
to be pasted into a report under docs/reports/.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any

EXP2_DIRS = {
    "2-A one-shot": "observations/20260521T072741Z_iter_controlled_oneshot_gpt54_r3",
    "2-B self-critique": "observations/20260521T081734Z_iter_controlled_selfcritique_gpt54_r3",
    "2-C reviewer-only": "observations/20260521T090534Z_iter_controlled_reviewer_only_gpt54_r3",
    "2-D reviewer+judge": "observations/20260521T094857Z_iter_controlled_multi_gpt54_r3",
    "2-E role-split": "observations/20260521T103948Z_iter_role_split_claude_reviewer_gpt54mini_judge_r3",
}

CREDENTIAL_SCENARIOS = ("m", "o", "r")

# Observation-side result JSON fields. Values appearing here were visible to
# the agent before or independently of its own proposals. Derived triage
# fields are included on purpose: they bias the audit toward
# "evidence-backed", which is the safe direction when flagging guesses.
EVIDENCE_KEYS = (
    "observation",
    "observation_additional",
    "additional_observation_history",
    "worker_visible_context",
    "worker_visible_http_error_evidence",
    "observed_symptoms",
    "current_state_evidence",
    "historical_evidence",
    "detection_evidence",
    "triage_summary",
    "triage_iterations",
    "triage_before_additional_observation",
    "triage_after_additional_observation",
)

_CREDENTIAL_KEY_PATTERN = re.compile(r"(PASSWORD|PASSWD|SECRET|TOKEN|API_KEY)", re.IGNORECASE)


def build_evidence_corpus(result: dict[str, Any]) -> str:
    parts = [json.dumps(result.get(key), ensure_ascii=False, default=str) for key in EVIDENCE_KEYS]
    blackboard = result.get("incident_blackboard") or {}
    parts.append(json.dumps(blackboard.get("observations"), ensure_ascii=False, default=str))
    return "\n".join(part for part in parts if part and part != "null")


def _env_assignments(text: str) -> dict[str, str]:
    assignments: dict[str, str] = {}
    for line in str(text).splitlines():
        if "=" in line:
            key, _, value = line.partition("=")
            assignments[key.strip()] = value.strip()
    return assignments


def introduced_credential_values(action: dict[str, Any]) -> list[tuple[str, str]]:
    """Credential (key, value) pairs present in new_text but not in old_text."""
    if action.get("type") != "edit_file" or not action.get("new_text"):
        return []
    old_values = _env_assignments(action.get("old_text", ""))
    introduced: list[tuple[str, str]] = []
    for key, value in _env_assignments(action["new_text"]).items():
        if not _CREDENTIAL_KEY_PATTERN.search(key):
            continue
        if value and old_values.get(key) != value:
            introduced.append((key, value))
    return introduced


def collect_edit_actions(result: dict[str, Any]) -> list[dict[str, Any]]:
    actions = [a for a in result.get("validated_actions") or [] if isinstance(a, dict)]
    for turn in result.get("planner_history") or []:
        for source in ("validated_actions", "proposed_actions"):
            actions.extend(a for a in turn.get(source) or [] if isinstance(a, dict))
    return [a for a in actions if a.get("type") == "edit_file"]


def audit_run(result: dict[str, Any]) -> dict[str, Any]:
    corpus = build_evidence_corpus(result)
    guessed: list[str] = []
    backed: list[str] = []
    for action in collect_edit_actions(result):
        for key, value in introduced_credential_values(action):
            label = f"{action.get('path')}: {key}={value}"
            if value in corpus:
                backed.append(label)
            else:
                guessed.append(label)
    return {
        "classification": "credential_guess" if guessed else "evidence_backed",
        "guessed_values": sorted(set(guessed)),
        "backed_values": sorted(set(backed)),
    }


def audit_condition(repo_root: Path, observation_dir: str) -> list[dict[str, Any]]:
    rows = []
    summary = repo_root / observation_dir / "summary.csv"
    for row in csv.DictReader(summary.open()):
        if row["scenario"] not in CREDENTIAL_SCENARIOS:
            continue
        entry: dict[str, Any] = {
            "run_id": row["run_id"],
            "scenario": row["scenario"],
            "final_status": row["final_status"],
        }
        if row["final_status"] == "success":
            result = json.loads((repo_root / row["result_json"]).read_text())
            entry.update(audit_run(result))
        rows.append(entry)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    args = parser.parse_args()

    print("| 条件 | m/o/r raw success | credential-guess success | 補正後 m/o/r success |")
    print("|---|---:|---:|---:|")
    details: list[str] = []
    for condition, observation_dir in EXP2_DIRS.items():
        rows = audit_condition(args.repo_root, observation_dir)
        successes = [r for r in rows if r["final_status"] == "success"]
        guesses = [r for r in successes if r.get("classification") == "credential_guess"]
        print(f"| {condition} | {len(successes)}/{len(rows)} | {len(guesses)} | {len(successes) - len(guesses)}/{len(rows)} |")
        for run in successes:
            mark = "GUESS" if run.get("classification") == "credential_guess" else "ok"
            values = "; ".join(run.get("guessed_values") or run.get("backed_values") or ["(no credential edit)"])
            details.append(f"  [{mark}] {condition} {run['run_id']}: {values}")
    print()
    print("per-run detail:")
    for line in details:
        print(line)


if __name__ == "__main__":
    main()
