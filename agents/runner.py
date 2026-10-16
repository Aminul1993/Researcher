"""Running the workflow: events, results and client-safe errors."""

import logging
import time
from collections.abc import Callable, Generator, Mapping

import httpx
from langchain_core.exceptions import OutputParserException
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langgraph.errors import GraphRecursionError
from ollama import ResponseError

from .config import (
    FINALIZER,
    RECURSION_LIMIT,
    SUPERVISOR,
    get_ollama_host,
    get_role_model_name,
    get_run_time_budget,
    orchestration_models,
)
from .errors import WorkflowError
from .graph import build_dynamic_agent_graph, validate_registry
from .messages import message_text, response_model
from .models import (
    fixed_model_label,
    get_role_llm,
    model_name_of,
    single_model,
)
from .schemas import (
    ChatModelFactory,
    DynamicAgentState,
    StepRecord,
    Team,
    WorkflowEvent,
    WorkflowResult,
)
from .team import generate_agent_registry, resolve_agent_skills, team_profiles
from .telemetry import RunTelemetry, new_run_id, run_context

logger = logging.getLogger(__name__)


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
    agent_registry: Mapping[str, str] | None = None,
    llm: BaseChatModel | None = None,
    *,
    run_id: str | None = None,
    time_budget: float | None = None,
) -> Generator[WorkflowEvent, None, None]:
    """Run the workflow, yielding an event as each stage completes.

    The supervisor routes between agents until it chooses FINISH, until
    ``MAX_AGENT_STEPS`` agent replies have been produced, or until the time
    budget has passed; in every case the finalizer then writes the final
    answer.

    Args:
        task: The user's request.
        agent_registry: A fixed team to use. When omitted, a team is
            generated from the task.
        llm: Use this one chat model for every role instead of the
            configured per-role Ollama models.
        run_id: Tags this run's log records. A new ID is generated when
            omitted.
        time_budget: Seconds before the supervisor stops routing. Defaults
            to RUN_TIME_BUDGET_SECONDS.

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
    # Run in a context of its own, so every record logged during the run,
    # graph nodes included, carries the run ID.
    context = run_context(run_id or new_run_id())
    events = _run_events(task, agent_registry, llm, time_budget)
    try:
        while True:
            try:
                event = context.run(next, events)
            except StopIteration:
                return
            yield event
    finally:
        context.run(events.close)


def _run_events(
    task: str,
    agent_registry: Mapping[str, str] | None,
    llm: BaseChatModel | None,
    time_budget: float | None,
) -> Generator[WorkflowEvent, None, None]:
    """Yield the events of one run; see ``stream_workflow``."""
    started = time.perf_counter()
    telemetry = RunTelemetry()
    step = 0
    reason = ""
    try:
        budget = get_run_time_budget() if time_budget is None else time_budget
        deadline = time.monotonic() + budget
        logger.info(
            "Workflow started (%d-character task, %.0fs budget)",
            len(task),
            budget,
        )
        models: ChatModelFactory
        model_label: Callable[[str], str]
        if llm is not None:
            models = single_model(llm)
            model_label = fixed_model_label(model_name_of(llm))
        else:
            models = get_role_llm
            model_label = get_role_model_name
        if agent_registry is None:
            team = generate_agent_registry(
                task,
                models,
                {"callbacks": [telemetry], "metadata": {"stage": "Designer"}},
            )
        else:
            registry = dict(agent_registry)
            validate_registry(registry)
            team = Team(registry, resolve_agent_skills(registry), False)
        yield {
            "type": "team",
            "agents": team_profiles(team, model_label),
            "generated": team.generated,
            "models": orchestration_models(model_label),
        }

        graph = build_dynamic_agent_graph(
            team.registry,
            agent_skills=team.skills,
            models=models,
            deadline=deadline,
        )
        initial_state: DynamicAgentState = {
            "messages": [HumanMessage(content=task)],
            "task_description": task,
            "team_members": list(team.registry),
            "next_agent": "",
            "routing_reason": "",
        }

        for event in graph.stream(
            initial_state,
            {"recursion_limit": RECURSION_LIMIT, "callbacks": [telemetry]},
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
        "Workflow finished in %.1fs: %d agent steps, %d model calls, "
        "%d input / %d output tokens",
        time.perf_counter() - started,
        step,
        telemetry.model_calls,
        telemetry.input_tokens,
        telemetry.output_tokens,
    )


def run_workflow(
    task: str,
    agent_registry: Mapping[str, str] | None = None,
    llm: BaseChatModel | None = None,
    *,
    run_id: str | None = None,
    time_budget: float | None = None,
) -> WorkflowResult:
    """Run the workflow to completion and collect every agent step.

    Takes the same arguments as ``stream_workflow``.
    """
    run_id = run_id or new_run_id()
    result = WorkflowResult(
        task=task,
        run_id=run_id,
        team=[],
        team_generated=False,
        models={},
        steps=[],
        final_response="",
    )
    events = stream_workflow(
        task, agent_registry, llm, run_id=run_id, time_budget=time_budget
    )
    for event in events:
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
