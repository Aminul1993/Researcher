# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Developers who run Researcher themselves, on their own machine or a server they control, as a personal assistant for research, coding and writing tasks. They bring their own Groq API key, describe a task in plain language, and want both a good answer and a clear view of how the agent team reached it. They are comfortable reading logs, editing `.env`, and calling an API with `curl` or from Python.

## Product Purpose

Researcher builds a small team of AI agents for each task. A team designer reads the task and designs 2 to 5 specialist agents, each with one skill. A supervisor routes the work between them and explains each choice. A finalizer merges their contributions into one Markdown answer.

Success means the user gets a useful final answer and can see, step by step and while it happens, which agent did what and why the supervisor sent the work there. It runs cheaply enough to use on Groq's free plan.

## Positioning

Every task gets a team designed for it rather than a fixed pipeline, and each agent runs on the Groq model that suits its skill. The whole orchestration is visible live: the team, every routing decision with its reason, each agent's contribution, and where a run finished, fell back, failed or was stopped. Researcher is as much a way to watch and learn how a supervisor-routed multi-agent system behaves as it is a way to get answers.

## Operating Context

- Started with `python app.py` and used at `http://127.0.0.1:5000`, or deployed with gunicorn behind a TLS-terminating reverse proxy with `APP_PASSWORD` set.
- A run typically takes a minute or two. The page streams it over Server-Sent Events: the team roster, the live workflow graph and execution path, a timeline of agent contributions, then the final answer to copy. Streaming can be turned off for a single blocking request.
- The same workflow is used without the UI, through `POST /api/run`, `POST /api/stream`, and `run_workflow` / `stream_workflow` in Python.
- Every run uses the owner's Groq quota. Groq's per-model rate limits on the free plan are the main operational constraint, so roles are spread over several models and a refused or rate-limited model falls back to `GROQ_MODEL`.
- Failures are traced through the 12-character run ID, which appears in log lines, the `X-Run-ID` header and the stream's `start` event.

## Capabilities and Constraints

- **Workflow:** team designer, then supervisor routing to agents until it chooses `FINISH`, then finalizer. If the designer's output is unusable, a fallback team (Planner, Researcher, Coder, Reviewer) takes over.
- **Skills:** `planning`, `research`, `coding`, `review`, `analysis`, `writing`, `general`. Each maps to a configurable model (`GROQ_MODEL_<ROLE>`).
- **Budgets that guarantee an answer:** at most 10 agent steps and `RUN_TIME_BUDGET_SECONDS` (default 600) per run. When either is spent, the supervisor stops routing and the finalizer answers with the work done so far.
- **Limits:** tasks up to 4,000 characters, request bodies up to 64 KB, up to 5 agents per team, agent names up to three words, `MAX_CONCURRENT_RUNS` (default 4) per process, 300-second timeout per model reply.
- **Security:** optional HTTP Basic login (`APP_PASSWORD`), a strict Content Security Policy that allows only the exact pinned CDN files, security headers on every response, and model output rendered through DOMPurify.
- **Binding constraints, confirmed by the owner:**
  - No build step. The UI is Flask templates, plain CSS and vanilla JavaScript. Third-party files load only from pinned CDN URLs with Subresource Integrity hashes, declared once in `CDN_STYLES` / `CDN_SCRIPTS` in `app.py`, which also builds the CSP.
  - Groq is the only model provider.
  - The JSON API and Python usage stay first-class. A capability added to the UI must remain available, or be represented, through the API and the stream events.
  - The UI meets WCAG 2.2 AA (see Accessibility & Inclusion).
- **Terminology** (used consistently across UI, API, logs and README): task, run, run ID, team, team designer, agent, skill, supervisor, routing reason, step, finalizer, final answer, workflow graph, execution path, fallback team, fallback model.

## Brand Commitments

- The product name is **Researcher**.
- MIT licensed, copyright Aminul1993. Source at `https://github.com/Aminul1993/Researcher`.

## Evidence on Hand

- `README.md`: setup, configuration, API reference with example requests and responses, and log examples.
- `tests/fakes.py`: a scripted offline chat model that runs the full workflow without a Groq key, usable for demos and screenshots.
- There are no user counts, testimonials, case studies, answer-quality benchmarks, hosted demo or press. Future work must not invent any of these.

## Product Principles

1. **Show the work, deliver the answer.** The orchestration is visible and inspectable as it happens, but the merged final answer is the deliverable and stays the clear end point of every run.
2. **Every run ends with an answer or an honest reason.** Budgets and fallbacks exist so runs finish. When a limit, fallback, failure or stop shapes a run, the user can see where and why, with a recovery they can act on.
3. **Respect the owner's quota.** Runs spend the user's own Groq allowance. Show which model actually answered, keep runs bounded, and never hide retries or fallbacks.
4. **Teach through consistent language.** The same terms name the same parts of the system in the UI, API, logs and docs, so using Researcher explains how supervisor-routed agents behave.
5. **Small and self-contained.** No build step, pinned dependencies, a strict CSP, and API parity. New features fit inside those limits rather than loosening them.

## Accessibility & Inclusion

WCAG 2.2 AA is required. The existing UI already provides a skip link, a polite live status region for run progress, labelled controls, visible keyboard focus, `prefers-reduced-motion` support, and light and dark themes; future work keeps these and meets the standard in both themes. Run progress must stay perceivable without relying on animation or colour alone.
