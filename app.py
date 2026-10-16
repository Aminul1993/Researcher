"""Flask web application exposing the multi-agent LangGraph workflow.

Run locally with ``python app.py``. For deployment, serve the application
factory with a threaded WSGI server so streaming responses are not blocked,
for example::

    gunicorn --worker-class gthread --threads 8 "app:create_app()"

Keep ``--threads`` at MAX_CONCURRENT_RUNS + 2 or more, so the page and the
health check stay reachable while every run slot is busy.
"""

import hmac
import json
import logging
import os
import queue
import threading
from collections.abc import Callable, Generator, Mapping
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from flask import (
    Blueprint,
    Flask,
    Response,
    current_app,
    g,
    jsonify,
    render_template,
    request,
)
from werkzeug.exceptions import BadRequest, HTTPException, TooManyRequests
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.wrappers import Response as WerkzeugResponse

from agents.workflow import (
    MAX_AGENTS,
    ROLE_SUPERVISOR,
    RunIdFilter,
    WorkflowError,
    get_model_name,
    get_role_model_name,
    get_role_models,
    new_run_id,
    reload_settings,
    run_workflow,
    stream_workflow,
)

BASE_DIR = Path(__file__).resolve().parent
MAX_TASK_LENGTH = 4000
MAX_REQUEST_BYTES = 64 * 1024
DEFAULT_USERNAME = "admin"
DEFAULT_MAX_CONCURRENT_RUNS = 4
RETRY_AFTER_SECONDS = 30
# Proxies such as nginx and AWS ALB close connections that stay silent for
# 60 seconds, which a single slow model call can exceed.
SSE_HEARTBEAT_SECONDS = 15.0
# Reachable without logging in, even when APP_PASSWORD is set.
PUBLIC_ENDPOINTS = frozenset({"main.health", "static"})


@dataclass(frozen=True)
class CdnAsset:
    """A third-party file the page loads, pinned by its integrity hash."""

    url: str
    integrity: str


# Third-party files the page loads. The template and the Content Security
# Policy are both built from these tables, so upgrading a library means
# changing its URL and integrity hash here and nowhere else.
CDN_STYLES = {
    "bootstrap": CdnAsset(
        "https://cdn.jsdelivr.net/npm/bootstrap@5.3.8/dist/css/"
        "bootstrap.min.css",
        "sha384-sRIl4kxILFvY47J16cr9ZwB07vP4J8+LH7qKQnuqkuIAvNWLzeN8tE5YBujZqJLB",
    ),
    "bootstrap_icons": CdnAsset(
        "https://cdn.jsdelivr.net/npm/bootstrap-icons@1.13.1/font/"
        "bootstrap-icons.min.css",
        "sha384-CK2SzKma4jA5H/MXDUU7i1TqZlCFaD4T01vtyDFvPlD97JQyS+IsSh1nI2EFbpyk",
    ),
    "hljs_light": CdnAsset(
        "https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.12.0/styles/"
        "github.min.css",
        "sha384-eFTL69TLRZTkNfYZOLM+G04821K1qZao/4QLJbet1pP4tcF+fdXq/9CdqAbWRl/L",
    ),
    "hljs_dark": CdnAsset(
        "https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.12.0/styles/"
        "github-dark.min.css",
        "sha384-wH75j6z1lH97ZOpMOInqhgKzFkAInZPPSPlZpYKYTOqsaizPvhQZmAtLcPKXpLyH",
    ),
}
CDN_SCRIPTS = {
    "marked": CdnAsset(
        "https://cdn.jsdelivr.net/npm/marked@18.0.14/lib/marked.umd.js",
        "sha384-2vpGtuKqJvFlwJqYnf/wUMuzUfhUnYBt9oay0e2yaFcq0Dh6/aEbQ8YAOeKGzlYo",
    ),
    "dompurify": CdnAsset(
        "https://cdn.jsdelivr.net/npm/dompurify@3.4.16/dist/purify.min.js",
        "sha384-a7SzOxErzJ3ZpQz0zJ32d67dSitNzPcbfybc/ykU9KJhMgZkwqfSxlhhdJRS+XGL",
    ),
    "highlight": CdnAsset(
        "https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.12.0/"
        "highlight.min.js",
        "sha384-wjfDDhOPPdjtva8vWBhWeVprSpmxisEu5aYT3q1JyACqXpdKpo3PWZTMVq24MBix",
    ),
}
# Bootstrap Icons loads its font files from next to its stylesheet.
CDN_FONTS = (
    CDN_STYLES["bootstrap_icons"].url.rsplit("/", 1)[0] + "/fonts/",
)


