"""Flask web application exposing the multi-agent LangGraph workflow.

Run locally with ``python app.py``. For deployment, serve the application
factory with a threaded WSGI server so streaming responses are not blocked,
for example::

    gunicorn --worker-class gthread --threads 8 "app:create_app()"
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Iterator, Mapping, Optional, Tuple, Union

from dotenv import load_dotenv
from flask import (
    Blueprint,
    Flask,
    Response,
    current_app,
    jsonify,
    render_template,
    request,
)
from werkzeug.exceptions import BadRequest, HTTPException

from agents.workflow import (
    MAX_AGENTS,
    ROLE_SUPERVISOR,
    WorkflowError,
    get_model_name,
    get_role_model_name,
    get_role_models,
    run_workflow,
    stream_workflow,
)

BASE_DIR = Path(__file__).resolve().parent
MAX_TASK_LENGTH = 4000
MAX_REQUEST_BYTES = 64 * 1024

CONTENT_SECURITY_POLICY = "; ".join((
    "default-src 'self'",
    "script-src 'self' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com",
    "style-src 'self' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com",
    "font-src 'self' https://cdn.jsdelivr.net",
    "img-src 'self' data:",
    "connect-src 'self'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
))

logger = logging.getLogger(__name__)
bp = Blueprint("main", __name__)

ErrorResponse = Tuple[Response, int]


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


def _event_stream(task: str) -> Iterator[str]:
    """Relay workflow events to the client as they happen."""
    yield _sse("start", {"task": task})
    try:
        for event in stream_workflow(task):
            yield _sse(event["type"], event)
    except GeneratorExit:
        logger.info("Client disconnected; stream cancelled")
        raise
    except WorkflowError as exc:
        yield _sse("error", {"status": "error", "error": exc.message})
        return
    except Exception:
        logger.exception("Unexpected error while streaming")
        yield _sse(
            "error",
            {"status": "error", "error": "The workflow failed unexpectedly."},
        )
        return
    yield _sse("done", {"status": "success"})


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
    logger.info("POST /api/run (%d-character task)", len(task))
    result = run_workflow(task)
    return jsonify({"status": "success", **result})


@bp.post("/api/stream")
def stream() -> Response:
    """Stream workflow events to the client as Server-Sent Events."""
    task = _read_task()
    logger.info("POST /api/stream (%d-character task)", len(task))
    return Response(
        _event_stream(task),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# =====================================================================
# Error handling and response hardening
# =====================================================================
def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(WorkflowError)
    def handle_workflow_error(exc: WorkflowError) -> ErrorResponse:
        logger.warning("Workflow request failed: %s", exc.message)
        return _error_response(exc.message, exc.status_code)

    @app.errorhandler(HTTPException)
    def handle_http_error(
        exc: HTTPException,
    ) -> Union[HTTPException, ErrorResponse]:
        if not _is_api_request():
            return exc
        return _error_response(exc.description or exc.name, exc.code or 500)

    @app.errorhandler(Exception)
    def handle_unexpected_error(
        exc: Exception,
    ) -> Union[ErrorResponse, Tuple[str, int]]:
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
    return response


def _configure_logging() -> None:
    level = getattr(
        logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO
    )
    if not isinstance(level, int):
        level = logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    # httpx logs every model request at INFO; keep the app's logs readable.
    logging.getLogger("httpx").setLevel(logging.WARNING)


# =====================================================================
# Application factory
# =====================================================================
def create_app(config: Optional[Mapping[str, Any]] = None) -> Flask:
    """Create and configure the Flask application."""
    load_dotenv(BASE_DIR / ".env")
    _configure_logging()

    app = Flask(__name__)
    app.config.update(
        MAX_CONTENT_LENGTH=MAX_REQUEST_BYTES,
        MAX_TASK_LENGTH=MAX_TASK_LENGTH,
    )
    if config:
        app.config.update(config)
    # Keep response keys in the documented order: status, task, steps, ...
    app.json.sort_keys = False  # type: ignore[attr-defined]

    app.register_blueprint(bp)
    _register_error_handlers(app)
    app.after_request(_set_security_headers)

    logger.info("Application ready (model=%s)", get_model_name())
    return app


if __name__ == "__main__":
    application = create_app()
    application.run(
        host=os.getenv("FLASK_HOST", "127.0.0.1"),
        port=int(os.getenv("FLASK_PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG", "").lower() in {"1", "true", "yes"},
        threaded=True,
    )
