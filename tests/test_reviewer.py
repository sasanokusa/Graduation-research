import json
from types import SimpleNamespace

from agents import reviewer as reviewer_module
from core.agent_factory import ChatModelBinding
from core.agent_roles import AgentRole
from core.settings import RoleModelSettings


def _settings() -> RoleModelSettings:
    return RoleModelSettings(
        role=AgentRole.REVIEWER,
        provider="anthropic",
        model="test-reviewer",
        api_key_env_name="ANTHROPIC_API_KEY",
        api_key="test",
        timeout_seconds=1,
        max_attempts=1,
        backoff_base_seconds=0,
        backoff_cap_seconds=0,
        thinking_level="low",
        thinking_budget=None,
        extra_options={},
    )


def test_reviewer_invocation_failure_retries_without_advancing_turn(monkeypatch) -> None:
    class FlakyClient:
        def __init__(self) -> None:
            self.calls = 0

        def invoke(self, _messages):
            self.calls += 1
            if self.calls == 1:
                raise TimeoutError("temporary network timeout")
            return SimpleNamespace(
                content=json.dumps(
                    {
                        "decision": "retry",
                        "summary": "retry after exposed fault",
                        "failure_analysis": "postcheck exposed another repairable fault",
                        "feedback_for_planner": "focus on app/main.py",
                        "suspected_remaining_domains": ["query_or_code_bug"],
                        "recommended_scope_adjustment": {
                            "editable_files": ["app/main.py"],
                            "services": ["app"],
                            "allowed_actions": ["edit_file"],
                        },
                        "recommended_next_observations": [],
                    }
                ),
                usage_metadata={"input_tokens": 11, "output_tokens": 7, "total_tokens": 18},
                response_metadata={},
            )

    client = FlakyClient()

    def fake_binding(_role):
        return ChatModelBinding(
            settings=_settings(),
            client=client,
            initialization_error_type="none",
            initialization_error_stage="none",
            initialization_error_message="",
        )

    monkeypatch.setenv("REVIEWER_INVOCATION_FAILURE_RETRIES", "1")
    monkeypatch.setattr(reviewer_module, "build_chat_model_binding", fake_binding)

    state = {
        "prompt_mode": "blind",
        "planner_turn": 2,
        "reviewer_history": [],
        "agent_role_trace": [],
        "role_model_trace": [],
        "suspected_domains": [],
        "candidate_scope": {},
        "ambiguity_level": "",
        "triage_summary": "",
        "observation": {},
        "proposed_actions": [],
        "verifier_precheck_result": {},
        "execution_result": {},
        "verifier_postcheck_result": {},
        "rollback_used": False,
        "rollback_result": {},
        "planner_history": [],
        "incident_blackboard": {},
    }

    result = reviewer_module.reviewer_node(state)

    assert client.calls == 2
    assert result["planner_turn"] == 2
    assert result["review_decision"] == "retry"
    assert result["reviewer_invocation_retry_count"] == 1
    assert result["reviewer_invocation_failed"] is False
    assert result["reviewer_token_usage"]["total_tokens"] == 18
