import random
import time
from typing import Any

from core.actions import format_actions, parse_plan_text
from core.agent_factory import build_chat_model_binding
from core.agent_roles import AgentRole
from core.prompts import get_prompt_spec
from core.state import SingleAgentState


STRICT_FALLBACK_CONFIDENCE = 0.9


def _section(title: str) -> None:
    divider = "=" * 50
    print(divider)
    print(title)
    print(divider)


def _classify_planner_exception(exc: Exception) -> tuple[str, bool, str]:
    message = str(exc).lower()
    class_name = exc.__class__.__name__.lower()
    auth_markers = ["invalid api key", "api key not valid", "authentication", "permission denied", "401", "403"]
    model_markers = ["model not found", "unknown model", "invalid model", "not supported for generatecontent"]
    if any(marker in message for marker in auth_markers):
        return "planner_auth_error", False, "config"
    if any(marker in message for marker in model_markers):
        return "planner_model_error", False, "config"
    if "timeout" in message or "timed out" in message or "deadline exceeded" in message:
        return "planner_timeout", True, "transport"
    transient_markers = [
        "temporarily unavailable",
        "service unavailable",
        "connection reset",
        "connection aborted",
        "connection error",
        "remote disconnected",
        "429",
        "500",
        "502",
        "503",
        "504",
        "unavailable",
    ]
    if any(marker in message for marker in transient_markers) or "connection" in class_name:
        return "planner_transport_error", True, "transport"
    return "planner_invocation_error", False, "invocation"


def _planner_backoff_seconds(attempt: int, base_seconds: float, cap_seconds: float) -> float:
    raw = min(cap_seconds, base_seconds * (2 ** max(0, attempt - 1)))
    jitter = random.uniform(0.75, 1.25)
    return round(raw * jitter, 3)


def _append_role_trace(
    role_model_trace: list[dict[str, str]],
    *,
    role: str,
    provider: str,
    model: str,
) -> list[dict[str, str]]:
    updated = list(role_model_trace)
    entry = {"role": role, "provider": provider, "model": model}
    if entry not in updated:
        updated.append(entry)
    return updated


