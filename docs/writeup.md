# Engineering Writeup — AI Workflow Orchestrator

## What it is

A production-grade LLM orchestration system that automates triage of IT incidents, customer emails, and support tickets. Submit an incident log or a customer complaint via REST API; the system classifies it, generates a multi-step execution plan, runs each step using specialized tools (log analysis, email drafting, PagerDuty, Slack, database queries), and returns a structured resolution — all asynchronously across a distributed worker pool.

This isn't a demo. It's the kind of system you'd actually run in production to handle alert fatigue or first-line support at scale.

---

## Why I built it

AI agent frameworks like LangChain and AutoGen are useful for demos, but they hide the hard parts: what happens when the LLM returns garbage, when a worker crashes mid-execution, when you have 200 concurrent incidents and need to process priority-1 alerts before priority-5 ones, or when you need to audit exactly what happened on run #4823 at 03:14 UTC.

I wanted to build a system where the hard parts were visible and solved correctly. That meant owning the orchestration layer myself.

---

## Architecture

The system is built around a clean separation of concerns across three layers:

**API layer** (FastAPI) — accepts submissions, returns a `run_id` immediately (202), and exposes a Server-Sent Events stream so callers can watch execution in real time without polling.

**Worker layer** (Celery Prefork + Redis) — each run is dispatched as a priority-ordered task. Inside each worker, an `Orchestrator` drives the full lifecycle: classify → plan → execute → (optionally replan) → complete. The key insight here is that asyncio and Celery don't naturally compose — Celery workers are synchronous processes, but all the core logic is async. The bridge is `asyncio.run()`, one call per task, with careful singleton management to prevent stale event loop references across task boundaries.

**State layer** (Redis + PostgreSQL) — Redis handles the hot path: live status updates, accumulated step context (so step N can reference step N-1's output), and the SSE stream source. Postgres is the write-through store for the full audit trail: every run, step, tool call, LLM invocation, token count, and cost estimate.

---

## The interesting engineering problems

### Multi-model cost routing

Not all inference tasks are equal. Classification ("is this a log, email, or ticket?") follows a tight JSON schema with well-constrained outputs — there's no reason to pay for `gpt-4o` on that. The system routes `gpt-4o-mini` to classify, plan, replan, and fallback agents (~10x cheaper per token) and reserves `gpt-4o` for the execution agent, where multi-step tool-calling reasoning actually benefits from a stronger model. Cost is tracked per LLM call and surfaced in the `/metrics` endpoint.

### Confidence-based human escalation

The classifier emits a confidence score alongside its classification. If that score falls below a configurable threshold (default: 0.65), the run is held in `needs_review` status instead of executing automatically. An operator reviews the queue, approves the run, and it re-enters the pipeline with the confidence gate bypassed. This is the right production behavior — low-confidence automated action on a P1 incident is worse than a 30-second human review.

### Event loop management in Celery Prefork workers

This one bit me hard and is worth explaining in detail.

Celery's Prefork pool forks worker processes once at startup, then calls tasks synchronously in each process. We bridge to async via `asyncio.run()`, which creates a fresh event loop per task. The problem: any async singleton that was initialized during the *previous* task holds internal state (connection pools, transport objects) bound to the *previous* event loop. On the second task, those connections are still referencing a dead loop and raise "Future attached to a different loop."

Three separate singletons needed resetting:
- **Redis client** — `redis.asyncio` caches a connection pool per client instance
- **SQLAlchemy engine** — replaced with `NullPool` in `worker_process_init` (open/close per session); the tricky part was that `orchestrator.py` had imported `AsyncSessionFactory` by direct name at module load time, *before* the signal handler ran — so the replacement was invisible to it. Fixed by importing the module reference instead.
- **AsyncOpenAI client** — wraps `httpx.AsyncClient`, same problem

The fix for each is the same pattern: `reset_X()` clears the module-level singleton before every `asyncio.run()`, so the next call in the new event loop creates a fresh client. This is documented in the codebase with an explanation of *why*, not just the fix.

### Priority queue correctness

The API accepts `priority: 1` (urgent) through `priority: 9` (low). Celery's internal scale is inverted (0 = highest). The mapping `celery_priority = 10 - api_priority` is a one-liner but it's the kind of subtle inversion that silently breaks SLAs if you miss it — P1 incidents would process *last* without it.

---

## What I'd do next

**Dead reckoning for cost** — right now cost is estimated post-hoc from token counts. A better approach would be to estimate cost before each LLM call based on context length and refuse to proceed if projected cost exceeds a per-run budget.

**Streaming execution steps to the LLM** — currently each agent gets a static snapshot of prior step outputs. Streaming the live context window as steps complete would let the planner make better decisions without a full replan cycle.

**Vector store for incident memory** — storing completed run summaries in a vector database and retrieving similar past incidents as few-shot examples for the executor. This would dramatically improve tool argument quality on recurring incident patterns.

---

## Stack

Python 3.12 · FastAPI · Pydantic v2 · SQLAlchemy 2.x async · Alembic · Celery · Redis · PostgreSQL · OpenAI API (gpt-4o + gpt-4o-mini) · Prometheus · Grafana · Jaeger (OpenTelemetry) · Docker Compose
