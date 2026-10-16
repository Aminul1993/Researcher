"""Graph state, API records and the models' structured-output schemas."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Annotated, Any, Protocol, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field, model_validator

from .config import SKILLS


# =====================================================================
# Graph state and records
# =====================================================================
class DynamicAgentState(TypedDict):
    """Shared state passed between the supervisor and the agents."""

    messages: Annotated[Sequence[BaseMessage], add_messages]
    task_description: str
    team_members: list[str]
    next_agent: str  # Who speaks next, or FINISH when the work is done
    routing_reason: str  # The supervisor's explanation for that choice


@dataclass(frozen=True)
class Team:
    """The agents assembled for one task."""

    registry: dict[str, str]  # Agent name -> role prompt
    skills: dict[str, str]  # Agent name -> skill (a key of SKILLS)
    generated: bool  # False when the fallback team is used


class AgentProfile(TypedDict):
    """A team member as exposed to API clients."""

    name: str
    role: str
    skill: str
    model: str


class StepRecord(TypedDict):
    """One agent contribution, in the order it was produced."""

    step: int
    agent: str
    message: str
    reason: str
    model: str


class WorkflowResult(TypedDict):
    """The complete outcome of a workflow run."""

    task: str
    run_id: str
    team: list[AgentProfile]
    team_generated: bool
    models: dict[str, str]
    steps: list[StepRecord]
    final_response: str


WorkflowEvent = dict[str, Any]


class AgentNode(Protocol):
    """A graph node: reads the state, returns the keys to update."""

    def __call__(self, state: DynamicAgentState) -> dict[str, Any]: ...


# Returns the chat model for a role or skill name.
ChatModelFactory = Callable[[str], BaseChatModel]


# =====================================================================
# Structured output schemas
# =====================================================================
class RouterSchema(BaseModel):
    """Structured output that forces the supervisor to pick the next step."""

    next_agent: str = Field(
        description=(
            "The name of the next agent to invoke, or 'FINISH' if the task "
            "is complete."
        )
    )
    reasoning: str = Field(
        description="Explanation of why this agent was chosen."
    )


# Field names models use, in order of preference, when they do not follow
# the AgentSpec schema exactly.
_AGENT_NAME_KEYS = ("name", "agent", "agent_name", "title", "role")
_ROLE_PROMPT_KEYS = (
    "role_prompt",
    "prompt",
    "instructions",
    "description",
    "responsibility",
    "role",
)
_SKILL_KEYS = (
    "skill",
    "specialty",
    "speciality",
    "specialization",
    "expertise",
    "category",
    "type",
)


def _default_role(name: str) -> str:
    return f"Contribute your expertise as the team's {name.strip()}."


class AgentSpec(BaseModel):
    """One specialist agent proposed by the team designer."""

    name: str = Field(
        description="Short role name, such as 'Planner' or 'Data Analyst'."
    )
    role_prompt: str = Field(
        description="Imperative instructions for what this agent produces."
    )
    skill: str = Field(
        default="",
        description=f"The agent's skill, one of: {', '.join(SKILLS)}.",
    )

    @model_validator(mode="before")
    @classmethod
    def _normalise(cls, value: Any) -> Any:
        """Accept the shapes models commonly send instead of the schema.

        Seen in practice: plain 'Name' or 'Name: role' strings, and objects
        keyed ``role``/``prompt`` instead of ``name``/``role_prompt``.
        """
        if isinstance(value, str):
            name, _, role = value.partition(":")
            role = role.strip() or _default_role(name)
            return {"name": name, "role_prompt": role, "skill": ""}
        if not isinstance(value, dict):
            return value

        def text(key: str) -> str:
            return str(value.get(key) or "").strip()

        name_key = next((k for k in _AGENT_NAME_KEYS if text(k)), None)
        if name_key is None:
            return value
        role_prompt = next(
            (text(k) for k in _ROLE_PROMPT_KEYS if k != name_key and text(k)),
            "",
        )
        return {
            "name": text(name_key),
            "role_prompt": role_prompt or _default_role(text(name_key)),
            "skill": next((text(k) for k in _SKILL_KEYS if text(k)), ""),
        }


class TeamSchema(BaseModel):
    """Structured output describing the team generated for a task."""

    agents: list[AgentSpec] = Field(
        description=(
            "The specialist agents, in the order they would typically "
            "contribute."
        )
    )