def _content_security_policy() -> str:
    """Allow the exact CDN files the page uses, rather than whole hosts."""
    scripts = " ".join(asset.url for asset in CDN_SCRIPTS.values())
    styles = " ".join(asset.url for asset in CDN_STYLES.values())
    return "; ".join((
        "default-src 'self'",
        f"script-src 'self' {scripts}",
        f"style-src 'self' {styles}",
        f"font-src 'self' {' '.join(CDN_FONTS)}",
        "img-src 'self' data:",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ))


CONTENT_SECURITY_POLICY = _content_security_policy()
PERMISSIONS_POLICY = ", ".join(
    f"{feature}=()"
    for feature in (
        "accelerometer",
        "camera",
        "geolocation",
        "gyroscope",
        "magnetometer",
        "microphone",
        "payment",
        "usb",
    )
)
# Sent only over HTTPS. Browsers then refuse plain HTTP for a year.
HSTS_POLICY = "max-age=31536000"

logger = logging.getLogger(__name__)
bp = Blueprint("main", __name__)

ErrorResponse = tuple[Response, int]
# What the workflow thread hands the stream: ("event", event),
# ("error", message) or ("done", None).
StreamItem = tuple[str, Any]


# =====================================================================
# Helpers
# =====================================================================
def _read_task() -> str:
    """Validate the JSON request body and return the trimmed task."""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise BadRequest(
            "Request body must be a JSON object with a 'task' field."
        )
    task = payload.get("task")
    if not isinstance(task, str) or not task.strip():
        raise BadRequest("'task' must be a non-empty string.")
    task = task.strip()
    limit = current_app.config["MAX_TASK_LENGTH"]
    if len(task) > limit:
        raise BadRequest(f"'task' must be at most {limit} characters.")
    return task


