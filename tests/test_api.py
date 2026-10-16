import base64
import json
import logging
import re
import threading
import time
from urllib.parse import urlsplit

import pytest
from ollama import ResponseError

import app as app_module
from agents.workflow import RunIdFilter

TASK = "Write a function that adds two numbers."


def basic_auth(username, password):
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def sse_events(body):
    """Parse an SSE body into (event, data) pairs, skipping comments."""
    events = []
    for frame in body.strip().split("\n\n"):
        lines = [
            line for line in frame.split("\n") if not line.startswith(":")
        ]
        if not lines:
            continue
        name = lines[0].removeprefix("event: ")
        data = json.loads(lines[1].removeprefix("data: "))
        events.append((name, data))
    return events


# ---------------------------------------------------------------------------
# Pages and headers
# ---------------------------------------------------------------------------
def test_index_renders(client):
    response = client.get("/")

    assert response.status_code == 200
    assert b"What should the team work on?" in response.data


def test_security_headers_are_set(client):
    headers = client.get("/").headers

    assert "default-src 'self'" in headers["Content-Security-Policy"]
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Referrer-Policy"] == "same-origin"


def test_csp_allows_exact_files_rather_than_whole_hosts(client):
    csp = client.get("/").headers["Content-Security-Policy"]

    directives = dict(
        directive.split(" ", 1) for directive in csp.split("; ")
    )
    assert directives["object-src"] == "'none'"
    for directive, sources in directives.items():
        for source in sources.split():
            if source.startswith("https:"):
                path = urlsplit(source).path
                assert len(path) > 1, f"{directive} allows a whole host"


def test_page_loads_only_pinned_cdn_files(client):
    page = client.get("/").get_data(as_text=True)
    csp = app_module.CONTENT_SECURITY_POLICY

    external = set(re.findall(r'(?:src|href)="(https://[^"]+)"', page))
    assets = [
        *app_module.CDN_STYLES.values(),
        *app_module.CDN_SCRIPTS.values(),
    ]
    assert external == {asset.url for asset in assets}
    for asset in assets:
        assert f'integrity="{asset.integrity}"' in page
        assert asset.url in csp


def test_extra_security_headers(client):
    headers = client.get("/").headers

    assert headers["Cross-Origin-Opener-Policy"] == "same-origin"
    assert "camera=()" in headers["Permissions-Policy"]
    assert "Strict-Transport-Security" not in headers


def test_hsts_is_sent_over_https(client):
    response = client.get("/", base_url="https://localhost")

    assert response.headers["Strict-Transport-Security"] == "max-age=31536000"


@pytest.mark.parametrize(("proxies", "hsts"), [(0, False), (1, True)])
def test_forwarded_https_is_trusted_only_behind_a_proxy(
    make_app, proxies, hsts
):
    client = make_app(TRUSTED_PROXIES=proxies).test_client()

    response = client.get("/", headers={"X-Forwarded-Proto": "https"})

    assert ("Strict-Transport-Security" in response.headers) is hsts


def test_health(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json["status"] == "ok"
    assert response.json["role_models"]["supervisor"] == "gemma4:31b"


# ---------------------------------------------------------------------------
# Request validation and error handling
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("kwargs", "fragment"),
    [
        ({"data": "task=hi", "content_type": "text/plain"}, "JSON object"),
        ({"json": ["not", "an", "object"]}, "JSON object"),
        ({"json": {}}, "non-empty string"),
        ({"json": {"task": "   "}}, "non-empty string"),
        ({"json": {"task": 42}}, "non-empty string"),
        ({"json": {"task": "x" * 4001}}, "at most 4000"),
    ],
)
@pytest.mark.parametrize("url", ["/api/run", "/api/stream"])
def test_invalid_requests_are_rejected(client, url, kwargs, fragment):
    response = client.post(url, **kwargs)

    assert response.status_code == 400
    assert response.json["status"] == "error"
    assert fragment in response.json["error"]


def test_oversized_body_is_rejected(client):
    response = client.post("/api/run", json={"task": "x" * 70_000})

    assert response.status_code == 413
    assert response.json["status"] == "error"


def test_api_errors_keep_their_headers(client):
    response = client.get("/api/run")

    assert response.status_code == 405
    assert response.json == {
        "status": "error",
        "error": "The method is not allowed for the requested URL.",
    }
    assert set(response.headers["Allow"].split(", ")) == {"POST", "OPTIONS"}
    assert response.mimetype == "application/json"


def test_unknown_api_path_is_json_and_pages_are_html(client):
    api = client.get("/api/missing")
    page = client.get("/missing")

    assert api.status_code == 404 and api.json["status"] == "error"
    assert page.status_code == 404 and page.mimetype == "text/html"


def test_unexpected_errors_are_hidden(make_app, monkeypatch):
    client = make_app().test_client()

    def explode(task, **_kwargs):
        raise RuntimeError("secret detail")

    monkeypatch.setattr(app_module, "run_workflow", explode)
    response = client.post("/api/run", json={"task": TASK})

    assert response.status_code == 500
    assert response.json["error"] == "Internal server error."


