"""Helpers for reading model replies and presenting them to models."""

import re
from collections.abc import Sequence

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage


def escape_braces(text: str) -> str:
    """Escape braces so dynamic text is not parsed as template variables."""
    return text.replace("{", "{{").replace("}", "}}")


def name_key(name: str) -> str:
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


def excerpt(text: str, limit: int) -> str:
    """Keep the start and end of long text, where plans and verdicts sit."""
    if len(text) <= limit:
        return text
    half = limit // 2
    omitted = len(text) - 2 * half
    return (
        f"{text[:half]}\n[... {omitted} characters omitted ...]\n"
        f"{text[-half:]}"
    )


def as_transcript(
    messages: Sequence[BaseMessage], excerpt_chars: int | None = None
) -> list[BaseMessage]:
    """Rewrite agent replies as attributed user turns for the model.

    Ollama's chat API drops the per-message ``name`` field, so without this
    the model could not tell which agent wrote which reply. Presenting the
    replies as user turns also keeps the conversation ending on a user
    message, which Ollama would otherwise treat as a reply to continue.

    With ``excerpt_chars``, each reply is shortened to that many characters
    from its start and end.
    """
    transcript: list[BaseMessage] = []
    for message in messages:
        if isinstance(message, AIMessage):
            speaker = message.name or "Agent"
            text = message_text(message)
            if excerpt_chars is not None:
                text = excerpt(text, excerpt_chars)
            transcript.append(HumanMessage(content=f"[{speaker}]\n{text}"))
        else:
            transcript.append(message)
    return transcript
