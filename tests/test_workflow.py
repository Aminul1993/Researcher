import logging

import httpx
import pytest
from langchain_core.exceptions import OutputParserException
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.errors import GraphRecursionError
from ollama import ResponseError

from agents import workflow
from agents.messages import as_transcript, excerpt
from agents.routing import _find_agent_in_text
from agents.runner import _to_workflow_error
from agents.team import _sanitize_team
from agents.workflow import (
    FALLBACK_AGENT_REGISTRY,
    FINISH,
    MAX_AGENT_STEPS,
    MAX_AGENTS,
    AgentSpec,
    ConfigurationError,
    InvalidTeamError,
    WorkflowError,
    build_dynamic_agent_graph,
    generate_agent_registry,
    run_workflow,
    stream_workflow,
)
from tests.fakes import (
    CHAT_CALL,
    ROUTER_CALL,
    TEAM_CALL,
    ScriptedChatModel,
)

TASK = "Write a function that adds two numbers."


def events_of(model, task=TASK, **kwargs):
    return list(stream_workflow(task, llm=model, **kwargs))


def types_of(events):
    return [event["type"] for event in events]


# ---------------------------------------------------------------------------
# Running the workflow
# ---------------------------------------------------------------------------
def test_finish_decision_goes_straight_to_the_final_answer():
    model = ScriptedChatModel(routes=["FINISH"], reply="All done.")

    events = events_of(model)

    assert types_of(events) == ["team", "routing", "final"]
    assert events[1]["next_agent"] == FINISH
    assert events[2] == {
        "type": "final",
        "message": "All done.",
        "model": "scripted-model",
    }


def test_agents_run_in_the_order_the_supervisor_routes(fake):
    events = events_of(fake)

    assert types_of(events) == [
        "team", "routing", "step", "routing", "step", "routing", "final",
    ]
    steps = [event for event in events if event["type"] == "step"]
    assert [(s["step"], s["agent"]) for s in steps] == [
        (1, "Coder"),
        (2, "Reviewer"),
    ]
    assert steps[0]["reason"] == "Coder is next."
    assert steps[0]["message"] == "done"


def test_step_budget_always_ends_with_a_final_answer():
    model = ScriptedChatModel(routes=["Coder"])  # Never chooses FINISH.

    events = events_of(model)

    steps = [event for event in events if event["type"] == "step"]
    assert len(steps) == MAX_AGENT_STEPS
    assert events[-2]["type"] == "routing"
    assert events[-2]["next_agent"] == FINISH
    assert "limit" in events[-2]["reason"]
    assert events[-1]["type"] == "final"
    # The budget check replaces the last routing call: 1 designer call,
    # MAX_AGENT_STEPS routing and agent calls, and 1 finalizer call.
    assert model.count(TEAM_CALL) == 1
    assert model.count(ROUTER_CALL) == MAX_AGENT_STEPS
    assert model.count(CHAT_CALL) == MAX_AGENT_STEPS + 1


def test_time_budget_ends_the_run_with_a_final_answer():
    model = ScriptedChatModel(routes=["Coder"])

    events = events_of(model, time_budget=0)

    assert types_of(events) == ["team", "routing", "final"]
    assert events[1]["next_agent"] == FINISH
    assert "time" in events[1]["reason"]
    assert model.count(ROUTER_CALL) == 0


def test_time_budget_comes_from_the_environment(monkeypatch):
    assert workflow.get_run_time_budget() == workflow.RUN_TIME_BUDGET_SECONDS

    monkeypatch.setenv("RUN_TIME_BUDGET_SECONDS", "90.5")
    workflow.reload_settings()
    assert workflow.get_run_time_budget() == 90.5


@pytest.mark.parametrize("value", ["0", "-5", "soon", "nan", "inf"])
def test_bad_time_budget_is_a_configuration_error(monkeypatch, value):
    monkeypatch.setenv("RUN_TIME_BUDGET_SECONDS", value)

    with pytest.raises(ConfigurationError, match="RUN_TIME_BUDGET_SECONDS"):
        workflow.reload_settings()