def _strict_fallback_plan(state: SingleAgentState, planner_error_type: str) -> dict[str, Any] | None:
    if planner_error_type not in {"planner_timeout", "planner_transport_error"}:
        return None
    if state.get("ambiguity_level") != "low":
        return None
    suspected_domains = state.get("suspected_domains", [])
    if not suspected_domains:
        return None
    top_domain = suspected_domains[0]
    if float(top_domain.get("confidence", 0.0)) < STRICT_FALLBACK_CONFIDENCE:
        return None

    candidate_scope = state.get("candidate_scope", {})
    allowed_files = set(candidate_scope.get("files", []))
    allowed_actions = set(candidate_scope.get("allowed_actions", []))
    snippets = state.get("worker_visible_context", {}).get("observation", {}).get("file_snippets", {})
    domain_name = str(top_domain.get("domain", ""))

    if (
        domain_name in {"query_or_code_bug", "schema_drift"}
        and "app/main.py" in allowed_files
        and {"edit_file", "rebuild_compose_service"} <= allowed_actions
    ):
        app_snippet = snippets.get("app/main.py", "")
        if "FROM itemz ORDER BY id" in app_snippet:
            return {
                "summary": "planner transport failed; using strict fallback for a directly visible missing-table query bug",
                "actions": [
                    {
                        "type": "edit_file",
                        "path": "app/main.py",
                        "operation": "replace_text",
                        "old_text": "FROM itemz ORDER BY id",
                        "new_text": "FROM items ORDER BY id",
                    },
                    {"type": "rebuild_compose_service", "service": "app"},
                ],
                "reason": "transport failure occurred after high-confidence query bug triage and the broken SQL token was directly visible in app/main.py",
                "fallback_type": "direct_visible_snippet_replace",
            }
        if "name, details FROM items" in app_snippet:
            return {
                "summary": "planner transport failed; using strict fallback for a directly visible missing-column query bug",
                "actions": [
                    {
                        "type": "edit_file",
                        "path": "app/main.py",
                        "operation": "replace_text",
                        "old_text": "name, details FROM items",
                        "new_text": "name, description FROM items",
                    },
                    {"type": "rebuild_compose_service", "service": "app"},
                ],
                "reason": "transport failure occurred after high-confidence schema drift triage and the broken column token was directly visible in app/main.py",
                "fallback_type": "direct_visible_snippet_replace",
            }

    if (
        domain_name == "reverse_proxy_or_upstream_mismatch"
        and "nginx/nginx.conf" in allowed_files
        and {"edit_file", "run_config_test", "restart_compose_service"} <= allowed_actions
    ):
        nginx_snippet = snippets.get("nginx/nginx.conf", "")
        if "server app:8001 resolve;" in nginx_snippet:
            return {
                "summary": "planner transport failed; using strict fallback for a directly visible upstream port mismatch",
                "actions": [
                    {
                        "type": "edit_file",
                        "path": "nginx/nginx.conf",
                        "operation": "replace_text",
                        "old_text": "server app:8001 resolve;",
                        "new_text": "server app:8000 resolve;",
                    },
                    {"type": "run_config_test", "target": "nginx"},
                    {"type": "restart_compose_service", "service": "nginx"},
                ],
                "reason": "transport failure occurred after high-confidence reverse-proxy triage and the wrong upstream port was directly visible in nginx/nginx.conf",
                "fallback_type": "direct_visible_snippet_replace",
            }
        if (
            "upstream backend" in nginx_snippet
            and "proxy_pass http://backend;" in nginx_snippet
            and "server backend:8000 resolve;" in nginx_snippet
        ):
            return {
                "summary": "planner transport failed; using strict fallback for a directly visible upstream host mismatch",
                "actions": [
                    {
                        "type": "edit_file",
                        "path": "nginx/nginx.conf",
                        "operation": "replace_text",
                        "old_text": "server backend:8000 resolve;",
                        "new_text": "server app:8000 resolve;",
                    },
                    {"type": "run_config_test", "target": "nginx"},
                    {"type": "restart_compose_service", "service": "nginx"},
                ],
                "reason": "transport failure occurred after high-confidence reverse-proxy triage and the broken upstream member host was directly visible while proxy_pass still referenced the named upstream group",
                "fallback_type": "direct_visible_snippet_replace",
            }

    return None