# ---------------------------------------------------------------------------
# Running workflows
# ---------------------------------------------------------------------------
def test_run_returns_every_step(client):
    response = client.post("/api/run", json={"task": f"  {TASK}  "})

    body = response.json
    assert response.status_code == 200
    assert list(body)[:2] == ["status", "task"]
    assert body["status"] == "success"
    assert body["task"] == TASK
    assert [step["agent"] for step in body["steps"]] == ["Coder", "Reviewer"]
    assert body["final_response"] == "done"
    assert body["models"]["supervisor"] == "scripted-model"
    assert len(body["run_id"]) == 12
    assert response.headers["X-Run-ID"] == body["run_id"]


def test_run_reports_workflow_errors(make_app, fake):
    fake.error = ResponseError("unauthorized", 401)
    client = make_app().test_client()

    response = client.post("/api/run", json={"task": TASK})

    assert response.status_code == 502
    assert "API key" in response.json["error"]
    assert response.headers["X-Run-ID"]  # So the failure can be traced.


def test_stream_sends_events_in_order(client):
    response = client.post("/api/stream", json={"task": TASK})

    assert response.status_code == 200
    assert response.mimetype == "text/event-stream"
    assert response.headers["Cache-Control"] == "no-cache"
    events = sse_events(response.get_data(as_text=True))
    assert [name for name, _ in events] == [
        "start", "team", "routing", "step", "routing", "step", "routing",
        "final", "done",
    ]
    assert events[0][1] == {
        "task": TASK, "run_id": response.headers["X-Run-ID"],
    }
    assert events[-1][1] == {"status": "success"}


def test_stream_sends_heartbeats_while_the_workflow_is_quiet(
    make_app, monkeypatch
):
    client = make_app(SSE_HEARTBEAT_SECONDS=0.02).test_client()

    def slow(task, **_kwargs):
        time.sleep(0.2)
        yield {"type": "final", "message": "late", "model": "m"}

    monkeypatch.setattr(app_module, "stream_workflow", slow)
    body = client.post("/api/stream", json={"task": TASK}).get_data(
        as_text=True
    )

    assert ": keepalive\n\n" in body
    assert [name for name, _ in sse_events(body)] == ["start", "final", "done"]


def test_disconnect_stops_the_workflow(make_app, monkeypatch):
    client = make_app(MAX_CONCURRENT_RUNS=1).test_client()
    produced = []
    stopped = threading.Event()

    def endless(task, **_kwargs):
        try:
            for step in range(1, 21):
                time.sleep(0.02)
                produced.append(step)
                yield {"type": "routing", "next_agent": "Coder", "reason": ""}
        finally:
            stopped.set()

    monkeypatch.setattr(app_module, "stream_workflow", endless)
    response = client.post("/api/stream", json={"task": TASK}, buffered=False)
    chunks = iter(response.response)
    assert next(chunks).startswith(b"event: start")
    assert next(chunks).startswith(b"event: routing")

    response.close()  # What the server does when the client goes away.

    assert stopped.wait(timeout=5)
    assert len(produced) < 20
    # The run slot is free again for the next request.
    assert client.post("/api/run", json={"task": TASK}).status_code == 200


def test_log_records_carry_the_run_id(client, caplog):
    caplog.handler.addFilter(RunIdFilter())
    caplog.set_level(logging.INFO)

    response = client.post("/api/run", json={"task": TASK})

    run_id = response.json["run_id"]
    workflow_records = [
        record for record in caplog.records
        if record.name.startswith("agents.")
    ]
    assert workflow_records
    assert {record.run_id for record in workflow_records} == {run_id}
    assert any("model calls" in r.getMessage() for r in workflow_records)


def test_logging_setup_adds_the_run_id_filter():
    app_module._configure_logging()

    for handler in logging.getLogger().handlers:
        assert any(isinstance(f, RunIdFilter) for f in handler.filters)


def test_stream_reports_workflow_errors_as_events(make_app, fake):
    fake.error = ResponseError("unauthorized", 401)
    client = make_app().test_client()

    events = sse_events(
        client.post("/api/stream", json={"task": TASK}).get_data(as_text=True)
    )

    assert [name for name, _ in events] == ["start", "error"]
    assert events[1][1]["status"] == "error"
    assert "API key" in events[1][1]["error"]


def test_stream_hides_unexpected_errors(make_app, monkeypatch):
    client = make_app().test_client()

    def explode(task, **_kwargs):
        yield {"type": "routing", "next_agent": "Coder", "reason": ""}
        raise RuntimeError("secret detail")

    monkeypatch.setattr(app_module, "stream_workflow", explode)
    events = sse_events(
        client.post("/api/stream", json={"task": TASK}).get_data(as_text=True)
    )

    assert [name for name, _ in events] == ["start", "routing", "error"]
    assert events[-1][1]["error"] == "The workflow failed unexpectedly."


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------
@pytest.fixture
def secured(make_app):
    app = make_app(AUTH_USERNAME="alice", AUTH_PASSWORD="s3cret")
    return app.test_client()


