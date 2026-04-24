from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from experimental.production_poc.runtime_prod.models import ProposedAction


@dataclass(frozen=True)
class ApprovalDecision:
    approved: bool
    approval_id: str
    path: str
    reason: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class ApprovalStore(Protocol):
    def check(self, action: ProposedAction) -> ApprovalDecision:
        """Return whether a proposed medium-risk action has human approval."""


class NullApprovalStore:
    def check(self, action: ProposedAction) -> ApprovalDecision:
        approval_id = approval_id_for_action(action)
        return ApprovalDecision(
            approved=False,
            approval_id=approval_id,
            path="",
            reason="No approval_dir is configured for medium-risk actions.",
        )


class FileApprovalStore:
    """File-based approval gate for small human-in-the-loop experiments."""

    def __init__(self, approval_dir: Path) -> None:
        self._approval_dir = approval_dir

    def check(self, action: ProposedAction) -> ApprovalDecision:
        approval_id = approval_id_for_action(action)
        approval_path = self._approval_dir / f"{approval_id}.approved"
        if approval_path.exists() and approval_path.is_file():
            return ApprovalDecision(
                approved=True,
                approval_id=approval_id,
                path=str(approval_path),
                reason="Approval file exists.",
            )
        return ApprovalDecision(
            approved=False,
            approval_id=approval_id,
            path=str(approval_path),
            reason=f"Create approval file {approval_path} to allow this medium-risk action.",
        )


def approval_id_for_action(action: ProposedAction) -> str:
    runbook_id = str(action.metadata.get("runbook_id", "")).strip()
    label = runbook_id or action.service.strip() or action.kind
    safe_label = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in label)[:40]
    payload = {
        "kind": action.kind,
        "service": action.service,
        "runbook_id": runbook_id,
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    return f"{action.kind}-{safe_label}-{digest}"
