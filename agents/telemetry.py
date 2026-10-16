"""Run IDs for log records, and per-call latency and token logging."""

import contextvars
import logging
import threading
import time
import uuid
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import BaseMessage
from langchain_core.outputs import LLMResult

logger = logging.getLogger(__name__)

_current_run_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "run_id", default="-"
)


def new_run_id() -> str:
    """Return a short random ID for one workflow run."""
    return uuid.uuid4().hex[:12]


def run_context(run_id: str) -> contextvars.Context:
    """Return a copy of the current context in which ``run_id`` is set.

    Code run inside it, including graph nodes that LangGraph runs in other
    threads, logs with that run ID, and the caller's context is untouched.
    """
    context = contextvars.copy_context()
    context.run(_current_run_id.set, run_id)
    return context


class RunIdFilter(logging.Filter):
    """Add the ID of the run in progress to log records as ``run_id``.

    Attach it to a handler and use ``%(run_id)s`` in the format. Records
    logged outside a run get ``-``.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = _current_run_id.get()
        return True


def _token_usage(response: LLMResult) -> tuple[int, int]:
    """Return (input, output) tokens reported for a model call."""
    for generations in response.generations:
        for generation in generations:
            message = getattr(generation, "message", None)
            usage = getattr(message, "usage_metadata", None)
            if usage:
                return (
                    int(usage.get("input_tokens") or 0),
                    int(usage.get("output_tokens") or 0),
                )
    return 0, 0


class RunTelemetry(BaseCallbackHandler):
    """Log each model call's latency and tokens, and total them per run."""

    def __init__(self) -> None:
        self.model_calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self._started: dict[uuid.UUID, tuple[float, str, str]] = {}
        self._lock = threading.Lock()

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        *,
        run_id: uuid.UUID,
        metadata: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        metadata = metadata or {}
        # LangGraph names the node making the call; other calls name a stage.
        stage = str(
            metadata.get("langgraph_node") or metadata.get("stage") or "Model"
        )
        model = str(metadata.get("ls_model_name") or "unknown model")
        with self._lock:
            self._started[run_id] = (time.perf_counter(), stage, model)

    def on_llm_end(
        self, response: LLMResult, *, run_id: uuid.UUID, **kwargs: Any
    ) -> None:
        with self._lock:
            started = self._started.pop(run_id, None)
            if started is None:
                return
            input_tokens, output_tokens = _token_usage(response)
            self.model_calls += 1
            self.input_tokens += input_tokens
            self.output_tokens += output_tokens
        began, stage, model = started
        logger.info(
            "%s call on %s took %.1fs (%d input / %d output tokens)",
            stage,
            model,
            time.perf_counter() - began,
            input_tokens,
            output_tokens,
        )

    def on_llm_error(
        self, error: BaseException, *, run_id: uuid.UUID, **kwargs: Any
    ) -> None:
        with self._lock:
            started = self._started.pop(run_id, None)
        if started is not None:
            began, stage, model = started
            logger.info(
                "%s call on %s failed after %.1fs (%s)",
                stage,
                model,
                time.perf_counter() - began,
                type(error).__name__,
            )