@pytest.mark.parametrize(
    "headers",
    [{}, basic_auth("alice", "wrong"), basic_auth("bob", "s3cret")],
)
def test_login_is_required_when_a_password_is_set(secured, headers):
    page = secured.get("/", headers=headers)
    api = secured.post("/api/run", json={"task": TASK}, headers=headers)

    assert page.status_code == 401
    assert page.headers["WWW-Authenticate"].startswith('Basic realm=')
    assert api.status_code == 401
    assert api.json == {"status": "error", "error": "Authentication required."}
    assert "Content-Security-Policy" in api.headers


def test_correct_credentials_are_accepted(secured):
    headers = basic_auth("alice", "s3cret")

    assert secured.get("/", headers=headers).status_code == 200
    response = secured.post("/api/run", json={"task": TASK}, headers=headers)
    assert response.status_code == 200


def test_health_and_static_files_stay_public(secured):
    assert secured.get("/api/health").status_code == 200
    assert secured.get("/static/js/app.js").status_code == 200


def test_login_is_off_without_a_password(client):
    assert client.get("/").status_code == 200


def test_login_settings_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "pw")

    app = app_module.create_app({"TESTING": True})

    assert app.config["AUTH_USERNAME"] == "admin"
    assert app.config["AUTH_PASSWORD"] == "pw"


# ---------------------------------------------------------------------------
# Concurrent-run cap
# ---------------------------------------------------------------------------
def test_runs_over_the_cap_get_429_until_a_slot_frees(make_app):
    client = make_app(MAX_CONCURRENT_RUNS=1).test_client()

    first = client.post("/api/stream", json={"task": TASK}, buffered=False)
    busy_stream = client.post("/api/stream", json={"task": TASK})
    busy_run = client.post("/api/run", json={"task": TASK})

    for busy in (busy_stream, busy_run):
        assert busy.status_code == 429
        assert busy.headers["Retry-After"] == "30"
        assert busy.json["status"] == "error"
        assert "Too many workflows" in busy.json["error"]

    first.close()  # The server closes the response when the client leaves.
    assert client.post("/api/run", json={"task": TASK}).status_code == 200


def test_stream_frees_its_slot_without_the_response_being_closed(
    monkeypatch,
):
    # Werkzeug's development server skips Response.close() when the client
    # resets the connection; the stream is then ended by garbage collection.
    released = []
    stopped = threading.Event()

    def endless(task, **_kwargs):
        try:
            while True:
                time.sleep(0.02)
                yield {"type": "routing", "next_agent": "Coder", "reason": ""}
        finally:
            stopped.set()

    monkeypatch.setattr(app_module, "stream_workflow", endless)
    stream = app_module._event_stream(
        TASK, "run-1", 5.0, lambda: released.append(True)
    )
    next(stream)
    next(stream)

    stream.close()

    assert released  # Freed at once, without waiting for the worker.
    assert stopped.wait(timeout=5)


def test_freeing_a_run_slot_twice_frees_it_once(make_app):
    app = make_app(MAX_CONCURRENT_RUNS=1)
    slots = app.extensions["run_slots"]

    with app.test_request_context():
        release = app_module._acquire_run_slot()
        release()
        release()  # A BoundedSemaphore would raise ValueError here.

    assert slots.acquire(blocking=False)
    assert not slots.acquire(blocking=False)


def test_slot_is_freed_after_a_failed_run(make_app, fake):
    fake.error = ResponseError("unauthorized", 401)
    client = make_app(MAX_CONCURRENT_RUNS=1).test_client()

    assert client.post("/api/run", json={"task": TASK}).status_code == 502
    assert client.post("/api/run", json={"task": TASK}).status_code == 502


@pytest.mark.parametrize("value", ["0", "-1", "lots"])
def test_bad_concurrency_setting_fails_at_startup(monkeypatch, value):
    monkeypatch.setenv("MAX_CONCURRENT_RUNS", value)

    with pytest.raises(ValueError, match="MAX_CONCURRENT_RUNS"):
        app_module.create_app({"TESTING": True})


def test_server_settings_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("MAX_CONCURRENT_RUNS", "7")
    monkeypatch.setenv("TRUSTED_PROXIES", "2")

    app = app_module.create_app({"TESTING": True})

    assert app.config["MAX_CONCURRENT_RUNS"] == 7
    assert app.config["TRUSTED_PROXIES"] == 2


def test_bad_proxy_setting_fails_at_startup(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXIES", "-1")

    with pytest.raises(ValueError, match="TRUSTED_PROXIES"):
        app_module.create_app({"TESTING": True})
