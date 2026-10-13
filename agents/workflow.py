"""LangGraph multi-agent workflow driven by a dynamic supervisor.

For every task, a team designer LLM call first generates the agent registry:
a small set of specialist agents, each with a role prompt and a skill
tailored to the task. Every skill maps to the model best suited to it, so a
coder, a reviewer and a writer can each run on a different model. A
supervisor then routes work between the agents until it decides the task is
complete, and a finalizer node consolidates the team's contributions into a
single answer.

Configuration (environment variables):
    OLLAMA_API_KEY       Ollama Cloud API key (required).
    OLLAMA_HOST          Server URL, default https://ollama.com.
    OLLAMA_MODEL         Default model, and the fallback for every role.
    OLLAMA_MODEL_<ROLE>  Per-role override such as OLLAMA_MODEL_CODING.
                         Roles are the keys of DEFAULT_ROLE_MODELS.
"""

import logging
import os
import re
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import (
    Annotated,
    Any,
    Callable,
    Dict,
    Iterator,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    TypedDict,
)

import httpx
from langchain_core.exceptions import OutputParserException
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import Runnable, RunnableLambda
from langchain_ollama import ChatOllama
from langgraph.errors import GraphRecursionError
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph
from ollama import ResponseError
from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)

# =====================================================================
# Configuration
# =====================================================================
DEFAULT_HOST = "https://ollama.com"
DEFAULT_MODEL = "gpt-oss:120b"
PLACEHOLDER_API_KEY = "your-ollama-api-key"
REQUEST_TIMEOUT_SECONDS = 300.0
RECURSION_LIMIT = 25

SUPERVISOR = "Supervisor"
FINALIZER = "Finalizer"
FINISH = "FINISH"
RESERVED_NAMES = frozenset({SUPERVISOR, FINALIZER, FINISH})

MAX_AGENTS = 5
MAX_AGENT_NAME_LENGTH = 40
MAX_ROLE_PROMPT_LENGTH = 400

# Ollama Cloud models such as gpt-oss ignore the JSON-schema ``format``
# option and reply in prose, but they follow tool calls reliably.
STRUCTURED_OUTPUT_METHOD = "function_calling"

# Orchestration roles. Agents are assigned one of the SKILLS below instead.
ROLE_SUPERVISOR = "supervisor"
ROLE_DESIGNER = "designer"
ROLE_FINALIZER = "finalizer"
GENERAL_SKILL = "general"

# Skills the team designer can give an agent. Each one maps to a model.
SKILLS: Dict[str, str] = {
    "planning": "breaking work into steps, strategy and outlines",
    "research": "facts, background knowledge and references",
    "coding": "writing, fixing or explaining code",
    "review": "checking work for errors, testing and critique",
    "analysis": "data, maths and quantitative reasoning",
    "writing": "prose, documentation, marketing copy and editing",
    GENERAL_SKILL: "anything else",
}

# Default model per role. All of these are on Ollama Cloud's Free plan as of
# 2026-10-13; other cloud models answer 402 Payment Required on that plan.
# Override any role with OLLAMA_MODEL_<ROLE>; roles not listed here, and any
# call whose model is refused, use OLLAMA_MODEL.
DEFAULT_ROLE_MODELS: Dict[str, str] = {
    # Runs before every step, so it needs fast, reliable tool calling.
    ROLE_SUPERVISOR: "gemma4:31b",
    # Proposed the most sensible teams when the free models were compared.
    ROLE_DESIGNER: "gpt-oss:120b",
    # Merges the team's work and keeps code and details intact.
    ROLE_FINALIZER: "gpt-oss:120b",
    "planning": "nemotron-3-super",
    # The largest free model, with the broadest general knowledge.
    "research": "nemotron-3-ultra",
    "coding": "gpt-oss:120b",
    # A different model family from the coder gives an independent check.
    "review": "nemotron-3-ultra",
    "analysis": "gpt-oss:120b",
    "writing": "gemma4:31b",
}

