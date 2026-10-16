"""Agent and finalizer nodes, and the graph that connects them."""

import logging
from collections.abc import Hashable, Mapping
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import Runnable
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from .config import (
    FINALIZER,
    FINISH,
    RESERVED_NAME_CHARACTERS,
    RESERVED_NAMES,
    ROLE_FINALIZER,
    SUPERVISOR,
)
from .errors import InvalidTeamError
from .messages import as_transcript, escape_braces, name_key
from .models import create_llm, get_role_llm, single_model, with_fallback
from .routing import create_supervisor_node
from .schemas import AgentNode, ChatModelFactory, DynamicAgentState
from .team import resolve_agent_skills

logger = logging.getLogger(__name__)

FINALIZER_PROMPT = (
    "You are the team lead. Your specialist agents have finished working on "
    "the user's task. Combine their contributions into one complete, "
    "well-structured final answer in Markdown. Prefer the reviewed version "
    "of any code, resolve disagreements, and do not mention the agents or "
    "the process.\n\nTask: {task}"
)


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
            escape_braces(
                f"You are a specialized agent named {name}.\n"
                f"Role Prompt: {system_prompt}\n"
                "Keep your answer concise and focused."
            ),
        ),
        MessagesPlaceholder(variable_name="messages"),
    ])
    agent_runnable = prompt | llm

    def node(state: DynamicAgentState) -> dict[str, Any]:
        logger.info("Agent %s is working", name)
        response = agent_runnable.invoke(
            {"messages": as_transcript(state["messages"])}
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

    def node(state: DynamicAgentState) -> dict[str, Any]:
        logger.info("Finalizer is consolidating the team's work")
        response = finalizer_runnable.invoke({
            "task": state["task_description"],
            "messages": as_transcript(state["messages"]),
        })
        response.name = FINALIZER
        return {"messages": [response]}

    return node


def validate_registry(agent_registry: Mapping[str, str]) -> None:
    """Raise InvalidTeamError unless every agent name can be a graph node."""
    if not agent_registry:
        raise InvalidTeamError(
            "The agent registry must contain at least one agent."
        )
    keys = [name_key(name) for name in agent_registry]
    if not all(keys):
        raise InvalidTeamError("Agent names must contain letters or digits.")
    if len(set(keys)) != len(keys):
        raise InvalidTeamError("Agent names must be unique.")
    reserved = {name_key(name) for name in RESERVED_NAMES}
    clashes = sorted(n for n in agent_registry if name_key(n) in reserved)
    if clashes:
        raise InvalidTeamError(
            f"Reserved agent names cannot be used: {clashes}"
        )
    unusable = sorted(
        name
        for name in agent_registry
        if any(char in name for char in RESERVED_NAME_CHARACTERS)
    )
    if unusable:
        raise InvalidTeamError(
            f"Agent names cannot contain '|' or ':': {unusable}"
        )


def build_dynamic_agent_graph(
    agent_registry: Mapping[str, str],
    model_name: str | None = None,
    llm: BaseChatModel | None = None,
    agent_skills: Mapping[str, str] | None = None,
    models: ChatModelFactory | None = None,
    deadline: float | None = None,
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
        deadline: A ``time.monotonic()`` value. Once it has passed, the
            supervisor stops routing and the finalizer runs.
    """
    validate_registry(agent_registry)
    if llm is not None:
        models = single_model(llm)
    elif model_name is not None:
        models = single_model(create_llm(model_name))
    elif models is None:
        models = get_role_llm
    skills = resolve_agent_skills(agent_registry, agent_skills)

    # 1. Initialize State Graph
    workflow: StateGraph[DynamicAgentState] = StateGraph(DynamicAgentState)
    agent_names = list(agent_registry)

    # 2. Supervisor node, which also enforces the step and time budgets
    workflow.add_node(
        SUPERVISOR, create_supervisor_node(models, agent_registry, deadline)
    )

    # 3. Dynamically loop through the registry to add agent nodes, each on
    # the model for its skill. Every agent returns to the supervisor, which
    # decides the next step.
    for name, system_prompt in agent_registry.items():
        agent_llm = with_fallback(models, skills[name])
        workflow.add_node(
            name, create_agent_node(agent_llm, name, system_prompt)
        )
        workflow.add_edge(name, SUPERVISOR)

    finalizer_llm = with_fallback(models, ROLE_FINALIZER)
    workflow.add_node(FINALIZER, create_finalizer_node(finalizer_llm))
    workflow.add_edge(FINALIZER, END)

    # 4. Routing logic based on the supervisor's next_agent decision
    def router_conditional_edge(state: DynamicAgentState) -> str:
        next_step = state["next_agent"]
        return FINALIZER if next_step == FINISH else next_step

    conditional_mapping: dict[Hashable, str] = {
        name: name for name in agent_names
    }
    conditional_mapping[FINALIZER] = FINALIZER

    # 5. Connect Entry and Router Edge
    workflow.add_edge(START, SUPERVISOR)
    workflow.add_conditional_edges(
        SUPERVISOR, router_conditional_edge, conditional_mapping
    )

    return workflow.compile()
