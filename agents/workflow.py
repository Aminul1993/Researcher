"""LangGraph multi-agent workflow driven by a dynamic supervisor.

For every task, a team designer LLM call first generates the agent registry:
a small set of specialist agents, each with a role prompt and a skill
tailored to the task. Every skill maps to the model best suited to it, so a
coder, a reviewer and a writer can each run on a different model. A
supervisor then routes work between the agents until it decides the task is
complete, and a finalizer node consolidates the team's contributions into a
single answer.

The implementation is split across the modules of the ``agents`` package:

    config     settings, limits, roles and skills (see it for the
               environment variables)
    errors     client-safe exceptions
    schemas    graph state, API records and structured-output schemas
    messages   reading model replies and presenting them to models
    models     Ollama clients and falling back to the default model
    team       designing the team and each agent's skill
    routing    the supervisor and its step and time budgets
    graph      agent and finalizer nodes, and the graph builder
    telemetry  run IDs and per-call latency and token logging
    runner     stream_workflow, run_workflow and error mapping

This module re-exports the public API, so ``from agents.workflow import
...`` keeps working.
"""

import logging

from .config import (
    DEFAULT_HOST,
    DEFAULT_MODEL,
    DEFAULT_ROLE_MODELS,
    FINALIZER,
    FINISH,
    GENERAL_SKILL,
    MAX_AGENT_NAME_LENGTH,
    MAX_AGENT_STEPS,
    MAX_AGENTS,
    MAX_ROLE_PROMPT_LENGTH,
    PLACEHOLDER_API_KEY,
    RECURSION_LIMIT,
    REQUEST_TIMEOUT_SECONDS,
    RESERVED_NAME_CHARACTERS,
    RESERVED_NAMES,
    ROLE_DESIGNER,
    ROLE_FINALIZER,
    ROLE_SUPERVISOR,
    RUN_TIME_BUDGET_SECONDS,
    SKILLS,
    STRUCTURED_OUTPUT_METHOD,
    SUPERVISOR,
    SUPERVISOR_EXCERPT_CHARS,
    Settings,
    get_model_name,
    get_ollama_host,
    get_role_model_name,
    get_role_models,
    get_run_time_budget,
    get_settings,
    orchestration_models,
    reload_settings,
)
from .errors import ConfigurationError, InvalidTeamError, WorkflowError
from .graph import (
    FINALIZER_PROMPT,
    build_dynamic_agent_graph,
    create_agent_node,
    create_finalizer_node,
)
from .messages import message_text, response_model
from .models import create_llm, get_llm, get_role_llm
from .routing import create_supervisor
from .runner import run_workflow, stream_workflow
from .schemas import (
    AgentNode,
    AgentProfile,
    AgentSpec,
    ChatModelFactory,
    DynamicAgentState,
    RouterSchema,
    StepRecord,
    Team,
    TeamSchema,
    WorkflowEvent,
    WorkflowResult,
)
from .team import (
    FALLBACK_AGENT_REGISTRY,
    TEAM_DESIGNER_PROMPT,
    create_team_designer,
    generate_agent_registry,
    infer_skill,
    resolve_agent_skills,
    resolve_skill,
    team_profiles,
)
from .telemetry import RunIdFilter, RunTelemetry, new_run_id

# The parent of every module's logger in the package.
logger = logging.getLogger("agents")

__all__ = [
    "DEFAULT_HOST",
    "DEFAULT_MODEL",
    "DEFAULT_ROLE_MODELS",
    "FALLBACK_AGENT_REGISTRY",
    "FINALIZER",
    "FINALIZER_PROMPT",
    "FINISH",
    "GENERAL_SKILL",
    "MAX_AGENTS",
    "MAX_AGENT_NAME_LENGTH",
    "MAX_AGENT_STEPS",
    "MAX_ROLE_PROMPT_LENGTH",
    "PLACEHOLDER_API_KEY",
    "RECURSION_LIMIT",
    "REQUEST_TIMEOUT_SECONDS",
    "RESERVED_NAMES",
    "RESERVED_NAME_CHARACTERS",
    "ROLE_DESIGNER",
    "ROLE_FINALIZER",
    "ROLE_SUPERVISOR",
    "RUN_TIME_BUDGET_SECONDS",
    "SKILLS",
    "STRUCTURED_OUTPUT_METHOD",
    "SUPERVISOR",
    "SUPERVISOR_EXCERPT_CHARS",
    "TEAM_DESIGNER_PROMPT",
    "AgentNode",
    "AgentProfile",
    "AgentSpec",
    "ChatModelFactory",
    "ConfigurationError",
    "DynamicAgentState",
    "InvalidTeamError",
    "RouterSchema",
    "RunIdFilter",
    "RunTelemetry",
    "Settings",
    "StepRecord",
    "Team",
    "TeamSchema",
    "WorkflowError",
    "WorkflowEvent",
    "WorkflowResult",
    "build_dynamic_agent_graph",
    "create_agent_node",
    "create_finalizer_node",
    "create_llm",
    "create_supervisor",
    "create_team_designer",
    "generate_agent_registry",
    "get_llm",
    "get_model_name",
    "get_ollama_host",
    "get_role_llm",
    "get_role_model_name",
    "get_role_models",
    "get_run_time_budget",
    "get_settings",
    "infer_skill",
    "logger",
    "message_text",
    "new_run_id",
    "orchestration_models",
    "reload_settings",
    "resolve_agent_skills",
    "resolve_skill",
    "response_model",
    "run_workflow",
    "stream_workflow",
    "team_profiles",
]