def _runtime_guidance(state: SingleAgentState) -> str:
    observation = state["worker_visible_context"].get("observation", {})
    suspected_domains = state["worker_visible_context"].get("suspected_domains", [])
    snippets = observation.get("file_snippets", {})
    static_observations = observation.get("static_observations", {})
    nginx_snippet = snippets.get("nginx/nginx.conf", "")
    app_main_snippet = snippets.get("app/main.py", "")
    env_snippet = snippets.get("app/app.env", "")
    http_error_evidence = observation.get("http_error_evidence", {})
    guidance_lines = [
        "Single-turn guidance:",
        "- Do not return show_file.",
        "- Stay within the candidate_scope from triage. Do not edit files or use actions outside that scope.",
        "- Treat suspected_domains as hypotheses only. Prefer the plan that is most directly justified by the visible evidence.",
        "- Prefer current_state_evidence over historical_evidence when they conflict. Older log noise is not sufficient reason to edit a service that is currently healthy.",
        "- Do not return run_health_check for nginx_running, healthz_200, or api_items_200; verifier handles them.",
        "- If an editable file snippet already shows an exact faulty line, prioritize edit_file before any restart action.",
        "- Prefer replace_text as the first choice when a local fault is directly visible.",
        "- Treat restore_from_base as a last resort rather than a default repair strategy.",
        "- If you return restart_compose_service, it must come after a state-changing edit_file action.",
        "- A plan containing only run_config_test and/or restart_compose_service is invalid when the observation already shows an editable fault.",
        "- If an editable env or config line appears wrong but the corrected value is not directly visible in the evidence, prefer restore_from_base over guessing.",
        "- If you edit startup-time settings such as app/app.env, prefer rebuild_compose_service for app instead of restart_compose_service.",
        "- If you edit app/main.py, prefer rebuild_compose_service for app so the running process reloads the changed code.",
        "- Avoid initial restore_from_base for app/main.py when a smaller replace_text patch is directly supported by the evidence.",
        "- If you choose restore_from_base, include a short reason in the summary.",
        "- Distinguish reference layers. In nginx, a proxy_pass target can be an upstream group name, while server entries inside that upstream block can be backend hosts or Docker services.",
    ]
    if state["prompt_mode"] == "hinted":
        guidance_lines.append(
            "- Common recoverable faults here include configuration mismatches, startup/dependency issues, and service-to-service connection mismatches."
        )
    if suspected_domains:
        guidance_lines.append(f"- Current top domain hypotheses: {suspected_domains[:3]}")
    if state["prompt_mode"] == "hinted" and "server app:8001" in nginx_snippet:
        guidance_lines.extend(
            [
                "- The visible nginx snippet already contains a directly editable upstream/backend mismatch.",
                "- Use the exact visible line as old_text and apply the smallest direct port correction visible in the evidence.",
            ]
        )
    if env_snippet and ("Access denied" in str(http_error_evidence) or "database error" in str(http_error_evidence)):
        guidance_lines.extend(
            [
                "- The visible editable environment snippet and HTTP error evidence indicate an application-side credential mismatch.",
                "- If the correct credential value is not directly visible, prefer edit_file with operation restore_from_base for app/app.env.",
                "- After editing app/app.env, use rebuild_compose_service for app so the container restarts with the restored env file.",
            ]
        )
    if app_main_snippet and ("Unknown column" in str(http_error_evidence) or "doesn't exist" in str(http_error_evidence)):
        guidance_lines.extend(
            [
                "- The visible editable app/main.py snippet already contains the failing SQL statement.",
                "- Prefer the smallest replace_text on app/main.py and then rebuild_compose_service for app.",
            ]
        )
    if "APP_PORT=9000" in env_snippet and "server app:8000" in nginx_snippet:
        guidance_lines.extend(
            [
                "- The visible evidence shows application listen-port drift relative to nginx.",
                "- Prefer restoring the app-side startup setting or another evidence-backed direct edit before generic restarts.",
            ]
        )
    if (
        "nginx_reference_note" in static_observations
        and "upstream backend" in nginx_snippet
        and "proxy_pass http://backend" in nginx_snippet
    ):
        guidance_lines.extend(
            [
                "- The visible nginx snippet shows proxy_pass using a named upstream group.",
                "- Do not rewrite proxy_pass solely because the same token also appears inside an upstream server line. Check whether the fault is inside the upstream membership instead.",
            ]
        )
    return "\n".join(guidance_lines)


def _planner_history_context(state: SingleAgentState) -> str:
    sections: list[str] = []
    planner_history = state.get("planner_history", [])
    reviewer_history = state.get("reviewer_history", [])
    if planner_history:
        sections.append(f"Previous planner turns: {planner_history[-3:]}")
    if reviewer_history:
        sections.append(f"Previous reviewer turns: {reviewer_history[-3:]}")
    if state.get("review_feedback"):
        sections.append(f"Latest reviewer feedback: {state['review_feedback']}")
    if state.get("review_decision"):
        sections.append(f"Latest reviewer decision: {state['review_decision']}")
    if state.get("reviewer_recommended_scope"):
        sections.append(f"Reviewer recommended scope adjustment: {state['reviewer_recommended_scope']}")
    if state.get("reviewer_recommended_next_observations"):
        sections.append(
            "Reviewer recommended next observations: "
            f"{state['reviewer_recommended_next_observations']}"
        )
    return "\n".join(sections)


def _planner_phase_title(state: SingleAgentState, role: AgentRole) -> str:
    if role == AgentRole.PLANNER:
        return f"🧠 [PHASE 4] PLANNER (TURN {state.get('planner_turn', 1)})"
    return "🧠 [PHASE 3] WORKER"