def _sse(event: str, data: Mapping[str, Any]) -> str:
    """Format one Server-Sent Events frame."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _error_response(message: str, status_code: int) -> ErrorResponse:
    return jsonify(status="error", error=message), status_code


def _is_api_request() -> bool:
    return request.path.startswith("/api/")


def _acquire_run_slot() -> Callable[[], None]:
    """Reserve one of the concurrent-run slots, or answer 429.

    Returns the function that frees the slot again. It is safe to call more
    than once; only the first call frees the slot.
    """
    slots: threading.BoundedSemaphore = current_app.extensions["run_slots"]
    if not slots.acquire(blocking=False):
        raise TooManyRequests(
            "Too many workflows are running. Please try again shortly.",
            retry_after=RETRY_AFTER_SECONDS,
        )
    first_call = threading.Lock()

    def release() -> None:
        if first_call.acquire(blocking=False):
            slots.release()

    return release


def _credentials_match(username: str, password: str) -> bool:
    """Compare credentials in constant time."""
    username_ok = hmac.compare_digest(
        username.encode(), current_app.config["AUTH_USERNAME"].encode()
    )
    password_ok = hmac.compare_digest(
        password.encode(), current_app.config["AUTH_PASSWORD"].encode()
    )
    return username_ok and password_ok


def _require_auth() -> Response | None:
    """Require HTTP Basic credentials when APP_PASSWORD is configured."""
    if not current_app.config["AUTH_PASSWORD"]:
        return None
    if request.endpoint in PUBLIC_ENDPOINTS:
        return None
    auth = request.authorization
    if (
        auth is not None
        and auth.type == "basic"
        and _credentials_match(auth.username or "", auth.password or "")
    ):
        return None

    if _is_api_request():
        response = jsonify(status="error", error="Authentication required.")
    else:
        response = Response("Authentication required.", mimetype="text/plain")
    response.status_code = 401
    response.headers["WWW-Authenticate"] = (
        'Basic realm="Researcher", charset="UTF-8"'
    )
    return response


def _int_env(name: str, default: int, minimum: int) -> int:
    """Read an integer setting, failing fast on a bad value."""
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        value = minimum - 1
    if value < minimum:
        raise ValueError(
            f"{name} must be a whole number of at least {minimum}, "
            f"not {raw!r}."
        )
    return value


def _produce_events(
    task: str,
    run_id: str,
    events: queue.Queue[StreamItem],
    cancel: threading.Event,
    release: Callable[[], None],
) -> None:
    """Run the workflow in a worker thread, handing events to the stream.

    Stops at the next event once ``cancel`` is set. A model call that is
    already in progress still finishes first. Frees the run slot when done.
    """
    try:
        with closing(stream_workflow(task, run_id=run_id)) as workflow:
            for event in workflow:
                if cancel.is_set():
                    logger.info("Run %s cancelled after disconnect", run_id)
                    return
                events.put(("event", event))
        events.put(("done", None))
    except WorkflowError as exc:
        events.put(("error", exc.message))
    except Exception:
        logger.exception("Unexpected error while streaming run %s", run_id)
        events.put(("error", "The workflow failed unexpectedly."))
    finally:
        release()


def _event_stream(
    task: str,
    run_id: str,
    heartbeat_seconds: float,
    release: Callable[[], None],
) -> Generator[str, None, None]:
    """Relay workflow events to the client as they happen.

    The workflow runs in its own thread so the stream can send a comment
    line whenever nothing else has been sent for ``heartbeat_seconds``,
    which keeps proxies from closing the connection during a slow model
    call. SSE clients ignore comment lines.

    The run slot is freed as soon as the stream ends, however it ends, and
    again (harmlessly) when the worker finishes. It must not depend only on
    the server closing the response: Werkzeug's development server skips
    that when the client resets the connection, and the stream is then
    ended by garbage collection instead.
    """
    events: queue.Queue[StreamItem] = queue.Queue()
    cancel = threading.Event()
    worker = threading.Thread(
        target=_produce_events,
        args=(task, run_id, events, cancel, release),
        name=f"workflow-{run_id}",
        daemon=True,
    )
    try:
        yield _sse("start", {"task": task, "run_id": run_id})
        worker.start()
        while True:
            try:
                kind, payload = events.get(timeout=heartbeat_seconds)
            except queue.Empty:
                yield ": keepalive\n\n"
                continue
            if kind == "event":
                yield _sse(payload["type"], payload)
            elif kind == "error":
                yield _sse("error", {"status": "error", "error": payload})
                return
            else:
                yield _sse("done", {"status": "success"})
                return
    except GeneratorExit:
        logger.info("Client disconnected; stopping run %s", run_id)
        raise
    finally:
        cancel.set()
        release()


# =====================================================================
# Routes
# =====================================================================
@bp.get("/")
def index() -> str:
    return render_template(
        "index.html",
        model=get_model_name(),
        supervisor_model=get_role_model_name(ROLE_SUPERVISOR),
        max_agents=MAX_AGENTS,
        max_task_length=current_app.config["MAX_TASK_LENGTH"],
        cdn_styles=CDN_STYLES,
        cdn_scripts=CDN_SCRIPTS,
    )


@bp.get("/api/health")
def health() -> Response:
    return jsonify(
        status="ok", model=get_model_name(), role_models=get_role_models()
    )


@bp.post("/api/run")
def run() -> Response:
    """Run the workflow to completion and return every step at once."""
    task = _read_task()
    release = _acquire_run_slot()
    g.run_id = new_run_id()
    logger.info(
        "POST /api/run: run %s (%d-character task)", g.run_id, len(task)
    )
    try:
        result = run_workflow(task, run_id=g.run_id)
    finally:
        release()
    return jsonify({"status": "success", **result})


@bp.post("/api/stream")
def stream() -> Response:
    """Stream workflow events to the client as Server-Sent Events."""
    task = _read_task()
    release = _acquire_run_slot()
    g.run_id = new_run_id()
    logger.info(
        "POST /api/stream: run %s (%d-character task)", g.run_id, len(task)
    )
    # current_app is not available inside the streaming generator.
    heartbeat = current_app.config["SSE_HEARTBEAT_SECONDS"]
    response = Response(
        _event_stream(task, g.run_id, heartbeat, release),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
    # Frees the slot if the client leaves before the stream starts.
    response.call_on_close(release)
    return response


# =====================================================================
# Error handling and response hardening
# =====================================================================
def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(WorkflowError)
    def handle_workflow_error(exc: WorkflowError) -> ErrorResponse:
        logger.warning(
            "Run %s failed: %s", g.get("run_id", "-"), exc.message
        )
        return _error_response(exc.message, exc.status_code)

    @app.errorhandler(HTTPException)
    def handle_http_error(
        exc: HTTPException,
    ) -> HTTPException | WerkzeugResponse:
        if not _is_api_request():
            return exc
        # Start from Werkzeug's own response so headers such as Allow and
        # Retry-After survive, and replace only the body.
        response = exc.get_response()
        response.set_data(app.json.dumps(
            {"status": "error", "error": exc.description or exc.name}
        ))
        response.mimetype = "application/json"
        return response

    @app.errorhandler(Exception)
    def handle_unexpected_error(
        exc: Exception,
    ) -> ErrorResponse | tuple[str, int]:
        logger.error(
            "Unhandled error on %s %s",
            request.method,
            request.path,
            exc_info=exc,
        )
        if _is_api_request():
            return _error_response("Internal server error.", 500)
        return "Internal server error", 500


def _set_security_headers(response: Response) -> Response:
    headers = response.headers
    headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
    headers.setdefault("X-Content-Type-Options", "nosniff")
    headers.setdefault("X-Frame-Options", "DENY")
    headers.setdefault("Referrer-Policy", "same-origin")
    headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    headers.setdefault("Permissions-Policy", PERMISSIONS_POLICY)
    # Behind a TLS-terminating proxy this needs TRUSTED_PROXIES.
    if request.is_secure:
        headers.setdefault("Strict-Transport-Security", HSTS_POLICY)
    return response


def _add_run_id_header(response: Response) -> Response:
    """Let clients quote the run ID that tags this run's log records."""
    run_id = g.get("run_id")
    if run_id:
        response.headers["X-Run-ID"] = run_id
    return response


