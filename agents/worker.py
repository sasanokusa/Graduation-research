import os

from langchain_google_genai import ChatGoogleGenerativeAI

from core.actions import format_actions, parse_plan_text
from core.prompts import get_prompt_spec
from core.state import SingleAgentState


MODEL_NAME = "gemini-2.5-flash"
MODEL_TIMEOUT_SECONDS = 20
MODEL_MAX_RETRIES = 1


def _section(title: str) -> None:
    divider = "=" * 50
    print(divider)
    print(title)
    print(divider)


def _runtime_guidance(state: SingleAgentState) -> str:
    observation = state["worker_visible_context"].get("observation", {})
    snippets = observation.get("file_snippets", {})
    nginx_snippet = snippets.get("nginx/nginx.conf", "")
    env_snippet = snippets.get("app/app.env", "")
    http_error_evidence = observation.get("http_error_evidence", {})
    guidance_lines = [
        "Single-turn guidance:",
        "- Do not return show_file.",
        "- Stay within the proposed_scope from triage. Do not edit files or use actions outside that scope.",
        "- Do not return run_health_check for nginx_running, healthz_200, or api_items_200; verifier handles them.",
        "- If an editable file snippet already shows an exact faulty line, prioritize edit_file before any restart action.",
        "- If you return restart_compose_service, it must come after a state-changing edit_file action.",
        "- A plan containing only run_config_test and/or restart_compose_service is invalid when the observation already shows an editable fault.",
        "- If an editable env or config line appears wrong but the corrected value is not directly visible in the evidence, prefer restore_from_base over guessing.",
        "- If you edit startup-time settings such as app/app.env, prefer rebuild_compose_service for app instead of restart_compose_service.",
    ]
    if state["prompt_mode"] == "hinted":
        guidance_lines.append(
            "- Common recoverable faults here include configuration mismatches, startup/dependency issues, and service-to-service connection mismatches."
        )
    if state["prompt_mode"] == "hinted" and "server app:8001;" in nginx_snippet:
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
    return "\n".join(guidance_lines)


def worker_node(state: SingleAgentState) -> SingleAgentState:
    prompt_spec = get_prompt_spec(state["prompt_mode"])
    observation = state["worker_visible_context"].get("observation", {})
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        planner_output_raw = '{"summary":"GOOGLE_API_KEY is not set","actions":[]}'
        plan, parse_errors = parse_plan_text(
            planner_output_raw,
            forbidden_action_types={"show_file"},
        )
        _section("🧠 [PHASE 3] WORKER")
        print(f"mode: {state['worker_mode']}")
        print(f"prompt_mode: {state['prompt_mode']} ({prompt_spec['name']})")
        print(format_actions(plan["actions"]))
        print()
        return {
            **state,
            "system_prompt_name": prompt_spec["name"],
            "planner_output_raw": planner_output_raw,
            "planner_summary": plan["summary"],
            "normalized_actions": plan["actions"],
            "proposed_actions": plan["actions"],
            "verifier_precheck_result": {
                **state["verifier_precheck_result"],
                "planner_errors": parse_errors,
            },
        }

    model = ChatGoogleGenerativeAI(
        model=MODEL_NAME,
        google_api_key=api_key,
        temperature=0,
        timeout=MODEL_TIMEOUT_SECONDS,
        max_retries=MODEL_MAX_RETRIES,
        response_mime_type="application/json",
        transport="rest",
    )
    prompt = (
        f"Observed symptoms: {state['observed_symptoms']}\n"
        f"Triage output: {state['worker_visible_context'].get('triage', {})}\n"
        f"Relevant file snippets: {observation.get('file_snippets', {})}\n"
        f"Relevant log excerpts: {observation.get('relevant_log_excerpts', {})}\n"
        f"Suspicious patterns: {observation.get('suspicious_patterns', {})}\n"
        f"HTTP error evidence: {observation.get('http_error_evidence', {})}\n"
        f"{_runtime_guidance(state)}\n"
        f"Worker-visible context: {state['worker_visible_context']}\n"
    )

    try:
        print(f"[worker] invoking {MODEL_NAME} with timeout={MODEL_TIMEOUT_SECONDS}s")
        response = model.invoke(
            [
                ("system", prompt_spec["system_prompt"]),
                ("human", prompt),
            ],
            timeout=MODEL_TIMEOUT_SECONDS,
            max_retries=MODEL_MAX_RETRIES,
        )
        planner_output_raw = response.content if isinstance(response.content, str) else str(response.content)
    except Exception as exc:
        planner_output_raw = (
            '{"summary": "planner invocation failed: '
            + str(exc).replace('"', "'")
            + '", "actions": []}'
        )

    plan, parse_errors = parse_plan_text(
        planner_output_raw,
        forbidden_action_types={"show_file"},
    )
    _section("🧠 [PHASE 3] WORKER")
    print(f"mode: {state['worker_mode']}")
    print(f"prompt_mode: {state['prompt_mode']} ({prompt_spec['name']})")
    print(format_actions(plan["actions"]))
    print()
    return {
        **state,
        "system_prompt_name": prompt_spec["name"],
        "planner_output_raw": planner_output_raw,
        "planner_summary": plan["summary"],
        "normalized_actions": plan["actions"],
        "proposed_actions": plan["actions"],
        "verifier_precheck_result": {
            **state["verifier_precheck_result"],
            "planner_errors": parse_errors,
        },
    }