def test_supervisor_sees_excerpts_while_agents_see_everything():
    reply = "x" * 5000
    model = ScriptedChatModel(routes=["Coder"], reply=reply)

    events_of(model)

    # Ten routing calls over ten 5,000-character replies. Without excerpts
    # the supervisor received about 230,000 characters.
    assert model.input_chars(ROUTER_CALL) < 70_000
    # The finalizer still receives every reply in full.
    final_call_chars = model.calls[-1][1]
    assert final_call_chars > MAX_AGENT_STEPS * len(reply)


def test_excerpt_keeps_the_start_and_end():
    text = "START" + "m" * 5000 + "END"

    shortened = excerpt(text, 100)

    assert shortened.startswith("START")
    assert shortened.endswith("END")
    assert "[... 4908 characters omitted ...]" in shortened
    assert excerpt("short", 100) == "short"


def test_run_id_tags_every_log_record_of_the_run(fake, caplog):
    caplog.handler.addFilter(workflow.RunIdFilter())
    caplog.set_level(logging.INFO, logger="agents")

    run_workflow(TASK, llm=fake, run_id="run-123")
    logging.getLogger("agents.test").info("after the run")

    records = [r for r in caplog.records if r.name.startswith("agents.")]
    assert {r.name for r in records} >= {
        "agents.runner", "agents.graph", "agents.routing", "agents.telemetry",
    }
    assert {r.run_id for r in records[:-1]} == {"run-123"}
    assert records[-1].run_id == "-"  # The caller's context is untouched.


def test_each_model_call_is_logged_with_latency_and_tokens(fake, caplog):
    caplog.set_level(logging.INFO, logger="agents")

    result = run_workflow(TASK, llm=fake)

    messages = [r.getMessage() for r in caplog.records]
    calls = [m for m in messages if " call on scripted-model took " in m]
    stages = [m.split(" call on ")[0] for m in calls]
    assert stages == [
        "Designer", "Supervisor", "Coder", "Supervisor", "Reviewer",
        "Supervisor", "Finalizer",
    ]
    assert all("output tokens)" in m for m in calls)
    summary = messages[-1]
    assert "2 agent steps, 7 model calls" in summary
    assert len(result["run_id"]) == 12


def test_failed_model_calls_are_logged(caplog):
    caplog.set_level(logging.INFO, logger="agents")
    model = ScriptedChatModel(error=ResponseError("unauthorized", 401))

    with pytest.raises(WorkflowError):
        events_of(model)

    assert any(
        "Designer call on scripted-model failed" in r.getMessage()
        for r in caplog.records
    )


def test_unknown_agent_choice_finishes_the_run():
    model = ScriptedChatModel(routes=["Nobody"])

    events = events_of(model)

    assert types_of(events) == ["team", "routing", "final"]
    assert events[1]["next_agent"] == FINISH


def test_prose_routing_is_parsed():
    model = ScriptedChatModel(
        routes=["Reviewer", "FINISH"], prose_routing=True
    )

    events = events_of(model)

    assert types_of(events) == ["team", "routing", "step", "routing", "final"]
    assert events[2]["agent"] == "Reviewer"
    assert events[2]["reason"] == "The next agent should be Reviewer."


def test_prose_routing_without_an_agent_name_fails_cleanly():
    model = ScriptedChatModel(routes=["someone"], prose_routing=True)

    with pytest.raises(WorkflowError) as caught:
        events_of(model)

    assert caught.value.status_code == 502
    assert "routing decision" in caught.value.message