def _configure_logging() -> None:
    level = getattr(
        logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO
    )
    if not isinstance(level, int):
        level = logging.INFO
    logging.basicConfig(
        level=level,
        format=(
            "%(asctime)s %(levelname)-8s %(name)s [%(run_id)s]: %(message)s"
        ),
    )
    # Every handler needs the filter, or %(run_id)s cannot be formatted.
    for handler in logging.getLogger().handlers:
        if not any(isinstance(f, RunIdFilter) for f in handler.filters):
            handler.addFilter(RunIdFilter())
    # httpx logs every model request at INFO; keep the app's logs readable.
    logging.getLogger("httpx").setLevel(logging.WARNING)


# =====================================================================
# Application factory
# =====================================================================
def create_app(config: Mapping[str, Any] | None = None) -> Flask:
    """Create and configure the Flask application."""
    load_dotenv(BASE_DIR / ".env")
    # The workflow reads its settings once; make sure it sees .env.
    reload_settings()
    _configure_logging()

    app = Flask(__name__)
    app.config.update(
        MAX_CONTENT_LENGTH=MAX_REQUEST_BYTES,
        MAX_TASK_LENGTH=MAX_TASK_LENGTH,
        AUTH_USERNAME=os.getenv("APP_USERNAME", "").strip()
        or DEFAULT_USERNAME,
        AUTH_PASSWORD=os.getenv("APP_PASSWORD", ""),
        MAX_CONCURRENT_RUNS=_int_env(
            "MAX_CONCURRENT_RUNS", DEFAULT_MAX_CONCURRENT_RUNS, minimum=1
        ),
        SSE_HEARTBEAT_SECONDS=SSE_HEARTBEAT_SECONDS,
        TRUSTED_PROXIES=_int_env("TRUSTED_PROXIES", 0, minimum=0),
    )
    if config:
        app.config.update(config)
    proxies = app.config["TRUSTED_PROXIES"]
    if proxies:
        # Trust X-Forwarded-* from that many proxies, so request.is_secure
        # and the client address reflect the original request.
        app.wsgi_app = ProxyFix(  # type: ignore[method-assign]
            app.wsgi_app, x_for=proxies, x_proto=proxies, x_host=proxies
        )
    # Keep response keys in the documented order: status, task, steps, ...
    app.json.sort_keys = False  # type: ignore[attr-defined]
    # The cap is per process: each gunicorn worker has its own slots.
    app.extensions["run_slots"] = threading.BoundedSemaphore(
        app.config["MAX_CONCURRENT_RUNS"]
    )

    app.register_blueprint(bp)
    _register_error_handlers(app)
    app.before_request(_require_auth)
    app.after_request(_set_security_headers)
    app.after_request(_add_run_id_header)

    if not app.config["AUTH_PASSWORD"]:
        logger.warning(
            "Login is off because APP_PASSWORD is not set; anyone who can "
            "reach this server can run workflows on your Ollama key."
        )
    logger.info(
        "Application ready (model=%s, max concurrent runs=%d)",
        get_model_name(),
        app.config["MAX_CONCURRENT_RUNS"],
    )
    return app


if __name__ == "__main__":
    application = create_app()
    application.run(
        host=os.getenv("FLASK_HOST", "127.0.0.1"),
        port=int(os.getenv("FLASK_PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "").lower() in {"1", "true", "yes"},
        threaded=True,
    )
