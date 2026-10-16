"""Designing the team of agents for a task, and each agent's skill."""

import logging
import re
from collections.abc import Callable, Mapping, Sequence

from langchain_core.exceptions import OutputParserException
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import Runnable, RunnableConfig

from .config import (
    GENERAL_SKILL,
    MAX_AGENT_NAME_LENGTH,
    MAX_AGENTS,
    MAX_ROLE_PROMPT_LENGTH,
    RESERVED_NAMES,
    ROLE_DESIGNER,
    SKILLS,
    STRUCTURED_OUTPUT_METHOD,
    get_role_model_name,
)
from .messages import name_key
from .models import with_fallback
from .schemas import (
    AgentProfile,
    AgentSpec,
    ChatModelFactory,
    Team,
    TeamSchema,
)

logger = logging.getLogger(__name__)

# Keyword rules used when the designer omits a skill or invents one. They
# are checked in order, so a "Code Reviewer" counts as a reviewer.
_SKILL_PATTERNS: tuple[tuple[str, str], ...] = (
    ("review", r"review|critic|\bqa\b|test|audit|verif|check|validat"),
    ("coding", r"\bcod|program|develop|engineer|implement|debug|script"),
    ("analysis", r"analy|data|statist|math|calcul|quant"),
    ("research", r"research|search|investigat|fact|scout|histor"),
    ("planning", r"plan|strateg|architect|outline|design|organi"),
    ("writing", r"writ|edit|author|copy|document|content|market"),
)

# Used only when the team designer cannot produce a usable team.
FALLBACK_AGENT_REGISTRY: dict[str, str] = {
    "Planner": "Create a step-by-step layout plan to fulfill the request.",
    "Researcher": "Provide factual analysis, statistics, or reference APIs.",
    "Coder": (
        "Write clean, idiomatic Python code blocks based on requirements."
    ),
    "Reviewer": (
        "Audit text or code for bugs, quality issues, or logic errors. "
        "Approve or request changes."
    ),
}

_SKILL_MENU = "; ".join(
    f"{skill} ({about})" for skill, about in SKILLS.items()
)

TEAM_DESIGNER_PROMPT = (
    "You design a small team of specialist AI agents for the user's task. "
    "A supervisor will route work between the agents and a team lead will "
    "merge their work into the final answer, so do not create supervisor, "
    "manager, coordinator or summarizer roles.\n\n"
    "Rules:\n"
    f"- Create 2 to {MAX_AGENTS} agents with distinct, non-overlapping "
    "responsibilities. Use fewer agents for simple tasks.\n"
    "- List them in the order they would typically contribute.\n"
    "- Give each agent a short role name of one or two words, such as "
    "'Planner' or 'Data Analyst'.\n"
    "- Write each role prompt as one or two imperative sentences that say "
    "exactly what the agent must produce.\n"
    "- Give each agent the skill that best matches its job, chosen from: "
    f"{_SKILL_MENU}.\n"
    "- When the task involves code, facts or calculations, include an agent "
    "that reviews the work for errors."
)


# =====================================================================
# Skills
# =====================================================================
def infer_skill(*texts: str) -> str:
    """Guess a skill from free text such as an agent's name or role."""
    for text in texts:
        for skill, pattern in _SKILL_PATTERNS:
            if text and re.search(pattern, text, flags=re.IGNORECASE):
                return skill
    return GENERAL_SKILL


def resolve_skill(proposed: str, name: str, role_prompt: str) -> str:
    """Return a valid skill, inferring one when the proposal is unusable."""
    skill = proposed.strip().lower()
    if skill in SKILLS:
        return skill
    return infer_skill(proposed, name, role_prompt)