def test_fixed_registry_skips_team_design():
    model = ScriptedChatModel(routes=["Writer", "FINISH"])
    registry = {"Writer": "Write the {answer} in prose."}  # Braces are text.

    events = events_of(model, agent_registry=registry)

    assert events[0]["generated"] is False
    assert [agent["name"] for agent in events[0]["agents"]] == ["Writer"]
    assert events[0]["agents"][0]["skill"] == "writing"
    assert model.count(TEAM_CALL) == 0
    assert types_of(events)[-1] == "final"


def test_run_workflow_collects_every_step(fake):
    result = run_workflow(TASK, llm=fake)

    assert result["task"] == TASK
    assert result["team_generated"] is True
    assert [step["agent"] for step in result["steps"]] == ["Coder", "Reviewer"]
    assert result["final_response"] == "done"


def test_llm_override_reports_the_model_actually_used(fake):
    team_event = events_of(fake)[0]

    assert {agent["model"] for agent in team_event["agents"]} == {
        "scripted-model"
    }
    assert team_event["models"] == {
        "supervisor": "scripted-model",
        "designer": "scripted-model",
        "finalizer": "scripted-model",
    }


def test_configured_models_are_reported_without_an_override(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL_CODING", "coder-model")
    workflow.reload_settings()
    team = workflow.Team({"Coder": "Write code."}, {"Coder": "coding"}, True)

    assert workflow.team_profiles(team)[0]["model"] == "coder-model"
    assert workflow.orchestration_models()["supervisor"] == "gemma4:31b"


# ---------------------------------------------------------------------------
# Team design
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "team",
    [
        None,  # The designer answers in prose.
        [],  # The designer proposes nobody.
        [{"name": "Supervisor", "role_prompt": "Route work."}],  # Reserved.
    ],
)
def test_unusable_designer_output_falls_back_to_the_default_team(team):
    model = ScriptedChatModel(team=team)

    designed = generate_agent_registry(TASK, lambda _role: model)

    assert designed.generated is False
    assert designed.registry == FALLBACK_AGENT_REGISTRY
    assert designed.skills["Reviewer"] == "review"


def test_malformed_designer_output_falls_back_to_the_default_team():
    model = ScriptedChatModel(team=[{"skill": "coding"}])  # No name at all.

    designed = generate_agent_registry(TASK, lambda _role: model)

    assert designed.generated is False


def test_sanitize_team_drops_reserved_duplicate_and_empty_agents():
    specs = [
        AgentSpec(name="data analyst!", role_prompt="Crunch   the numbers."),
        AgentSpec(name="Data-Analyst", role_prompt="Duplicate."),
        AgentSpec(name="finish", role_prompt="Reserved."),
        AgentSpec(name="supervisor", role_prompt="Reserved."),
        AgentSpec(name="???", role_prompt="No letters."),
        AgentSpec.model_construct(name="Writer", role_prompt=" ", skill=""),
        AgentSpec(name="Coder", role_prompt="Code.", skill="CODING"),
    ]

    registry, skills = _sanitize_team(specs)

    assert registry == {
        "Data Analyst": "Crunch the numbers.",
        "Coder": "Code.",
    }
    assert skills == {"Data Analyst": "analysis", "Coder": "coding"}


def test_sanitize_team_caps_the_team_size():
    specs = [
        AgentSpec(name=f"Agent {letter}", role_prompt="Help.")
        for letter in "ABCDEFG"
    ]

    registry, _ = _sanitize_team(specs)

    assert len(registry) == MAX_AGENTS


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Planner: Make a plan.", ("Planner", "Make a plan.", "")),
        (
            "Writer",
            ("Writer", "Contribute your expertise as the team's Writer.", ""),
        ),
        (
            {"role": "Coder", "prompt": "Write code.", "specialty": "coding"},
            ("Coder", "Write code.", "coding"),
        ),
        (
            {"agent_name": "Critic", "instructions": "Find flaws."},
            ("Critic", "Find flaws.", ""),
        ),
    ],
)
def test_agent_spec_accepts_the_shapes_models_send(value, expected):
    spec = AgentSpec.model_validate(value)

    assert (spec.name, spec.role_prompt, spec.skill) == expected


