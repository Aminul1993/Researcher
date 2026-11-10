"""Settings, limits, roles and skills for the workflow.

Settings come from these environment variables:
    GROQ_API_KEY         Groq API key (required).
    GROQ_BASE_URL        API URL, default https://api.groq.com.
    GROQ_MODEL           Default model, and the fallback for every role.
    GROQ_MODEL_<ROLE>    Per-role override such as GROQ_MODEL_CODING.
                         Roles are the keys of DEFAULT_ROLE_MODELS.
    RUN_TIME_BUDGET_SECONDS
                         Wall-clock budget per run, default 600.

They are read once, on first use, into a frozen ``Settings`` object, so a
run never sees a half-changed configuration. Call ``reload_settings()``
after changing the environment, for example after loading a .env file.
"""

import math
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from types import MappingProxyType

from .errors import ConfigurationError

DEFAULT_BASE_URL = "https://api.groq.com"
DEFAULT_MODEL = "openai/gpt-oss-120b"
PLACEHOLDER_API_KEY = "your-groq-api-key"
REQUEST_TIMEOUT_SECONDS = 300.0
# Agent replies allowed per run. Once they are used up the supervisor stops
# routing and the finalizer answers with the work done so far.
MAX_AGENT_STEPS = 10
# Each agent step costs two graph steps (supervisor + agent); the rest
# covers the last routing decision, the finalizer and some headroom.
RECURSION_LIMIT = 2 * MAX_AGENT_STEPS + 5
# Wall-clock budget per run, checked before each routing decision. The
# agent call in progress and the finalizer still run once it has passed.
RUN_TIME_BUDGET_SECONDS = 600.0
# The supervisor only routes, so it sees the start and end of each reply
# rather than the whole text. Agents and the finalizer see full replies.
SUPERVISOR_EXCERPT_CHARS = 1200

SUPERVISOR = "Supervisor"
FINALIZER = "Finalizer"
FINISH = "FINISH"
RESERVED_NAMES = frozenset({SUPERVISOR, FINALIZER, FINISH})
# LangGraph uses these characters to namespace nodes, so names can't.
RESERVED_NAME_CHARACTERS = ("|", ":")

MAX_AGENTS = 5
MAX_AGENT_NAME_LENGTH = 40
MAX_ROLE_PROMPT_LENGTH = 400

# Every Groq model supports tool calling, while JSON-schema output works
# on only some of them and can't be combined with tools.
STRUCTURED_OUTPUT_METHOD = "function_calling"

# Orchestration roles. Agents are assigned one of the SKILLS below instead.
ROLE_SUPERVISOR = "supervisor"
ROLE_DESIGNER = "designer"
ROLE_FINALIZER = "finalizer"
GENERAL_SKILL = "general"

# Skills the team designer can give an agent. Each one maps to a model.
SKILLS: dict[str, str] = {
    "planning": "breaking work into steps, strategy and outlines",
    "research": "facts, background knowledge and references",
    "coding": "writing, fixing or explaining code",
    "review": "checking work for errors, testing and critique",
    "analysis": "data, maths and quantitative reasoning",
    "writing": "prose, documentation, marketing copy and editing",
    GENERAL_SKILL: "anything else",
}

# Default model per role. All of these are Groq production models as of
# 2026-11-10; preview models can be withdrawn at short notice. Groq's rate
# limits apply per model, so spreading the roles over several models lets a
# run go further before it hits them.
# Override any role with GROQ_MODEL_<ROLE>; roles not listed here, and any
# call whose model is refused or rate-limited, use GROQ_MODEL.
DEFAULT_ROLE_MODELS: dict[str, str] = {
    # Runs before every step, so it needs fast, reliable tool calling.
    ROLE_SUPERVISOR: "openai/gpt-oss-20b",
    # Designing a sensible team needs the strongest reasoning.
    ROLE_DESIGNER: "openai/gpt-oss-120b",
    # Merges the team's work and keeps code and details intact.
    ROLE_FINALIZER: "openai/gpt-oss-120b",
    "planning": "llama-3.3-70b-versatile",
    "research": "llama-3.3-70b-versatile",
    "coding": "openai/gpt-oss-120b",
    # A different model family from the coder gives an independent check.
    "review": "llama-3.3-70b-versatile",
    "analysis": "openai/gpt-oss-120b",
    "writing": "llama-3.3-70b-versatile",
}