def resolve_agent_skills(
    agent_registry: Mapping[str, str],
    agent_skills: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Return a valid skill for every agent in a registry."""
    given = agent_skills or {}
    return {
        name: resolve_skill(given.get(name, ""), name, role_prompt)
        for name, role_prompt in agent_registry.items()
    }


def team_profiles(
    team: Team, model_label: Callable[[str], str] | None = None
) -> list[AgentProfile]:
    """Describe a team for API clients, including each agent's model.

    ``model_label`` maps a skill to the model name to report. It defaults to
    each skill's configured Ollama model.
    """
    label = model_label or get_role_model_name
    profiles: list[AgentProfile] = []
    for name, role in team.registry.items():
        skill = team.skills.get(name) or infer_skill(name, role)
        profiles.append(
            AgentProfile(name=name, role=role, skill=skill, model=label(skill))
        )
    return profiles


# =====================================================================
# Team design
# =====================================================================
def create_team_designer(llm: BaseChatModel) -> Runnable:
    """Create the runnable that designs a team of agents for a task."""
    prompt = ChatPromptTemplate.from_messages([
        ("system", TEAM_DESIGNER_PROMPT),
        MessagesPlaceholder(variable_name="messages"),
    ])
    return prompt | llm.with_structured_output(
        TeamSchema, method=STRUCTURED_OUTPUT_METHOD
    )


def _clean_agent_name(raw: str) -> str:
    """Turn a proposed name into a short, title-cased display name."""
    words = re.findall(r"[^\W_]+", raw)[:3]
    name = " ".join(word[:1].upper() + word[1:] for word in words)
    return name[:MAX_AGENT_NAME_LENGTH].strip()


def _sanitize_team(
    specs: Sequence[AgentSpec],
) -> tuple[dict[str, str], dict[str, str]]:
    """Build a registry and skill map from proposed agents.

    Skips agents with empty names or prompts, duplicate names and names that
    clash with the supervisor, finalizer or FINISH, and caps the team size.
    """
    reserved = {name_key(name) for name in RESERVED_NAMES}
    registry: dict[str, str] = {}
    skills: dict[str, str] = {}
    seen: set = set()
    for spec in specs:
        name = _clean_agent_name(spec.name)
        role = " ".join(spec.role_prompt.split())[:MAX_ROLE_PROMPT_LENGTH]
        key = name_key(name)
        if not key or not role or key in reserved or key in seen:
            logger.debug("Skipping proposed agent %r", spec.name)
            continue
        seen.add(key)
        registry[name] = role
        skills[name] = resolve_skill(spec.skill, name, role)
        if len(registry) == MAX_AGENTS:
            break
    return registry, skills


def _fallback_team() -> Team:
    registry = dict(FALLBACK_AGENT_REGISTRY)
    return Team(registry, resolve_agent_skills(registry), generated=False)


def generate_agent_registry(
    task: str,
    models: ChatModelFactory,
    config: RunnableConfig | None = None,
) -> Team:
    """Generate the agent registry, with a skill per agent, for a task.

    If the model's proposal cannot be parsed or contains no usable agents,
    the team built from ``FALLBACK_AGENT_REGISTRY`` is returned instead.
    Connection and authentication errors are not caught. ``config`` is
    passed to the model call, for example to attach callbacks.
    """
    designer = with_fallback(models, ROLE_DESIGNER, create_team_designer)
    try:
        proposal = designer.invoke(
            {"messages": [HumanMessage(content=task)]}, config
        )
    except (OutputParserException, ValueError) as exc:
        logger.warning(
            "Team generation returned invalid output (%s); using the "
            "fallback team",
            type(exc).__name__,
        )
        return _fallback_team()

    registry, skills = _sanitize_team(
        proposal.agents if isinstance(proposal, TeamSchema) else []
    )
    if not registry:
        logger.warning("Team generation proposed no usable agents; "
                       "using the fallback team")
        return _fallback_team()

    logger.info(
        "Generated team: %s",
        ", ".join(f"{name} ({skills[name]})" for name in registry),
    )
    return Team(registry, skills, generated=True)