# Keyword rules used when the designer omits a skill or invents one. They
# are checked in order, so a "Code Reviewer" counts as a reviewer.
_SKILL_PATTERNS: Tuple[Tuple[str, str], ...] = (
    ("review", r"review|critic|\bqa\b|test|audit|verif|check|validat"),
    ("coding", r"\bcod|program|develop|engineer|implement|debug|script"),
    ("analysis", r"analy|data|statist|math|calcul|quant"),
    ("research", r"research|search|investigat|fact|scout|histor"),
    ("planning", r"plan|strateg|architect|outline|design|organi"),
    ("writing", r"writ|edit|author|copy|document|content|market"),
)

# Used only when the team designer cannot produce a usable team.
FALLBACK_AGENT_REGISTRY: Dict[str, str] = {
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

FINALIZER_PROMPT = (
    "You are the team lead. Your specialist agents have finished working on "
    "the user's task. Combine their contributions into one complete, "
    "well-structured final answer in Markdown. Prefer the reviewed version "
    "of any code, resolve disagreements, and do not mention the agents or "
    "the process.\n\nTask: {task}"
)


class WorkflowError(Exception):
    """A workflow failure whose message is safe to show to API clients."""

    def __init__(self, message: str, status_code: int = 500) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class ConfigurationError(WorkflowError):
    """Raised when required settings, such as the API key, are missing."""

    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=503)


def get_ollama_host() -> str:
    """Return the Ollama server URL, defaulting to Ollama Cloud."""
    return os.getenv("OLLAMA_HOST", "").strip() or DEFAULT_HOST


def get_model_name() -> str:
    """Return the default Ollama model name (OLLAMA_MODEL)."""
    return os.getenv("OLLAMA_MODEL", "").strip() or DEFAULT_MODEL


def get_role_model_name(role: str) -> str:
    """Return the model for a role or skill, honouring OLLAMA_MODEL_<ROLE>."""
    override = os.getenv(f"OLLAMA_MODEL_{role.upper()}", "").strip()
    return override or DEFAULT_ROLE_MODELS.get(role) or get_model_name()


def get_role_models() -> Dict[str, str]:
    """Return the configured model for every orchestration role and skill."""
    roles = [ROLE_SUPERVISOR, ROLE_DESIGNER, ROLE_FINALIZER, *SKILLS]
    return {role: get_role_model_name(role) for role in roles}


def orchestration_models() -> Dict[str, str]:
    """Return the models used by the supervisor, designer and finalizer."""
    return {
        role: get_role_model_name(role)
        for role in (ROLE_SUPERVISOR, ROLE_DESIGNER, ROLE_FINALIZER)
    }


# =====================================================================
# 1. State Definition
# =====================================================================
class DynamicAgentState(TypedDict):
    """Shared state passed between the supervisor and the agents."""

    messages: Annotated[Sequence[BaseMessage], add_messages]
    task_description: str
    team_members: List[str]
    next_agent: str  # Who speaks next, or FINISH when the work is done
    routing_reason: str  # The supervisor's explanation for that choice


@dataclass(frozen=True)
class Team:
    """The agents assembled for one task."""

    registry: Dict[str, str]  # Agent name -> role prompt
    skills: Dict[str, str]  # Agent name -> skill (a key of SKILLS)
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
    team: List[AgentProfile]
    team_generated: bool
    models: Dict[str, str]
    steps: List[StepRecord]
    final_response: str


WorkflowEvent = Dict[str, Any]
AgentNode = Callable[[DynamicAgentState], Dict[str, Any]]
# Returns the chat model for a role or skill name.
ChatModelFactory = Callable[[str], BaseChatModel]


# =====================================================================
# 2. Structured Output Schemas
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

    agents: List[AgentSpec] = Field(
        description=(
            "The specialist agents, in the order they would typically "
            "contribute."
        )
    )


# =====================================================================
# Helpers
# =====================================================================
def _escape_braces(text: str) -> str:
    """Escape braces so dynamic text is not parsed as template variables."""
    return text.replace("{", "{{").replace("}", "}}")


def _name_key(name: str) -> str:
    """Normalise a name for comparison, so 'Data analyst' == 'DataAnalyst'."""
    return re.sub(r"[\W_]", "", name.lower())


