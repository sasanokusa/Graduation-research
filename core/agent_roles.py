from enum import Enum


class AgentRole(str, Enum):
    SINGLE_AGENT = "single_agent"
    PLANNER = "planner"
    REVIEWER = "reviewer"
    JUDGE = "judge"
    TRIAGE = "triage"


def role_env_prefix(role: AgentRole) -> str:
    return role.value.upper()