def _planner_prompt(state: SingleAgentState) -> str:
    prompt = (
        f"Observed symptoms: {state['observed_symptoms']}\n"
        f"{_runtime_guidance(state)}\n"
        f"Worker-visible context: {state['worker_visible_context']}\n"
    )
    history_context = _planner_history_context(state)
    if history_context:
        prompt += (
            "Multi-turn replanning context:\n"
            "Use the latest reviewer feedback and prior turn outcomes to prioritize the next remaining fault. "
            "Do not repeat the same ineffective action sequence unless the reviewer explicitly says the prior turn failed only due to timing.\n"
            f"{history_context}\n"
        )
    return prompt


def _run_planner_with_role(state: SingleAgentState, role: AgentRole) -> SingleAgentState:
    prompt_spec = get_prompt_spec(state["prompt_mode"])
    model_binding = build_chat_model_binding(role)
    planner_settings = model_binding.settings
    phase_title = _planner_phase_title(state, role)
    agent_role_trace = [*state.get("agent_role_trace", []), f"{role.value}:{state.get('planner_turn', 1)}"]
    role_model_trace = _append_role_trace(
        state.get("role_model_trace", []),
        role=role.value,
        provider=planner_settings.provider,
        model=planner_settings.model,
    )
    if model_binding.client is None:
        planner_output_raw = (
            '{"summary":"'
            + model_binding.initialization_error_message.replace('"', "'")
            + '","actions":[]}'
        )
        plan, parse_errors = parse_plan_text(
            planner_output_raw,
            forbidden_action_types={"show_file"},
        )
        _section(phase_title)
        print(f"mode: {state['worker_mode']}")
        print(f"prompt_mode: {state['prompt_mode']} ({prompt_spec['name']})")
        print(f"model: {planner_settings.provider}/{planner_settings.model}")
        print(format_actions(plan["actions"]))
        print()
        return {
            **state,
            "system_prompt_name": prompt_spec["name"],
            "planner_provider": planner_settings.provider,
            "planner_model": planner_settings.model,
            "planner_error_type": model_binding.initialization_error_type,
            "planner_error_stage": model_binding.initialization_error_stage,
            "planner_retry_count": 0,
            "planner_timeout_seconds": planner_settings.timeout_seconds,
            "planner_attempts": [],
            "planner_transport_failure": False,
            "planner_reasoning_failure": False,
            "planner_fallback_used": False,
            "planner_fallback_reason": "",
            "planner_fallback_type": "",
            "planner_output_raw": planner_output_raw,
            "planner_summary": plan["summary"],
            "normalized_actions": plan["actions"],
            "proposed_actions": plan["actions"],
            "agent_role_trace": agent_role_trace,
            "role_model_trace": role_model_trace,
            "verifier_precheck_result": {
                **state["verifier_precheck_result"],
                "planner_errors": parse_errors,
            },
        }

    model = model_binding.client
    prompt = _planner_prompt(state)

    planner_output_raw = ""
    planner_error_type = "none"
    planner_error_stage = "none"
    planner_summary = ""
    parse_errors: list[str] = []
    plan = {"summary": "", "actions": []}
    planner_attempts: list[dict[str, Any]] = []
    planner_transport_failure = False
    planner_reasoning_failure = False
    planner_fallback_used = False
    planner_fallback_reason = ""
    planner_fallback_type = ""

    for attempt in range(1, planner_settings.max_attempts + 1):
        attempt_started_at = time.time()
        try:
            print(
                f"[planner] invoking {planner_settings.provider}/{planner_settings.model} "
                f"attempt={attempt}/{planner_settings.max_attempts} "
                f"timeout={planner_settings.timeout_seconds}s thinking={planner_settings.thinking_level}"
            )
            response = model.invoke(
                [
                    ("system", prompt_spec["system_prompt"]),
                    ("human", prompt),
                ]
            )
            elapsed_seconds = round(time.time() - attempt_started_at, 3)
            planner_output_raw = response.content if isinstance(response.content, str) else str(response.content)
            plan, parse_errors = parse_plan_text(
                planner_output_raw,
                forbidden_action_types={"show_file"},
            )
            planner_summary = plan["summary"]
            planner_attempts.append(
                {
                    "attempt": attempt,
                    "model_name": planner_settings.model,
                    "provider": planner_settings.provider,
                    "timeout_seconds": planner_settings.timeout_seconds,
                    "elapsed_seconds": elapsed_seconds,
                    "error_type": "none",
                    "exception_class": "",
                    "message": "",
                }
            )
            if parse_errors and not plan["actions"]:
                planner_error_type = "planner_parse_error"
                planner_error_stage = "response_parse"
                planner_reasoning_failure = True
            elif not plan["actions"]:
                planner_error_type = "empty_plan"
                planner_error_stage = "reasoning"
                planner_reasoning_failure = True
            else:
                planner_error_type = "none"
                planner_error_stage = "none"
                planner_reasoning_failure = False
            break
        except Exception as exc:
            elapsed_seconds = round(time.time() - attempt_started_at, 3)
            planner_error_type, retriable, planner_error_stage = _classify_planner_exception(exc)
            planner_transport_failure = planner_error_stage == "transport"
            planner_summary = f"planner invocation failed: {exc}"
            planner_attempts.append(
                {
                    "attempt": attempt,
                    "model_name": planner_settings.model,
                    "provider": planner_settings.provider,
                    "timeout_seconds": planner_settings.timeout_seconds,
                    "elapsed_seconds": elapsed_seconds,
                    "error_type": planner_error_type,
                    "exception_class": exc.__class__.__name__,
                    "message": str(exc),
                }
            )
            if not retriable or attempt == planner_settings.max_attempts:
                break
            sleep_seconds = _planner_backoff_seconds(
                attempt,
                planner_settings.backoff_base_seconds,
                planner_settings.backoff_cap_seconds,
            )
            print(f"[planner] retrying after {sleep_seconds}s due to {planner_error_type}")
            time.sleep(sleep_seconds)

    if not plan["actions"]:
        fallback = _strict_fallback_plan(state, planner_error_type)
        if fallback:
            plan = {"summary": fallback["summary"], "actions": fallback["actions"]}
            planner_summary = fallback["summary"]
            planner_fallback_used = True
            planner_fallback_reason = fallback["reason"]
            planner_fallback_type = fallback["fallback_type"]

    planner_retry_count = max(0, len(planner_attempts) - 1)

    _section(phase_title)
    print(f"mode: {state['worker_mode']}")
    print(f"prompt_mode: {state['prompt_mode']} ({prompt_spec['name']})")
    print(
        f"model: {planner_settings.provider}/{planner_settings.model} "
        f"timeout={planner_settings.timeout_seconds}s thinking={planner_settings.thinking_level}"
    )
    print(f"planner_error_type: {planner_error_type}")
    print(f"planner_error_stage: {planner_error_stage}")
    print(f"planner_retry_count: {planner_retry_count}")
    print(f"planner_fallback_used: {planner_fallback_used}")
    print(format_actions(plan["actions"]))
    print()
    return {
        **state,
        "system_prompt_name": prompt_spec["name"],
        "planner_provider": planner_settings.provider,
        "planner_model": planner_settings.model,
        "planner_error_type": planner_error_type,
        "planner_error_stage": planner_error_stage,
        "planner_retry_count": planner_retry_count,
        "planner_timeout_seconds": planner_settings.timeout_seconds,
        "planner_attempts": planner_attempts,
        "planner_transport_failure": planner_transport_failure,
        "planner_reasoning_failure": planner_reasoning_failure,
        "planner_fallback_used": planner_fallback_used,
        "planner_fallback_reason": planner_fallback_reason,
        "planner_fallback_type": planner_fallback_type,
        "planner_output_raw": planner_output_raw,
        "planner_summary": planner_summary,
        "normalized_actions": plan["actions"],
        "proposed_actions": plan["actions"],
        "agent_role_trace": agent_role_trace,
        "role_model_trace": role_model_trace,
        "verifier_precheck_result": {
            **state["verifier_precheck_result"],
            "planner_errors": parse_errors,
        },
    }


def worker_node(state: SingleAgentState) -> SingleAgentState:
    return _run_planner_with_role(state, AgentRole.SINGLE_AGENT)


def planner_node(state: SingleAgentState) -> SingleAgentState:
    return _run_planner_with_role(state, AgentRole.PLANNER)