def message_text(message: BaseMessage) -> str:
    """Return a message's plain text, without any inline reasoning block."""
    content = message.content
    if isinstance(content, str):
        text = content
    else:
        text = "".join(
            part if isinstance(part, str) else str(part.get("text", ""))
            for part in content
        )
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def response_model(message: BaseMessage) -> str:
    """Return the model that produced a reply, when the provider reports it.

    This reflects any fallback, unlike the configured model for the role.
    """
    metadata = getattr(message, "response_metadata", None) or {}
    return str(metadata.get("model_name") or metadata.get("model") or "")


def _as_transcript(messages: Sequence[BaseMessage]) -> List[BaseMessage]:
    """Rewrite agent replies as attributed user turns for the model.

    Ollama's chat API drops the per-message ``name`` field, so without this
    the model could not tell which agent wrote which reply. Presenting the
    replies as user turns also keeps the conversation ending on a user
    message, which Ollama would otherwise treat as a reply to continue.
    """
    transcript: List[BaseMessage] = []
    for message in messages:
        if isinstance(message, AIMessage):
            speaker = message.name or "Agent"
            transcript.append(
                HumanMessage(content=f"[{speaker}]\n{message_text(message)}")
            )
        else:
            transcript.append(message)
    return transcript


# =====================================================================
# Skills and per-role models
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
    agent_skills: Optional[Mapping[str, str]] = None,
) -> Dict[str, str]:
    """Return a valid skill for every agent in a registry."""
    given = agent_skills or {}
    return {
        name: resolve_skill(given.get(name, ""), name, role_prompt)
        for name, role_prompt in agent_registry.items()
    }


def team_profiles(team: Team) -> List[AgentProfile]:
    """Describe a team for API clients, including each agent's model."""
    profiles: List[AgentProfile] = []
    for name, role in team.registry.items():
        skill = team.skills.get(name) or infer_skill(name, role)
        profiles.append(
            AgentProfile(
                name=name,
                role=role,
                skill=skill,
                model=get_role_model_name(skill),
            )
        )
    return profiles


def create_llm(model_name: Optional[str] = None) -> ChatOllama:
    """Create an Ollama chat model client."""
    api_key = os.getenv("OLLAMA_API_KEY", "").strip()
    if not api_key or api_key == PLACEHOLDER_API_KEY:
        raise ConfigurationError(
            "OLLAMA_API_KEY is not set. Add your Ollama Cloud API key to "
            ".env and restart the server."
        )
    return ChatOllama(
        model=model_name or get_model_name(),
        base_url=get_ollama_host(),
        temperature=0,
        client_kwargs={
            "headers": {"Authorization": f"Bearer {api_key}"},
            "timeout": REQUEST_TIMEOUT_SECONDS,
        },
    )


@lru_cache(maxsize=None)
def get_llm(model_name: str) -> ChatOllama:
    """Return a shared client per model so HTTP connections are reused."""
    logger.info(
        "Creating Ollama client for %s at %s", model_name, get_ollama_host()
    )
    return create_llm(model_name)


def get_role_llm(role: str) -> ChatOllama:
    """Return the chat model configured for a role or skill."""
    return get_llm(get_role_model_name(role))


def _single_model(llm: BaseChatModel) -> ChatModelFactory:
    """Return a model factory that uses one chat model for every role."""
    def factory(_role: str) -> BaseChatModel:
        return llm

    return factory


def _model_label(llm: BaseChatModel) -> str:
    return str(getattr(llm, "model", "") or type(llm).__name__)


