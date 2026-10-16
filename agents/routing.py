"""The supervisor, which routes work between agents within run budgets."""

import logging
import re
import time
from collections.abc import Mapping, Sequence
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import Runnable

from .config import (
    FINISH,
    MAX_AGENT_STEPS,
    MAX_ROLE_PROMPT_LENGTH,
    ROLE_SUPERVISOR,
    STRUCTURED_OUTPUT_METHOD,
    SUPERVISOR_EXCERPT_CHARS,
)
from .errors import WorkflowError
from .messages import as_transcript, escape_braces, message_text, name_key
from .models import with_fallback
from .schemas import (
    AgentNode,
    ChatModelFactory,
    DynamicAgentState,
    RouterSchema,
)

logger = logging.getLogger(__name__)


def create_supervisor(
    llm: BaseChatModel,
    agents: list[str],
    roles: Mapping[str, str] | None = None,
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
        ("system", escape_braces("\n".join(lines))),
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
    key = name_key(choice)
    if key == name_key(FINISH):
        return FINISH
    match = {name_key(name): name for name in agent_names}.get(key)
    if match is None:
        logger.warning("Supervisor chose unknown agent %r; finishing", choice)
        return FINISH
    return match


def _find_agent_in_text(
    text: str, agent_names: Sequence[str]
) -> str | None:
    """Return the agent name (or FINISH) mentioned first in free text."""
    best: tuple[int, str] | None = None
    for name in [*agent_names, FINISH]:
        pattern = r"\s*".join(re.escape(word) for word in name.split())
        match = re.search(rf"\b{pattern}\b", text, flags=re.IGNORECASE)
        if match and (best is None or match.start() < best[0]):
            best = (match.start(), name)
    return best[1] if best else None


def _parse_routing(
    output: Mapping[str, Any], agent_names: Sequence[str]
) -> tuple[str, str]:
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


def create_supervisor_node(
    models: ChatModelFactory,
    agent_registry: Mapping[str, str],
    deadline: float | None = None,
) -> AgentNode:
    """Create the graph node that picks the next agent or FINISH.

    The node chooses FINISH without asking the model once MAX_AGENT_STEPS
    agent replies exist or ``deadline`` (a ``time.monotonic()`` value) has
    passed, so the finalizer always gets to answer.
    """
    agent_names = list(agent_registry)
    supervisor_runnable = with_fallback(
        models,
        ROLE_SUPERVISOR,
        lambda model: create_supervisor(model, agent_names, agent_registry),
    )

    def supervisor_node(state: DynamicAgentState) -> dict[str, Any]:
        # Only agent replies are AI messages until the finalizer runs.
        replies = sum(isinstance(m, AIMessage) for m in state["messages"])
        budget_spent = ""
        if replies >= MAX_AGENT_STEPS:
            budget_spent = (
                f"Reached the limit of {MAX_AGENT_STEPS} agent steps"
            )
        elif deadline is not None and time.monotonic() >= deadline:
            budget_spent = "Ran out of time for this run"
        if budget_spent:
            reasoning = f"{budget_spent}; finalizing with the work so far."
            logger.warning(reasoning)
            return {"next_agent": FINISH, "routing_reason": reasoning}
        output = supervisor_runnable.invoke({
            "messages": as_transcript(
                state["messages"], SUPERVISOR_EXCERPT_CHARS
            )
        })
        next_agent, reasoning = _parse_routing(output, agent_names)
        logger.info("Supervisor routed to %s: %s", next_agent, reasoning)
        return {"next_agent": next_agent, "routing_reason": reasoning}

    return supervisor_node
