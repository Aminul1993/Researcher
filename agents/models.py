"""Groq chat model clients, and falling back to the default model."""

import logging
from collections.abc import Callable
from functools import cache
from typing import Any

from groq import APIStatusError
from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable, RunnableLambda
from langchain_groq import ChatGroq
from pydantic import SecretStr

from .config import (
    GENERAL_SKILL,
    PLACEHOLDER_API_KEY,
    REQUEST_TIMEOUT_SECONDS,
    get_role_model_name,
    get_settings,
)
from .errors import ConfigurationError
from .schemas import ChatModelFactory

logger = logging.getLogger(__name__)


def _require_api_key(api_key: str) -> None:
    if not api_key or api_key == PLACEHOLDER_API_KEY:
        raise ConfigurationError(
            "GROQ_API_KEY is not set. Add your Groq API key to .env and "
            "restart the server."
        )


def _new_client(model_name: str, base_url: str, api_key: str) -> ChatGroq:
    # The Groq client retries rate-limited (429) and failed calls twice,
    # waiting as long as Groq's Retry-After header asks, up to a minute.
    return ChatGroq(
        model=model_name,
        api_key=SecretStr(api_key),
        base_url=base_url,
        temperature=0,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )


@cache
def _shared_client(model_name: str, base_url: str, api_key: str) -> ChatGroq:
    logger.info("Creating Groq client for %s at %s", model_name, base_url)
    return _new_client(model_name, base_url, api_key)


def create_llm(model_name: str | None = None) -> ChatGroq:
    """Create a Groq chat model client."""
    settings = get_settings()
    _require_api_key(settings.api_key)
    return _new_client(
        model_name or settings.default_model,
        settings.base_url,
        settings.api_key,
    )


def get_llm(model_name: str) -> ChatGroq:
    """Return a shared client per model so HTTP connections are reused.

    Clients are shared per model, base URL and API key, so reloaded
    settings take effect for every role at once.
    """
    settings = get_settings()
    _require_api_key(settings.api_key)
    return _shared_client(model_name, settings.base_url, settings.api_key)


def get_role_llm(role: str) -> ChatGroq:
    """Return the chat model configured for a role or skill."""
    return get_llm(get_role_model_name(role))


def single_model(llm: BaseChatModel) -> ChatModelFactory:
    """Return a model factory that uses one chat model for every role."""
    def factory(_role: str) -> BaseChatModel:
        return llm

    return factory


def model_name_of(llm: BaseChatModel) -> str:
    """Return a chat model's model name, or its class name."""
    return str(getattr(llm, "model", "") or type(llm).__name__)


def fixed_model_label(label: str) -> Callable[[str], str]:
    """Return a role -> model name mapping that reports one model."""
    def model_label(_role: str) -> str:
        return label

    return model_label


def with_fallback(
    models: ChatModelFactory,
    role: str,
    build: Callable[[BaseChatModel], Runnable] | None = None,
) -> Runnable:
    """Build a runnable on the role's model, retrying on the default model.

    Groq's rate limits apply per model, and models are retired over time.
    When the role's model is rate-limited (429), withdrawn (404) or errors,
    the same call is retried on GROQ_MODEL instead of failing the run.
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
            model_name_of(primary),
            role,
            model_name_of(fallback),
        )
        return value

    return runnable.with_fallbacks(
        [RunnableLambda(announce) | build(fallback)],
        exceptions_to_handle=(APIStatusError,),
    )