def _with_fallback(
    models: ChatModelFactory,
    role: str,
    build: Optional[Callable[[BaseChatModel], Runnable]] = None,
) -> Runnable:
    """Build a runnable on the role's model, retrying on the default model.

    Free-plan access to individual models changes over time. When the
    role's model is refused (for example 402 Payment Required) or errors,
    the same call is retried on OLLAMA_MODEL instead of failing the run.
    """
    def identity(model: BaseChatModel) -> Runnable:
        return model

    build = build or identity
    primary = models(role)
    fallback = models(GENERAL_SKILL)
    runnable = build(primary)
    if primary is fallback:
        return runnable

    def announce(value: Any) -> Any:
        logger.warning(
            "Model %s failed for %s; retrying on %s",
            _model_label(primary),
            role,
            _model_label(fallback),
        )
        return value

    return runnable.with_fallbacks(
        [RunnableLambda(announce) | build(fallback)],
        exceptions_to_handle=(ResponseError,),
    )


# =====================================================================
# 3. Dynamic Agent Registry Generation
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
) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Build a registry and skill map from proposed agents.

    Skips agents with empty names or prompts, duplicate names and names that
    clash with the supervisor, finalizer or FINISH, and caps the team size.
    """
    reserved = {_name_key(name) for name in RESERVED_NAMES}
    registry: Dict[str, str] = {}
    skills: Dict[str, str] = {}
    seen: set = set()
    for spec in specs:
        name = _clean_agent_name(spec.name)
        role = " ".join(spec.role_prompt.split())[:MAX_ROLE_PROMPT_LENGTH]
        key = _name_key(name)
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


def generate_agent_registry(task: str, models: ChatModelFactory) -> Team:
    """Generate the agent registry, with a skill per agent, for a task.

    If the model's proposal cannot be parsed or contains no usable agents,
    the team built from ``FALLBACK_AGENT_REGISTRY`` is returned instead.
    Connection and authentication errors are not caught.
    """
    designer = _with_fallback(models, ROLE_DESIGNER, create_team_designer)
    try:
        proposal = designer.invoke({"messages": [HumanMessage(content=task)]})
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


# =====================================================================
# 4. Dynamic Router / Supervisor Definition
# =====================================================================
def create_supervisor(
    llm: BaseChatModel,
    agents: List[str],
    roles: Optional[Mapping[str, str]] = None,
) -> Runnable:
    """Create the supervisor runnable that picks the next agent or FINISH.

    Args:
        llm: Chat model used for routing.
        agents: Names of the agents the supervisor may choose from.
        roles: Optional agent name -> role prompt, so the supervisor knows
            what each generated agent is responsible for.
    """
    lines = [
        "You are the team supervisor managing a dynamic workflow.",
        f"Your active team members are: {agents}.",
    ]
    if roles:
        lines.append("Their responsibilities:")
        lines.extend(
            f"- {name}: {roles[name]}" for name in agents if name in roles
        )
    lines.extend([
        "",
        "Analyze the conversation history and the core task. Determine "
        "which specialist agent should act next to progress the work. If "
        "the task has been fully resolved, verified, and finalized, select "
        f"'{FINISH}'.",
        "Strictly adhere to selecting an agent from the provided list or "
        f"'{FINISH}'.",
    ])
    prompt = ChatPromptTemplate.from_messages([
        ("system", _escape_braces("\n".join(lines))),
        MessagesPlaceholder(variable_name="messages"),
    ])
    # Bind the structured output schema to guarantee clean routing tags.
    # include_raw keeps the reply available when the model skips the tool.
    return prompt | llm.with_structured_output(
        RouterSchema, method=STRUCTURED_OUTPUT_METHOD, include_raw=True
    )


def _resolve_next_agent(choice: str, agent_names: Sequence[str]) -> str:
    """Map the supervisor's choice onto a registered agent name or FINISH.

    Models sometimes vary casing, spacing or punctuation, and an unknown
    node name would crash the graph, so unrecognised choices end the run
    instead.
    """
    key = _name_key(choice)
    if key == _name_key(FINISH):
        return FINISH
    match = {_name_key(name): name for name in agent_names}.get(key)
    if match is None:
        logger.warning("Supervisor chose unknown agent %r; finishing", choice)
        return FINISH
    return match


def _find_agent_in_text(
    text: str, agent_names: Sequence[str]
) -> Optional[str]:
    """Return the agent name (or FINISH) mentioned first in free text."""
    best: Optional[Tuple[int, str]] = None
    for name in [*agent_names, FINISH]:
        pattern = r"\s*".join(re.escape(word) for word in name.split())
        match = re.search(rf"\b{pattern}\b", text, flags=re.IGNORECASE)
        if match and (best is None or match.start() < best[0]):
            best = (match.start(), name)
    return best[1] if best else None


def _parse_routing(
    output: Mapping[str, Any], agent_names: Sequence[str]
) -> Tuple[str, str]:
    """Extract (next agent, reasoning) from the supervisor's raw output.

    Falls back to scanning the reply for an agent name when the model
    answers in prose instead of calling the routing tool.
    """
    parsed = output.get("parsed")
    if isinstance(parsed, RouterSchema):
        next_agent = _resolve_next_agent(parsed.next_agent, agent_names)
        return next_agent, parsed.reasoning

    raw = output.get("raw")
    text = message_text(raw) if isinstance(raw, BaseMessage) else ""
    choice = _find_agent_in_text(text, agent_names)
    if choice is None:
        raise WorkflowError(
            "The supervisor returned an invalid routing decision. Try again "
            "or choose a different OLLAMA_MODEL_SUPERVISOR.",
            502,
        )
    logger.warning("Supervisor replied in prose; routing to %s", choice)
    return choice, text[:MAX_ROLE_PROMPT_LENGTH]


# =====================================================================
# 5. Dynamic Agent Node Factory
# =====================================================================
def create_agent_node(
    llm: Runnable, name: str, system_prompt: str
) -> AgentNode:
    """Factory to generate specialized agent nodes on-the-fly.

    ``llm`` is the chat model for the agent's skill, optionally wrapped with
    a fallback model.
    """
    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            _escape_braces(
                f"You are a specialized agent named {name}.\n"
                f"Role Prompt: {system_prompt}\n"
                "Keep your answer concise and focused."
            ),
        ),
        MessagesPlaceholder(variable_name="messages"),
    ])
    agent_runnable = prompt | llm

    def node(state: DynamicAgentState) -> Dict[str, Any]:
        logger.info("Agent %s is working", name)
        response = agent_runnable.invoke(
            {"messages": _as_transcript(state["messages"])}
        )
        # Tag the reply so the supervisor and the UI know who produced it.
        response.name = name
        return {"messages": [response]}

    return node


def create_finalizer_node(llm: Runnable) -> AgentNode:
    """Create the node that consolidates the team's work into one answer."""
    prompt = ChatPromptTemplate.from_messages([
        ("system", FINALIZER_PROMPT),
        MessagesPlaceholder(variable_name="messages"),
    ])
    finalizer_runnable = prompt | llm

    def node(state: DynamicAgentState) -> Dict[str, Any]:
        logger.info("Finalizer is consolidating the team's work")
        response = finalizer_runnable.invoke({
            "task": state["task_description"],
            "messages": _as_transcript(state["messages"]),
        })
        response.name = FINALIZER
        return {"messages": [response]}

    return node