@pytest.mark.parametrize(
    ("proposed", "name", "role", "expected"),
    [
        ("Coding", "Anyone", "", "coding"),
        ("", "Code Reviewer", "", "review"),
        ("wizardry", "Data Wrangler", "", "analysis"),
        ("", "Historian", "", "research"),
        ("", "Strategist", "", "planning"),
        ("", "Copywriter", "", "writing"),
        ("", "Helper", "Be nice.", "general"),
    ],
)
def test_resolve_skill(proposed, name, role, expected):
    assert workflow.resolve_skill(proposed, name, role) == expected


# ---------------------------------------------------------------------------
# Registry validation
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "registry",
    [
        {},
        {"???": "No letters."},
        {"Coder": "One.", "coder": "Two."},
        {"Finalizer": "Reserved."},
        {"Coder:1": "Reserved character."},
        {"Coder|Reviewer": "Reserved character."},
    ],
)
def test_invalid_registry_is_a_client_error(registry):
    model = ScriptedChatModel()

    with pytest.raises(InvalidTeamError) as caught:
        events_of(model, agent_registry=registry)

    assert caught.value.status_code == 400
    assert model.calls == []


def test_invalid_team_error_is_still_a_value_error():
    with pytest.raises(ValueError):
        build_dynamic_agent_graph({"Bad:Name": "x"}, llm=ScriptedChatModel())


# ---------------------------------------------------------------------------
# Models and fallback
# ---------------------------------------------------------------------------
def test_refused_model_falls_back_to_the_default_model():
    refused = ScriptedChatModel(
        model="paid-model", error=ResponseError("payment required", 402)
    )
    default = ScriptedChatModel(
        model="default-model", routes=["Coder", "FINISH"]
    )

    def models(role):
        return default if role == workflow.GENERAL_SKILL else refused

    designed = generate_agent_registry(TASK, models)
    graph = build_dynamic_agent_graph(
        designed.registry, agent_skills=designed.skills, models=models
    )
    state = graph.invoke({
        "messages": [HumanMessage(content=TASK)],
        "task_description": TASK,
        "team_members": list(designed.registry),
        "next_agent": "",
        "routing_reason": "",
    })

    assert designed.generated is True
    replies = [m for m in state["messages"] if isinstance(m, AIMessage)]
    assert [m.name for m in replies] == ["Coder", "Finalizer"]
    assert workflow.response_model(replies[0]) == "default-model"
    assert refused.count(TEAM_CALL) == 1  # Tried first, then fell back.


def test_model_errors_become_client_safe_workflow_errors():
    model = ScriptedChatModel(error=ResponseError("unauthorized", 401))

    with pytest.raises(WorkflowError) as caught:
        events_of(model)

    assert caught.value.status_code == 502
    assert "API key" in caught.value.message


@pytest.mark.parametrize(
    ("error", "status", "fragment"),
    [
        (ResponseError("unauthorized", 401), 502, "rejected the API key"),
        (ResponseError("payment required", 402), 502, "not available"),
        (ResponseError("forbidden", 403), 502, "not available"),
        (ResponseError("not found", 404), 502, "was not found"),
        (ResponseError("boom", 500), 502, "returned an error (500)"),
        (GraphRecursionError("loop"), 422, "step limit"),
        (httpx.ReadTimeout("slow"), 504, "too long"),
        (httpx.ConnectError("refused"), 502, "Could not connect"),
        (ConnectionError("reset"), 502, "Could not connect"),
        (OutputParserException("bad"), 502, "malformed"),
        (RuntimeError("bug"), 500, "unexpectedly"),
    ],
)
def test_to_workflow_error(error, status, fragment):
    mapped = _to_workflow_error(error)

    assert mapped.status_code == status
    assert fragment in mapped.message