_ROLE_MODEL_PREFIX = "GROQ_MODEL_"


def _parse_time_budget(raw: str) -> float:
    if not raw:
        return RUN_TIME_BUDGET_SECONDS
    try:
        budget = float(raw)
    except ValueError:
        budget = math.nan
    if not (budget > 0 and math.isfinite(budget)):
        raise ConfigurationError(
            "RUN_TIME_BUDGET_SECONDS must be a positive number of seconds."
        )
    return budget


@dataclass(frozen=True)
class Settings:
    """The workflow's configuration, read from the environment."""

    api_key: str = field(default="", repr=False)
    base_url: str = DEFAULT_BASE_URL
    default_model: str = DEFAULT_MODEL
    # Role or skill -> model, with GROQ_MODEL_<ROLE> overrides applied.
    role_models: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType(dict(DEFAULT_ROLE_MODELS))
    )
    run_time_budget: float = RUN_TIME_BUDGET_SECONDS

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "Settings":
        """Read settings from ``environ``, defaulting to ``os.environ``.

        Raises:
            ConfigurationError: when RUN_TIME_BUDGET_SECONDS is invalid.
        """
        env = os.environ if environ is None else environ

        def text(name: str) -> str:
            return env.get(name, "").strip()

        overrides = {
            name.removeprefix(_ROLE_MODEL_PREFIX).lower(): value.strip()
            for name, value in env.items()
            if name.startswith(_ROLE_MODEL_PREFIX) and value.strip()
        }
        return cls(
            api_key=text("GROQ_API_KEY"),
            base_url=text("GROQ_BASE_URL") or DEFAULT_BASE_URL,
            default_model=text("GROQ_MODEL") or DEFAULT_MODEL,
            role_models=MappingProxyType(
                {**DEFAULT_ROLE_MODELS, **overrides}
            ),
            run_time_budget=_parse_time_budget(
                text("RUN_TIME_BUDGET_SECONDS")
            ),
        )

    def model_for(self, role: str) -> str:
        """Return the model for a role or skill, or the default model."""
        return self.role_models.get(role) or self.default_model


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the settings, reading the environment on first use."""
    return Settings.from_env()


def reload_settings() -> Settings:
    """Read the environment again and return the new settings."""
    get_settings.cache_clear()
    return get_settings()


def get_groq_base_url() -> str:
    """Return the Groq API URL (GROQ_BASE_URL)."""
    return get_settings().base_url


def get_model_name() -> str:
    """Return the default Groq model name (GROQ_MODEL)."""
    return get_settings().default_model


def get_role_model_name(role: str) -> str:
    """Return the model for a role or skill, honouring GROQ_MODEL_<ROLE>."""
    return get_settings().model_for(role)


def get_run_time_budget() -> float:
    """Return the wall-clock budget per run (RUN_TIME_BUDGET_SECONDS)."""
    return get_settings().run_time_budget


def get_role_models() -> dict[str, str]:
    """Return the configured model for every orchestration role and skill."""
    roles = [ROLE_SUPERVISOR, ROLE_DESIGNER, ROLE_FINALIZER, *SKILLS]
    return {role: get_role_model_name(role) for role in roles}


def orchestration_models(
    model_label: Callable[[str], str] | None = None,
) -> dict[str, str]:
    """Return the models used by the supervisor, designer and finalizer.

    ``model_label`` maps a role to the model name to report. It defaults to
    each role's configured Groq model.
    """
    label = model_label or get_role_model_name
    return {
        role: label(role)
        for role in (ROLE_SUPERVISOR, ROLE_DESIGNER, ROLE_FINALIZER)
    }