# =====================================================================
# 6. Orchestrating the Dynamic Graph Builder
# =====================================================================
def _validate_registry(agent_registry: Mapping[str, str]) -> None:
    if not agent_registry:
        raise ValueError("The agent registry must contain at least one agent.")
    keys = [_name_key(name) for name in agent_registry]
    if not all(keys):
        raise ValueError("Agent names must contain letters or digits.")
    if len(set(keys)) != len(keys):
        raise ValueError("Agent names must be unique.")
    reserved = {_name_key(name) for name in RESERVED_NAMES}
    clashes = sorted(n for n in agent_registry if _name_key(n) in reserved)
    if clashes:
        raise ValueError(f"Reserved agent names cannot be used: {clashes}")


def build_dynamic_agent_graph(
    agent_registry: Mapping[str, str],
    model_name: Optional[str] = None,
    llm: Optional[BaseChatModel] = None,
    agent_skills: Optional[Mapping[str, str]] = None,
    models: Optional[ChatModelFactory] = None,
) -> CompiledStateGraph:
    """Compile a supervisor-routed graph with one node per registry agent.

    Args:
        agent_registry: Agent name -> role prompt, typically produced by
            ``generate_agent_registry``.
        model_name: Use this one Ollama model for every role.
        llm: Use this one pre-built chat model for every role.
        agent_skills: Agent name -> skill. Missing skills are inferred
            from the agent's name and role prompt.
        models: Role or skill -> chat model. Defaults to each role's
            configured Ollama model (see ``DEFAULT_ROLE_MODELS``).
    """
    _validate_registry(agent_registry)
    if llm is not None:
        models = _single_model(llm)
    elif model_name is not None:
        models = _single_model(create_llm(model_name))
    elif models is None:
        models = get_role_llm
    skills = resolve_agent_skills(agent_registry, agent_skills)

    # 1. Initialize State Graph
    workflow = StateGraph(DynamicAgentState)
    agent_names = list(agent_registry)

    # 2. Dynamic Supervisor Node Setup
    supervisor_runnable = _with_fallback(
        models,
        ROLE_SUPERVISOR,
        lambda model: create_supervisor(model, agent_names, agent_registry),
    )

    def supervisor_node(state: DynamicAgentState) -> Dict[str, Any]:
        output = supervisor_runnable.invoke(
            {"messages": _as_transcript(state["messages"])}
        )
        next_agent, reasoning = _parse_routing(output, agent_names)
        logger.info("Supervisor routed to %s: %s", next_agent, reasoning)
        return {"next_agent": next_agent, "routing_reason": reasoning}

    workflow.add_node(SUPERVISOR, supervisor_node)

    # 3. Dynamically loop through the registry to add agent nodes, each on
    # the model for its skill. Every agent returns to the supervisor, which
    # decides the next step.
    for name, system_prompt in agent_registry.items():
        agent_llm = _with_fallback(models, skills[name])
        workflow.add_node(
            name, create_agent_node(agent_llm, name, system_prompt)
        )
        workflow.add_edge(name, SUPERVISOR)

    finalizer_llm = _with_fallback(models, ROLE_FINALIZER)
    workflow.add_node(FINALIZER, create_finalizer_node(finalizer_llm))
    workflow.add_edge(FINALIZER, END)

    # 4. Routing logic based on the supervisor's next_agent decision
    def router_conditional_edge(state: DynamicAgentState) -> str:
        next_step = state["next_agent"]
        return FINALIZER if next_step == FINISH else next_step

    conditional_mapping = {name: name for name in agent_names}
    conditional_mapping[FINALIZER] = FINALIZER

    # 5. Connect Entry and Router Edge
    workflow.add_edge(START, SUPERVISOR)
    workflow.add_conditional_edges(
        SUPERVISOR, router_conditional_edge, conditional_mapping
    )

    return workflow.compile()


