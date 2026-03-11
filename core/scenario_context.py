from typing import Any


WORKER_CONTEXT_MODE_NAMES = {
    "blind": "worker_visible_blind_v9",
    "hinted": "worker_visible_hinted_v9",
}


def get_worker_context_mode_name(prompt_mode: str) -> str:
    return WORKER_CONTEXT_MODE_NAMES[prompt_mode]


def _hinted_operational_hints(candidate_files: list[str]) -> list[str]:
    hints: list[str] = []
    if "nginx/nginx.conf" in candidate_files:
        hints.append(
            "Reverse-proxy and upstream mismatches are common recoverable issues. Prefer a direct evidence-backed config edit over generic restart-only plans."
        )
    if "app/main.py" in candidate_files:
        hints.append(
            "Application code or SQL regressions can produce endpoint-specific failures. Prefer the smallest evidence-backed code fix before rebuilding the app service."
        )
    if "app/requirements.txt" in candidate_files:
        hints.append(
            "Startup or dependency issues may be recoverable from the dependency definition. Prefer a minimal dependency fix visible in the logs."
        )
    if "app/app.env" in candidate_files:
        hints.append(
            "Environment mismatches can affect startup-time behavior and backend connectivity. Prefer restore_from_base over guessing unseen secret values."
        )
    return hints


def _trim_text(text: str, *, max_lines: int = 6, max_chars: int = 500) -> str:
    if not text:
        return ""
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    trimmed = "\n".join(lines)
    return trimmed[:max_chars]


def _summarize_compose_ps(compose_ps: dict[str, Any]) -> dict[str, Any]:
    services = compose_ps.get("services", [])
    if services:
        return {
            "services": [
                {
                    "service": service.get("Service"),
                    "state": service.get("State"),
                    "health": service.get("Health"),
                }
                for service in services
            ]
        }

    raw_stdout = compose_ps.get("raw", {}).get("stdout", "")
    return {"raw_excerpt": _trim_text(raw_stdout, max_lines=5, max_chars=400)}


def build_worker_visible_context(
    triage_output: dict[str, Any],
    observation: dict[str, Any],
    prompt_mode: str,
) -> dict[str, Any]:
    candidate_scope = triage_output.get("candidate_scope", {})
    candidate_files = list(candidate_scope.get("files", []))
    filtered_file_snippets = {
        path_value: snippet
        for path_value, snippet in observation.get("file_snippets", {}).items()
        if path_value in candidate_files
    }

    worker_visible_context: dict[str, Any] = {
        "suspected_domains": triage_output.get("suspected_domains", []),
        "candidate_scope": candidate_scope,
        "missing_evidence": triage_output.get("missing_evidence", []),
        "recommended_next_observations": triage_output.get("recommended_next_observations", []),
        "ambiguity_level": triage_output.get("ambiguity_level", "high"),
        "triage_summary": triage_output.get("triage_summary", ""),
        "observation": {
            "compose_ps": _summarize_compose_ps(observation.get("compose_ps", {})),
            "health_checks": observation.get("health_checks", {}),
            "file_snippets": filtered_file_snippets,
            "relevant_log_excerpts": {
                service: _trim_text(excerpt, max_lines=4, max_chars=320)
                for service, excerpt in observation.get("relevant_log_excerpts", {}).items()
                if excerpt
            },
            "http_error_evidence": observation.get("http_error_evidence", {}),
            "suspicious_patterns": observation.get("suspicious_patterns", {}),
            "static_observations": observation.get("static_observations", {}),
            "current_state_evidence": observation.get("current_state_evidence", []),
            "historical_evidence": observation.get("historical_evidence", []),
            "additional_observation": observation.get("additional_observation", {}),
        },
        "safety_constraints": {
            "single_turn_runner": True,
            "show_file_allowed": False,
            "edit_operations": ["replace_text", "restore_from_base"],
            "no_repository_wide_edits": True,
            "no_shell_commands": True,
            "restore_from_base_role": "last_resort",
            "prefer_minimal_patch_for_code_files": ["app/main.py"],
            "initial_code_restore_is_discouraged": True,
        },
    }

    if prompt_mode == "hinted":
        worker_visible_context["operational_hints"] = _hinted_operational_hints(candidate_files)

    return worker_visible_context