@pytest.mark.parametrize("key", ["", "your-ollama-api-key"])
def test_missing_api_key_is_a_configuration_error(monkeypatch, key):
    monkeypatch.setenv("OLLAMA_API_KEY", key)
    workflow.reload_settings()

    with pytest.raises(ConfigurationError) as caught:
        list(stream_workflow(TASK))
    assert caught.value.status_code == 503
    with pytest.raises(ConfigurationError):
        workflow.create_llm()


def test_clients_are_cached_per_model(monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", "test-key")
    workflow.reload_settings()

    client = workflow.get_role_llm("coding")

    assert client is workflow.get_llm("gpt-oss:120b")
    assert client.model == "gpt-oss:120b"
    assert client.base_url == "https://ollama.com"
    assert workflow.create_llm() is not client  # A new, unshared client.


def test_model_settings_come_from_the_environment(monkeypatch):
    assert workflow.get_model_name() == "gpt-oss:120b"
    assert workflow.get_role_model_name("general") == "gpt-oss:120b"

    monkeypatch.setenv("OLLAMA_MODEL", "base-model")
    monkeypatch.setenv("OLLAMA_MODEL_REVIEW", " review-model ")
    monkeypatch.setenv("OLLAMA_MODEL_PLANNING", " ")
    monkeypatch.setenv("OLLAMA_HOST", "http://localhost:11434")
    workflow.reload_settings()

    models = workflow.get_role_models()
    assert models["review"] == "review-model"
    assert models["planning"] == "nemotron-3-super"  # Blank is ignored.
    assert models["general"] == "base-model"
    assert models["supervisor"] == "gemma4:31b"
    assert workflow.get_role_model_name("custom") == "base-model"
    assert workflow.get_ollama_host() == "http://localhost:11434"


def test_settings_are_a_consistent_snapshot(monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", "first-key")
    workflow.reload_settings()
    first = workflow.get_llm("m")

    monkeypatch.setenv("OLLAMA_API_KEY", "second-key")
    monkeypatch.setenv("OLLAMA_HOST", "http://other:11434")
    assert workflow.get_llm("m") is first  # Not reloaded yet.

    settings = workflow.reload_settings()
    second = workflow.get_llm("m")
    assert second is not first  # The new key and host take effect at once.
    assert second.base_url == "http://other:11434"
    assert "second-key" not in repr(settings)


def test_settings_can_be_read_from_a_mapping():
    settings = workflow.Settings.from_env({
        "OLLAMA_MODEL": "base",
        "OLLAMA_MODEL_WRITING": "writer",
        "RUN_TIME_BUDGET_SECONDS": "30",
    })

    assert settings.model_for("writing") == "writer"
    assert settings.model_for("unknown") == "base"
    assert settings.run_time_budget == 30.0
    assert settings.host == workflow.DEFAULT_HOST


def test_compatibility_layer_exports_every_public_name():
    import agents.workflow as facade

    for name in facade.__all__:
        assert hasattr(facade, name), name


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def test_message_text_drops_reasoning_and_joins_parts():
    message = AIMessage(content=[
        "<think>hidden</think>Visible",
        {"type": "text", "text": " text"},
    ])

    assert workflow.message_text(message) == "Visible text"


def test_find_agent_in_text_matches_multi_word_names():
    names = ["Data Analyst", "Writer"]

    assert _find_agent_in_text("Ask the DataAnalyst", names) == (
        "Data Analyst"
    )
    assert _find_agent_in_text("We can FINISH now", names) == FINISH
    assert _find_agent_in_text("No idea", names) is None


def test_transcript_attributes_each_reply():
    messages = [
        HumanMessage(content=TASK),
        AIMessage(content="Here it is.", name="Coder"),
    ]

    transcript = as_transcript(messages)

    assert all(isinstance(m, HumanMessage) for m in transcript)
    assert transcript[1].content == "[Coder]\nHere it is."