# =====================================================================
# 7. Running the Workflow
# =====================================================================
def _to_workflow_error(exc: Exception) -> WorkflowError:
    """Translate a low-level failure into a client-safe WorkflowError."""
    if isinstance(exc, GraphRecursionError):
        return WorkflowError(
            "The agents did not reach a conclusion within the step limit. "
            "Try a more specific task.",
            422,
        )
    if isinstance(exc, ResponseError):
        if exc.status_code == 401:
            return WorkflowError(
                "Ollama rejected the API key. Check OLLAMA_API_KEY in .env.",
                502,
            )
        if exc.status_code in (402, 403):
            return WorkflowError(
                f"A configured model is not available on your Ollama plan "
                f"({exc.error}). Choose other models in .env.",
                502,
            )
        if exc.status_code == 404:
            return WorkflowError(
                f"A configured model was not found on {get_ollama_host()}. "
                "Check the OLLAMA_MODEL settings in .env.",
                502,
            )
        return WorkflowError(
            f"Ollama returned an error ({exc.status_code}): {exc.error}", 502
        )
    if isinstance(exc, httpx.TimeoutException):
        return WorkflowError(
            "The model took too long to respond. Please try again.", 504
        )
    if isinstance(exc, (ConnectionError, httpx.HTTPError)):
        return WorkflowError(
            f"Could not connect to Ollama at {get_ollama_host()}.", 502
        )
    if isinstance(exc, OutputParserException):
        return WorkflowError(
            "The model returned a malformed routing decision. Try again or "
            "choose a different OLLAMA_MODEL_SUPERVISOR.",
            502,
        )
    return WorkflowError(
        "The workflow failed unexpectedly. Check the server logs.", 500
    )


