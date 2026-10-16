# Researcher

Researcher is a web app that builds a small team of AI agents for each task you give it. A supervisor passes the work between the agents, and a finalizer merges what they produce into one answer. You can watch each agent's contribution appear as it is written.

It is built with [LangGraph](https://github.com/langchain-ai/langgraph), [Flask](https://flask.palletsprojects.com/) and [Ollama Cloud](https://ollama.com). Each agent runs on the model that suits its skill, so the coder, the reviewer and the writer can all use different models.

## How it works

```mermaid
flowchart LR
    T([Task]) --> D[Team designer]
    D -- "2–5 agents,<br/>one skill each" --> S{Supervisor}
    S -- next agent --> A1[Agent]
    S -- next agent --> A2[Agent]
    S -- next agent --> A3[Agent]
    A1 --> S
    A2 --> S
    A3 --> S
    S -- FINISH --> F[Finalizer]
    F --> R([Final answer])
```

1. **Team design.** An LLM reads the task and designs 2 to 5 specialist agents. Each agent gets a name, a role prompt and one skill: `planning`, `research`, `coding`, `review`, `analysis`, `writing` or `general`. If the designer's output can't be used, a fixed fallback team takes over: Planner, Researcher, Coder and Reviewer.
2. **Routing.** Before each step, the supervisor reads the conversation so far and picks the next agent, or `FINISH`. It only needs to route, so it sees the first and last 600 characters of each long reply rather than the whole text. It also explains why it chose that agent, and the UI shows the explanation with each step. After 10 agent replies, or once the run's time budget has passed, the supervisor stops routing and hands over to the finalizer, so every run ends with an answer.
3. **Specialist work.** The chosen agent runs on the model assigned to its skill. Its reply is added to the shared conversation, and control goes back to the supervisor.
4. **Finalizing.** When the supervisor chooses `FINISH`, the finalizer combines the team's work into one Markdown answer. Where there is a reviewed version of any code, it uses that version.

If Ollama refuses a role's model (for example, `402 Payment Required` on the Free plan), that call is retried on `OLLAMA_MODEL` instead of failing the run.

## Features

- A new team of agents for every task, with each agent's model chosen by its skill
- Live streaming over Server-Sent Events, or a single blocking request
- A timeline of agent contributions that shows the supervisor's routing reason for each step
- Answers rendered as Markdown and sanitized with DOMPurify, with code highlighting
- Stop, Clear and Copy buttons, <kbd>Ctrl</kbd> + <kbd>Enter</kbd> to run, and a light/dark theme
- A JSON API you can use without the UI
- Optional login (HTTP Basic) and a cap on concurrent runs
- Security headers on every response (a Content Security Policy that allows only the exact CDN files the page uses, `X-Frame-Options`, `nosniff`, `Cross-Origin-Opener-Policy`, `Permissions-Policy`, and HSTS over HTTPS) and limits on request size

## Quick start

**Prerequisites:** Python 3.10 or newer, and an Ollama Cloud API key. You can create a key at <https://ollama.com/settings/keys>.

```bash
git clone https://github.com/Aminul1993/Researcher.git
cd Researcher

python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.lock
```

`requirements.lock` installs the exact, hash-checked versions that CI tests. `pip install -r requirements.txt` also works and picks the newest versions within the supported ranges.

Copy the example settings file, then set `OLLAMA_API_KEY` in `.env` to your key:

```bash
# Windows
copy .env.example .env
# macOS / Linux
cp .env.example .env
```

Start the server:

```bash
python app.py
```

Then open <http://127.0.0.1:5000> and describe a task. To see a full run, click **Try an example**.

## Configuration

All settings are environment variables. The app loads them from `.env` when it starts and reads them once, so restart the server after changing them. [.env.example](.env.example) lists every variable with its default value.

### Ollama

| Variable | Default | Description |
| --- | --- | --- |
| `OLLAMA_API_KEY` | — | **Required.** Your Ollama Cloud API key. Without it, API calls return `503`. |
| `OLLAMA_HOST` | `https://ollama.com` | URL of the Ollama server. |
| `OLLAMA_MODEL` | `gpt-oss:120b` | Default model. It is used for any role that has no model of its own, and when a role's model is refused. |

### Models per role

To change the model for a role or skill, set `OLLAMA_MODEL_<ROLE>`. For example, `OLLAMA_MODEL_CODING=nemotron-3-ultra`.

| Role / skill | Variable | Default model |
| --- | --- | --- |
| Supervisor | `OLLAMA_MODEL_SUPERVISOR` | `gemma4:31b` |
| Team designer | `OLLAMA_MODEL_DESIGNER` | `gpt-oss:120b` |
| Finalizer | `OLLAMA_MODEL_FINALIZER` | `gpt-oss:120b` |
| `planning` | `OLLAMA_MODEL_PLANNING` | `nemotron-3-super` |
| `research` | `OLLAMA_MODEL_RESEARCH` | `nemotron-3-ultra` |
| `coding` | `OLLAMA_MODEL_CODING` | `gpt-oss:120b` |
| `review` | `OLLAMA_MODEL_REVIEW` | `nemotron-3-ultra` |
| `analysis` | `OLLAMA_MODEL_ANALYSIS` | `gpt-oss:120b` |
| `writing` | `OLLAMA_MODEL_WRITING` | `gemma4:31b` |
| `general` | — | `OLLAMA_MODEL` |

All of these defaults were available on the Ollama Cloud Free plan as of 2026-10-13. The supervisor and the team designer call the models through tool calling, so any model you pick for those roles must support tool calls.

You can also use a local Ollama server. Set `OLLAMA_HOST=http://localhost:11434` and set each `OLLAMA_MODEL_*` to a model you have pulled. The app still requires `OLLAMA_API_KEY` to have a value, but any placeholder other than `your-ollama-api-key` will do.

### Server

| Variable | Default | Description |
| --- | --- | --- |
| `FLASK_HOST` | `127.0.0.1` | Address the development server binds to. |
| `FLASK_PORT` | `5000` | Port of the development server. |
| `FLASK_DEBUG` | off | Set to `1`, `true` or `yes` to turn on Flask debug mode. |
| `LOG_LEVEL` | `INFO` | Python logging level. |
| `TRUSTED_PROXIES` | `0` | Number of reverse proxies in front of the app whose `X-Forwarded-*` headers to trust. See [Deployment](#deployment). |

### Login and limits

Every run spends your Ollama key, so set `APP_PASSWORD` before the server is reachable from anywhere but your own machine.

| Variable | Default | Description |
| --- | --- | --- |
| `APP_PASSWORD` | empty (login off) | When set, the page and the API require HTTP Basic login. `/api/health` and static files stay public. Use it only over HTTPS. |
| `APP_USERNAME` | `admin` | Username for the login. |
| `MAX_CONCURRENT_RUNS` | `4` | Runs allowed at the same time in each server process. Further runs get `429` with a `Retry-After` header. A run's slot is freed when it finishes or its client disconnects. |
| `RUN_TIME_BUDGET_SECONDS` | `600` | Time budget per run. Once it has passed, the supervisor stops routing and the finalizer answers with the work done so far. The agent call in progress and the finalizer still run, so a run can take somewhat longer. |

### Logs

Each run gets a 12-character run ID. Every log line written during the run carries it in brackets, and so does a line for each model call with its latency and token counts. The API returns the ID in the `X-Run-ID` response header, in the `start` stream event and in the `/api/run` result, so a failed run can be traced in the logs.

```
2026-10-16 10:12:03 INFO     agents.telemetry [3f9a1c27b0d4]: Coder call on gpt-oss:120b took 14.2s (1830 input / 912 output tokens)
2026-10-16 10:12:41 INFO     agents.runner [3f9a1c27b0d4]: Workflow finished in 52.7s: 2 agent steps, 7 model calls, 9120 input / 3302 output tokens
```

## API

Every endpoint accepts and returns JSON. Errors come back as `{"status": "error", "error": "<message>"}` with a matching HTTP status code.

### `GET /api/health`

Returns the default model and the model used by each role and skill.

```json
{ "status": "ok", "model": "gpt-oss:120b", "role_models": { "supervisor": "gemma4:31b", "coding": "gpt-oss:120b", "...": "..." } }
```

### `POST /api/run`

Runs the whole workflow and returns the result in one response.

```bash
curl -X POST http://127.0.0.1:5000/api/run \
  -H "Content-Type: application/json" \
  -d '{"task": "Compare SQLite and PostgreSQL for a small web app."}'
```

```json
{
  "status": "success",
  "task": "Compare SQLite and PostgreSQL for a small web app.",
  "run_id": "3f9a1c27b0d4",
  "team": [
    { "name": "Researcher", "role": "Summarise the strengths and limits of each database.", "skill": "research", "model": "nemotron-3-ultra" }
  ],
  "team_generated": true,
  "models": { "supervisor": "gemma4:31b", "designer": "gpt-oss:120b", "finalizer": "gpt-oss:120b" },
  "steps": [
    { "step": 1, "agent": "Researcher", "message": "…", "reason": "…", "model": "nemotron-3-ultra" }
  ],
  "final_response": "…"
}
```

### `POST /api/stream`

Takes the same request body as `/api/run`, but streams the run as Server-Sent Events while it happens:

| Event | Payload |
| --- | --- |
| `start` | `{ "task", "run_id" }` |
| `team` | `{ "agents": [{ "name", "role", "skill", "model" }], "generated", "models" }` |
| `routing` | `{ "next_agent", "reason" }`, sent each time the supervisor picks the next step |
| `step` | `{ "step", "agent", "message", "reason", "model" }`, one per agent contribution |
| `final` | `{ "message", "model" }`, the merged answer |
| `done` | `{ "status": "success" }` |
| `error` | `{ "status": "error", "error" }` |

```bash
curl -N -X POST http://127.0.0.1:5000/api/stream \
  -H "Content-Type: application/json" \
  -d '{"task": "Write a Python function that validates an IPv4 address."}'
```

While a model call is in progress the stream sends a `: keepalive` comment line every 15 seconds, so proxies don't close the connection. SSE clients ignore comment lines. If the client disconnects, the run stops once the model call in progress has finished.

### Limits and error codes

| Limit | Value |
| --- | --- |
| Task length | 4,000 characters |
| Request body | 64 KB (larger bodies return `413`) |
| Agents per team | 5 |
| Agent steps per run | 10. After the 10th reply the finalizer answers with the work done so far. |
| Time per run | `RUN_TIME_BUDGET_SECONDS` (default 600). After that the finalizer answers with the work done so far. |
| Concurrent runs | `MAX_CONCURRENT_RUNS` (default 4) per server process. Further runs return `429`. |
| Model timeout | 300 seconds without any data from the model. Replies stream in, so a long reply can take longer in total. A timeout returns `504`. |

Other status codes: `400` for an invalid request body, `401` when login is on and the credentials are missing or wrong, `429` when every run slot is busy (retry after the `Retry-After` seconds), `502` when Ollama returns an error (bad key, model not found, model not on your plan), and `503` when `OLLAMA_API_KEY` is missing.

## Using the workflow from Python

You can also use the orchestration code without the web server:

```python
from dotenv import load_dotenv
from agents.workflow import run_workflow, stream_workflow

load_dotenv()

# Generate a team and wait for the final answer
result = run_workflow("Outline a migration plan from REST to GraphQL.")
print(result["final_response"])

# Use a fixed team and handle events as they arrive
team = {
    "Coder": "Write the requested Python code.",
    "Reviewer": "Check the code for bugs and suggest fixes.",
}
for event in stream_workflow("Write a thread-safe LRU cache.", agent_registry=team):
    if event["type"] == "step":
        print(f"[{event['agent']}] {event['message'][:80]}…")
```

`run_workflow` and `stream_workflow` both accept `agent_registry` and `llm` arguments, and the keyword-only `run_id` and `time_budget` (seconds). Pass any LangChain chat model as `llm` to use that one model for every role. To see run IDs in your own logs, attach `agents.workflow.RunIdFilter` to your log handler and add `%(run_id)s` to its format. Every module logs under the `agents` logger.

Settings are read from the environment once, on first use. Call `load_dotenv()` before the first workflow call, as above, or call `agents.workflow.reload_settings()` after changing the environment. An unusable `agent_registry` (an empty team, duplicate or reserved names, or names containing `|` or `:`) raises `InvalidTeamError`, a `WorkflowError` with status `400` that is also a `ValueError`.

## Deployment

`python app.py` starts Flask's development server. In production, serve the app factory with a threaded WSGI server so that streaming responses don't block other requests:

```bash
pip install -r requirements.lock   # includes gunicorn on Linux and macOS
gunicorn --worker-class gthread --threads 8 "app:create_app()"
```

Each run holds a server thread for its whole duration, so keep `--threads` at `MAX_CONCURRENT_RUNS + 2` or more. The page and the health check then stay reachable while every run slot is busy. The cap applies per process, so with several gunicorn workers the total is `workers × MAX_CONCURRENT_RUNS`.

Set `APP_PASSWORD` and serve the app over HTTPS before exposing it: HTTP Basic sends the password with every request.

If you put a reverse proxy in front of the app, turn off response buffering for `/api/stream`. The app sends `X-Accel-Buffering: no`, which nginx respects. If the proxy terminates TLS, set `TRUSTED_PROXIES` to the number of proxies in front of the app, so the app trusts their `X-Forwarded-*` headers and sends `Strict-Transport-Security` on HTTPS requests. Leave it at `0` when clients can reach the app directly, or they could spoof those headers.

## Development

Install the pinned development tools and run the same checks as CI. The tests use a scripted fake model, so they make no network calls and need no API key:

```bash
pip install -r requirements-dev.lock
ruff check .
mypy
pytest --cov
pip-audit -r requirements.lock --require-hashes --disable-pip
```

### Dependencies

`requirements.txt` and `requirements-dev.txt` list the supported version ranges. `requirements.lock` and `requirements-dev.lock` pin every package, including indirect ones, with hashes, for all platforms and Python 3.10 and newer. After changing a range, or to pick up new releases, regenerate both locks with [uv](https://docs.astral.sh/uv/):

```bash
uv pip compile requirements.txt --universal --python-version 3.10 --generate-hashes --no-header -o requirements.lock
uv pip compile requirements-dev.txt --universal --python-version 3.10 --generate-hashes --no-header -c requirements.lock -o requirements-dev.lock
```

### Front-end libraries

Bootstrap, Bootstrap Icons, marked, DOMPurify and highlight.js load from CDNs, pinned by Subresource Integrity hashes. Their URLs and hashes live only in `CDN_STYLES` and `CDN_SCRIPTS` in [app.py](app.py): the page template and the Content Security Policy are both built from them, and the policy allows those exact files rather than whole CDN hosts. To upgrade a library, change its URL there and replace its hash with the output of:

```bash
curl -s <url> | openssl dgst -sha384 -binary | openssl base64 -A
```

## Project structure

```
Researcher/
├── app.py               # Flask app factory, routes, SSE streaming, error handling, security headers
├── agents/
│   ├── workflow.py      # Public API: re-exports the names below for `from agents.workflow import ...`
│   ├── config.py        # Settings from the environment, limits, roles, skills, default models
│   ├── errors.py        # Client-safe WorkflowError and its subclasses
│   ├── schemas.py       # Graph state, API records, structured-output schemas
│   ├── messages.py      # Reading model replies and presenting them to models
│   ├── models.py        # Ollama clients and falling back to the default model
│   ├── team.py          # Team designer and skill inference
│   ├── routing.py       # Supervisor, with the step and time budgets
│   ├── graph.py         # Agent and finalizer nodes, graph builder
│   ├── telemetry.py     # Run IDs, per-call latency and token logging
│   └── runner.py        # stream_workflow, run_workflow, error mapping
├── templates/
│   └── index.html       # Single-page UI (Bootstrap 5)
├── static/
│   ├── css/style.css
│   └── js/app.js        # Streaming client, timeline, roster, theme toggle
├── tests/               # pytest suite; fakes.py holds the offline chat model
├── .github/workflows/   # CI: ruff, mypy, pytest with coverage, pip-audit
├── .env.example         # Every setting with its default; copy to .env
├── pyproject.toml       # Tool configuration (pytest, coverage, ruff, mypy)
├── requirements.txt     # Supported version ranges
├── requirements.lock    # Exact pinned versions with hashes
├── requirements-dev.txt
├── requirements-dev.lock
└── LICENSE
```

## License

[MIT](LICENSE)
