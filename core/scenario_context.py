from typing import Any


WORKER_CONTEXT_MODE_NAMES = {
    "blind": "worker_visible_blind_v4",
    "hinted": "worker_visible_hinted_v4",
}


def get_worker_context_mode_name(prompt_mode: str) -> str:
    return WORKER_CONTEXT_MODE_NAMES[prompt_mode]


def _hinted_operational_hints(editable_files: list[str]) -> list[str]:
    hints: list[str] = []
    if "nginx/nginx.conf" in editable_files:
        hints.append(
            "A recoverable issue may exist in the editable reverse-proxy configuration. Prefer a direct evidence-backed config fix over restart-only plans."
        )
    if "app/requirements.txt" in editable_files:
        hints.append(
            "A recoverable startup issue may exist in the editable dependency definition. Prefer the smallest dependency or startup fix visible in the logs."
        )
    if "app/app.env" in editable_files:
        hints.append(
            "A recoverable service-to-service connectivity or credential mismatch may exist in the editable application environment settings."
        )
    return hints


def build_worker_visible_context(
    triage_output: dict[str, Any],
    observation: dict[str, Any],
    prompt_mode: str,
) -> dict[str, Any]:
    proposed_scope = triage_output.get("proposed_scope", {})
    editable_files = list(proposed_scope.get("editable_files", []))
    allowed_actions = list(proposed_scope.get("allowed_actions", []))
    filtered_file_snippets = {
        path_value: snippet
        for path_value, snippet in observation.get("file_snippets", {}).items()
        if path_value in editable_files
    }

    worker_visible_context: dict[str, Any] = {
        "editable_files": editable_files,
        "allowed_actions": allowed_actions,
        "triage": {
            "suspected_fault_class": triage_output.get("suspected_fault_class", "unknown"),
            "confidence": triage_output.get("confidence", 0.0),
            "evidence": triage_output.get("evidence", []),
            "proposed_scope": proposed_scope,
            "alternatives": triage_output.get("alternatives", []),
        },
        "observation": {
            "compose_ps": observation.get("compose_ps", {}),
            "service_logs": observation.get("service_logs", {}),
            "health_checks": observation.get("health_checks", {}),
            "file_snippets": filtered_file_snippets,
            "relevant_log_excerpts": observation.get("relevant_log_excerpts", {}),
            "http_error_evidence": observation.get("http_error_evidence", {}),
            "suspicious_patterns": observation.get("suspicious_patterns", {}),
        },
        "safety_constraints": {
            "single_turn_runner": True,
            "show_file_allowed": False,
            "edit_operations": ["replace_text", "restore_from_base"],
            "no_repository_wide_edits": True,
            "no_shell_commands": True,
        },
    }

    if prompt_mode == "hinted":
        worker_visible_context["operational_hints"] = _hinted_operational_hints(editable_files)

    return worker_visible_context