def stream_workflow(
    task: str,
    agent_registry: Optional[Mapping[str, str]] = None,
    llm: Optional[BaseChatModel] = None,
) -> Iterator[WorkflowEvent]:
    """Run the workflow, yielding an event as each stage completes.

    Args:
        task: The user's request.
        agent_registry: A fixed team to use. When omitted, a team is
            generated from the task.
        llm: Use this one chat model for every role instead of the
            configured per-role Ollama models.

    Event shapes:
        {"type": "team", "agents": [{"name", "role", "skill", "model"}],
         "generated": bool, "models": {role: model}}
        {"type": "routing", "next_agent": str, "reason": str}
        {"type": "step", "step": int, "agent": str, "message": str,
         "reason": str, "model": str}
        {"type": "final", "message": str, "model": str}

    Raises:
        WorkflowError: on any failure, with a client-safe message.
    """
    started = time.perf_counter()
    step = 0
    reason = ""
    try:
        models = _single_model(llm) if llm is not None else get_role_llm
        if agent_registry is None:
            team = generate_agent_registry(task, models)
        else:
            registry = dict(agent_registry)
            team = Team(registry, resolve_agent_skills(registry), False)
        yield {
            "type": "team",
            "agents": team_profiles(team),
            "generated": team.generated,
            "models": orchestration_models(),
        }

        graph = build_dynamic_agent_graph(
            team.registry, agent_skills=team.skills, models=models
        )
        initial_state: DynamicAgentState = {
            "messages": [HumanMessage(content=task)],
            "task_description": task,
            "team_members": list(team.registry),
            "next_agent": "",
            "routing_reason": "",
        }
        logger.info("Workflow started (%d-character task)", len(task))

        for event in graph.stream(
            initial_state,
            {"recursion_limit": RECURSION_LIMIT},
            stream_mode="updates",
        ):
            for node, update in event.items():
                if not update:
                    continue
                if node == SUPERVISOR:
                    reason = update.get("routing_reason", "")
                    yield {
                        "type": "routing",
                        "next_agent": update["next_agent"],
                        "reason": reason,
                    }
                    continue
                reply = update["messages"][-1]
                if node == FINALIZER:
                    yield {
                        "type": "final",
                        "message": message_text(reply),
                        "model": response_model(reply),
                    }
                else:
                    step += 1
                    yield {
                        "type": "step",
                        "step": step,
                        "agent": node,
                        "message": message_text(reply),
                        "reason": reason,
                        "model": response_model(reply),
                    }
    except WorkflowError:
        raise
    except Exception as exc:
        error = _to_workflow_error(exc)
        # Only unexpected failures need a stack trace in the logs.
        logger.error(
            "Workflow failed: %s (%s)",
            error.message,
            type(exc).__name__,
            exc_info=error.status_code == 500,
        )
        raise error from exc

    logger.info(
        "Workflow finished in %.1fs with %d agent steps",
        time.perf_counter() - started,
        step,
    )


def run_workflow(task: str) -> WorkflowResult:
    """Run the workflow to completion and collect every agent step."""
    result = WorkflowResult(
        task=task,
        team=[],
        team_generated=False,
        models={},
        steps=[],
        final_response="",
    )
    for event in stream_workflow(task):
        if event["type"] == "team":
            result["team"] = event["agents"]
            result["team_generated"] = event["generated"]
            result["models"] = event["models"]
        elif event["type"] == "step":
            result["steps"].append(
                StepRecord(
                    step=event["step"],
                    agent=event["agent"],
                    message=event["message"],
                    reason=event["reason"],
                    model=event["model"],
                )
            )
        elif event["type"] == "final":
            result["final_response"] = event["message"]
    return result
