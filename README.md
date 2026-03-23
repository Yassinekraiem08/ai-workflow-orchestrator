# AI Workflow Orchestrator

**Production-grade multi-agent LLM orchestration** — classify → plan → execute → replan, with retries, dead-letter queues, semantic caching, LLM-as-judge evaluation, and full observability. Built for automated triage of tickets, emails, and log-based incidents.

**[▶ Live Demo](https://ai-workflow-orchestrator.vercel.app)** · [API Docs](http://localhost:8000/docs)

---

## Quick Start

```bash
git clone https://github.com/Yassinekraiem08/ai-workflow-orchestrator.git
cd ai-workflow-orchestrator
cp .env.example .env          # add your OPENAI_API_KEY
docker compose up
```

The API is now running at `http://localhost:8000`. Submit your first workflow:

```bash
# Get a token
TOKEN=$(curl -s -X POST http://localhost:8000/auth/token \
  -H "X-API-Key: dev-key-changeme" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Submit a workflow
curl -X POST http://localhost:8000/workflows/submit \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"input_type":"log","raw_input":"ERROR: DB connection pool exhausted after 3 retries","priority":1}'
```

**Observability stack** (included):
| Service | URL |
|---------|-----|
| API + Swagger | http://localhost:8000/docs |
| Jaeger traces | http://localhost:16686 |
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3000 (admin/admin) |

---

## Problem

Most "AI agent" projects are single-prompt pipelines with no error handling, no state, and no visibility into what happened when they fail. Real production systems need:

- **Multi-step execution** with dependencies between steps
- **Fault tolerance** — retries, fallbacks, dead-letter queues
- **Observability** — per-run traces, token usage, cost tracking, distributed tracing
- **Async, distributed execution** that scales across workers
- **Structured agent outputs** — not fragile string parsing
- **Human-in-the-loop** — confidence gates for low-certainty classifications

This project is that system.

---

## Architecture

![System Architecture](docs/architecture.svg)

```
Client (Bearer JWT or X-API-Key)
  │
  ▼
FastAPI (HTTP boundary)
  │  POST /workflows/submit → returns run_id immediately (202)
  │  GET  /workflows/{id}/stream → SSE live progress feed
  │
  ▼
Celery Task Queue (Redis broker, priority-ordered)
  │  execute_workflow_task(run_id, priority=N) → dispatched async
  │
  ▼
Orchestrator (worker process)
  ├── ClassifierAgent  [gpt-4o-mini]  → task_type + confidence score
  │     └── confidence < 0.65 → NEEDS_REVIEW (held for human approval)
  ├── PlannerAgent     [gpt-4o-mini]  → ordered execution plan (3–6 steps)
  ├── RePlannerAgent   [gpt-4o-mini]  → mid-run plan adjustment if needed
  └── ExecutorAgent    [gpt-4o]       → drives each step with tool calls
        │
        ▼
  Tool Execution Layer
  ├── LogAnalysisTool      → parse errors, extract severity, recommend action
  ├── EmailDraftTool       → generate structured email response
  ├── WebhookTool          → send HTTP notification (PagerDuty, Slack, etc.)
  ├── DatabaseQueryTool    → query incident/service database
  ├── SlackNotificationTool → post to Slack channel via incoming webhook
  └── PagerDutyIncidentTool → create/acknowledge PagerDuty incidents
        │
        ▼
  State Layer
  ├── Redis    → live run status + accumulated context (hot path, SSE source)
  └── Postgres → permanent record: runs, steps, tool calls, LLM traces + cost
```

### Workflow lifecycle

```
PENDING → QUEUED → RUNNING → COMPLETED
                           ↘ FAILED → (retry up to 3×) → DEAD_LETTER
                           ↘ NEEDS_REVIEW → (human approves) → QUEUED → ...
```

---

## Key Design Decisions

| Decision | Choice | Why |
|---|---|---|
| Agent outputs | OpenAI function calling (`tool_choice: required`) | Forces structured JSON — eliminates hallucinated/malformed output |
| Multi-model routing | `gpt-4o-mini` for classify/plan, `gpt-4o` for execute | ~10× cost reduction on cheap inference; reserves strong model for reasoning-heavy steps |
| Confidence gate | Classifier confidence < 0.65 → `needs_review` | Prevents low-certainty classifications from executing autonomously |
| State store | Redis (hot) + Postgres (write-through) | Sub-ms status checks with full audit trail |
| Context passing | Shared `run_context` dict in Redis | Step N can reference any prior step's output |
| Celery ↔ async | `asyncio.run()` in task body | Keeps core logic idiomatic async; `NullPool` prevents connection exhaustion |
| Retry strategy | Tool (3×, exponential backoff) + Celery (3×, 30s) | Handles transient tool failures and full worker crashes independently |
| Priority queue | `celery_priority = 10 - api_priority` inversion | Celery's 0=highest scale vs. API's 1=highest UX convention |

---

## Stack

- **Python 3.11+** · FastAPI · Pydantic v2 · SQLAlchemy 2.x async · Alembic
- **Celery** · **Redis** (broker + state) · **PostgreSQL** (persistence)
- **OpenAI API** (`gpt-4o` + `gpt-4o-mini`) · **Docker Compose**
- **Prometheus** · **Grafana** · **Jaeger** (OpenTelemetry OTLP)

---

## Project Structure

```
app/
├── main.py                   FastAPI app factory, lifespan, tool registration
├── config.py                 Centralized settings (pydantic-settings)
├── api/
│   ├── deps.py               Auth dependency (JWT Bearer + API key)
│   ├── routes_auth.py        POST /auth/token
│   ├── routes_workflows.py   POST /submit, POST /{id}/retry, POST /{id}/approve
│   ├── routes_runs.py        GET /{id}, GET /{id}/steps, GET /{id}/stream, GET /review-queue
│   └── routes_health.py      GET /health, GET /metrics, GET /metrics/prometheus
├── core/
│   ├── orchestrator.py       Run lifecycle owner; confidence gate; cost attribution
│   ├── executor.py           Single step execution + tool retries + fallback
│   ├── planner.py            ExecutionPlan → DB step records
│   ├── router.py             task_type → canonical route mapping
│   └── state_manager.py      Redis + Postgres dual-store abstraction
├── agents/
│   ├── base_agent.py         OpenAI function-calling contract; retry loop; Prometheus instrumentation
│   ├── classifier_agent.py   → ClassificationOutput (task_type + confidence)
│   ├── planner_agent.py      → ExecutionPlan
│   ├── replanner_agent.py    → ReplanDecision (add/skip steps mid-run)
│   ├── executor_agent.py     → StepExecutionOutput
│   └── fallback_agent.py     Triggered on step failure; marks step SKIPPED + escalation flag
├── tools/
│   ├── base.py               BaseTool, ToolResult, ToolRegistry (singleton)
│   ├── log_tool.py           Parse errors, extract severity
│   ├── email_tool.py         Generate draft email response
│   ├── webhook_tool.py       Send HTTP notification
│   ├── database_tool.py      Query incident/service records
│   ├── slack_tool.py         Slack incoming webhook notifications
│   └── pagerduty_tool.py     PagerDuty incident creation/acknowledgment
├── workers/
│   ├── celery_app.py         Celery config + queue routing + worker_process_init (tools, OTel, NullPool)
│   └── tasks.py              execute_workflow_task, dead_letter_task
├── db/
│   ├── models.py             4 ORM tables
│   ├── session.py            AsyncSession factory
│   └── schemas.py            Pydantic request/response models
├── services/
│   ├── llm_service.py        OpenAI gateway — completion + tool-call + cost estimation
│   ├── prometheus_service.py Prometheus counter/histogram definitions
│   ├── telemetry_service.py  OpenTelemetry setup + span helpers
│   ├── workflow_service.py   DB CRUD for runs/steps/traces
│   ├── logging_service.py    Structured JSON logging (structlog)
│   └── metrics_service.py    Aggregate metrics from DB
└── utils/
    ├── enums.py              InputType, RunStatus, StepStatus, ToolName
    ├── exceptions.py         Typed exceptions per failure mode
    └── helpers.py            generate_run_id, utcnow, ms_since
scripts/
└── eval.py                   20-case evaluation harness (7 log / 7 email / 6 ticket)
tests/                        82 tests — tools, agents, API, orchestrator, tasks, migrations, auth
alembic/versions/             Schema migrations (initial + cost/user columns)
grafana/                      Provisioned dashboards + Prometheus datasource
```

---

## Database Schema

```
workflow_runs              workflow_steps
─────────────              ──────────────
id (PK)                    id (PK)
input_type                 run_id (FK)
raw_input                  step_name
status                     step_order
priority                   status
user_id        ← auth      input_data  (JSON)
created_at                 output_data (JSON)
updated_at                 error_message
final_output               started_at
                           completed_at

tool_calls                 llm_traces
──────────                 ──────────
id (PK)                    id (PK)
run_id (FK)                run_id (FK)
step_id (FK)               agent_name
tool_name                  model_name
arguments  (JSON)          tokens_in
result     (JSON)          tokens_out
success                    estimated_cost_usd  ← cost
latency_ms                 latency_ms
```

---

## API Reference

### Authentication

All endpoints (except `/health` and `POST /auth/token`) require one of:
- `Authorization: Bearer <jwt>` — obtain via `POST /auth/token`
- `X-API-Key: <key>` — set via the `API_KEYS` env var (comma-separated)

```bash
# Get a short-lived JWT from your API key
curl -X POST http://localhost:8000/auth/token \
  -H "X-API-Key: dev-key-changeme"
# → {"access_token": "eyJ...", "token_type": "bearer"}
```

### Endpoints

| Method | Endpoint | Description | Auth | Response |
|---|---|---|---|---|
| `POST` | `/auth/token` | Exchange API key for JWT | API key | `200` + JWT |
| `POST` | `/workflows/submit` | Submit a triage job | Required | `202` + `run_id` |
| `GET` | `/workflows/review-queue` | List runs awaiting human review | Required | `200` |
| `GET` | `/workflows/{run_id}` | Get run status + final output | Required | `200` |
| `GET` | `/workflows/{run_id}/steps` | Step-by-step execution trace | Required | `200` |
| `GET` | `/workflows/{run_id}/stream` | Live SSE progress stream | Required | `text/event-stream` |
| `POST` | `/workflows/{run_id}/retry` | Requeue a failed/dead-letter run | Required | `202` |
| `POST` | `/workflows/{run_id}/approve` | Approve a needs_review run | Required | `202` |
| `GET` | `/health` | Liveness check | None | `200` |
| `GET` | `/metrics` | Aggregated DB metrics | Required | `200` |
| `GET` | `/metrics/prometheus` | Prometheus scrape endpoint | Required | `text/plain` |

### Submit a workflow

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/auth/token \
  -H "X-API-Key: dev-key-changeme" | jq -r .access_token)

curl -X POST http://localhost:8000/workflows/submit \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "input_type": "log",
    "raw_input": "2026-03-21 03:14:00 ERROR DB connection timeout\n2026-03-21 03:14:01 ERROR Retry failed after 3 attempts",
    "priority": 2
  }'
```

```json
{
  "run_id": "run_a3f9c12b8e01",
  "status": "queued",
  "input_type": "log",
  "priority": 2,
  "user_id": "key:dev-key-ch",
  "created_at": "2026-03-21T03:14:05Z",
  "updated_at": "2026-03-21T03:14:05Z",
  "final_output": null
}
```

### Stream live progress

```bash
curl -N -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/workflows/run_a3f9c12b8e01/stream
```

```
event: connected
data: {"run_id": "run_a3f9c12b8e01"}

event: status_changed
data: {"status": "running"}

event: step_completed
data: {"step_name": "analyze_logs", "summary": "Found 2 critical errors..."}

event: step_completed
data: {"step_name": "notify_oncall", "summary": "PagerDuty incident P-12345 created"}

event: status_changed
data: {"status": "completed"}

event: done
data: {"status": "completed"}
```

### Human review flow

When the classifier's confidence score falls below the configured threshold (default: 0.65), the run is held for review instead of executing automatically:

```bash
# See what's waiting for review
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/workflows/review-queue

# Approve a run (bypasses confidence gate, re-enqueues for full execution)
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/workflows/run_a3f9c12b8e01/approve
```

### Check metrics

```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/metrics
```

```json
{
  "total_runs": 142,
  "completed_runs": 128,
  "failed_runs": 9,
  "success_rate": 0.9014,
  "avg_latency_ms": 3240.5,
  "total_tokens_in": 187430,
  "total_tokens_out": 94210,
  "total_cost_usd": 1.24,
  "failure_breakdown": {
    "by_status": {"failed": 7, "dead_letter": 2},
    "by_tool": {"webhook": 4, "database_query": 2}
  }
}
```

---

## Fault Tolerance

```
Tool failure
  └── executor.py: retry 3× with exponential backoff (1s → 2s → 4s)
        └── on exhaustion: FallbackAgent generates safe response, step → SKIPPED
              └── run can still COMPLETE if remaining steps succeed

Worker crash / OOM / timeout
  └── Celery: retry 3× with 30s delay (separate from tool retries)
        └── on exhaustion: dead_letter_task fires, run → DEAD_LETTER

LLM returns no tool call (end_turn instead of tool_use)
  └── BaseAgent: retry up to 2× before raising LLMResponseError
        └── FallbackAgent invoked, step → SKIPPED, run can still COMPLETE

Low classifier confidence
  └── run → NEEDS_REVIEW, execution halted
        └── human approves via POST /{id}/approve → re-enqueues with skip_confidence_check=True

Retry a dead-letter run
  └── POST /workflows/{run_id}/retry → resets run, requeues from scratch
```

---

## Observability

### Prometheus + Grafana

Metrics are exposed at `GET /metrics/prometheus` and scraped every 15 seconds. The provisioned Grafana dashboard (auto-loaded on startup) shows:

- Workflow submission rate by input type
- Completion rate by status
- LLM cost per hour (by model and agent)
- Token throughput (input/output)
- Workflow duration p50/p95
- LLM call rate by agent

```bash
open http://localhost:3000   # Grafana (admin/admin)
open http://localhost:9090   # Prometheus
```

### Distributed tracing (Jaeger)

Every workflow run is traced end-to-end with OpenTelemetry. The `ai-workflow-orchestrator` service emits spans for classification, planning, and each execution step.

```bash
open http://localhost:16686  # Jaeger UI
```

### Structured logs

All components emit JSON via `structlog`. Fields include `run_id`, `step_name`, `agent`, `latency_ms`, and error context. Forward to Datadog, Grafana Loki, or any log aggregator.

---

## Local Setup

**Requirements:** Docker, Docker Compose, an OpenAI API key.

```bash
# 1. Clone and configure
cp .env.example .env
# Edit .env — set OPENAI_API_KEY and API_KEYS at minimum

# 2. Start the full stack
docker-compose up --build

# 3. Run the evaluation harness (optional, requires live stack)
python scripts/eval.py
```

The API container runs `alembic upgrade head` automatically on startup — no manual migration step needed.

**Run tests (no Docker needed):**

```bash
pip install -r requirements.txt
pytest tests/ -v
# 82 tests — tools, agents, API, orchestrator, Celery tasks, migrations, auth
```

---

## Evaluation Results

Results from running `scripts/eval.py` against a local Docker Compose stack (4 Celery workers, `gpt-4o-mini` for classify/plan, `gpt-4o` for execute):

| Metric | Result |
|---|---|
| Total runs | 20 |
| Success rate | **95%** (19/20) |
| Avg latency | 6.9s |
| p95 latency | 28.3s |

| Input type | Runs | Success | Avg latency | p95 latency |
|---|---|---|---|---|
| email | 7 | **100%** | 2.9s | 2.1s |
| log | 7 | **100%** | 11.6s | 28.3s |
| ticket | 6 | **83%** | 6.1s | 2.0s |

The single ticket failure was a transient OpenAI API error on a high-priority P1 case; retry via `POST /workflows/{id}/retry` recovers it in one attempt. Email triage is fastest because it routes to the `email_draft` tool only — no `log_analysis` round-trip. Log runs are slower due to multi-step plans (classify → analyze → query DB → notify → summarize, up to 5 LLM calls at `gpt-4o`).

---

## Evaluation Harness

`scripts/eval.py` submits 20 curated inputs (7 log / 7 email / 6 ticket) against a running stack, polls each to completion, and reports:

- Overall success rate and latency (avg + p95)
- Per-type breakdown (log / email / ticket)
- Per-run status table with run IDs

```bash
# Against local Docker stack
python scripts/eval.py

# Against a different host
EVAL_HOST=http://my-host:8000 EVAL_API_KEY=my-key python scripts/eval.py

# Shorter timeout for CI
EVAL_TIMEOUT=60 python scripts/eval.py
```

---

## Tradeoffs

**Static plan vs. dynamic re-planning**
The planner generates the full execution plan before steps run, which keeps runs auditable and deterministic. The `RePlannerAgent` can adjust the plan between steps when a step's output reveals a better path, but the core sequence remains planner-driven. Fully dynamic planning (where any step can rewrite everything) would reduce predictability in a production system.

**Redis + Postgres dual-store**
Redis handles the hot path (status checks, SSE streaming context). Postgres is the source of truth for history, metrics, and cost attribution. The consistency window — if a worker crashes between writing Redis and Postgres, states can briefly diverge — is closed by the `GET /{run_id}` endpoint, which syncs from Redis on read.

**`asyncio.run()` in Celery tasks**
Celery Prefork workers are synchronous by default. Each task creates a fresh event loop via `asyncio.run()`, which means cached async clients (Redis, asyncpg) from a previous loop can't be reused. The worker uses `NullPool` for SQLAlchemy (a new connection per session) and resets the Redis client singleton before each task, eliminating the "Future attached to a different loop" class of errors entirely.

**gpt-4o-mini for cheap agents**
Classification and planning don't require heavy reasoning — they follow tight schemas with well-constrained outputs. Running those on `gpt-4o-mini` cuts per-run cost by roughly 10× compared to using `gpt-4o` everywhere, without a measurable quality drop on structured tasks.

---

## Database Migrations

This project uses [Alembic](https://alembic.sqlalchemy.org/) for all schema changes. `Base.metadata.create_all()` is intentionally absent from production code; the Docker Compose setup runs migrations on API startup.

**Apply pending migrations:**
```bash
# Inside the running container
docker-compose exec api alembic upgrade head

# Or directly (with DATABASE_URL set)
alembic upgrade head
```

**Generate a migration after changing a model:**
```bash
alembic revision --autogenerate -m "add_column_x_to_workflow_runs"
# Review the generated file in alembic/versions/ before applying
alembic upgrade head
```

**Roll back:**
```bash
alembic downgrade -1       # one step back
alembic downgrade base     # empty schema
```

**Inspect state:**
```bash
alembic current
alembic history --verbose
```

**Stamp an existing database** (if it was bootstrapped outside Alembic):
```bash
alembic stamp head
```

---

## Production Deployment

### Scaling Celery workers

Each worker handles 4 concurrent tasks (`--concurrency=4`). Scale horizontally by running additional worker containers:

```bash
celery -A app.workers.celery_app worker \
  --loglevel=info \
  -Q workflows,retries,dead_letter \
  --concurrency=8 \
  --hostname=worker2@%h
```

Monitor the dead-letter queue:
```bash
celery -A app.workers.celery_app inspect active_queues
```

### Redis persistence

Enable AOF so run state survives a Redis restart:
```yaml
# docker-compose.yml
redis:
  image: redis:7-alpine
  command: redis-server --appendonly yes
```

### Key environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENAI_API_KEY` | Yes | — | OpenAI API key |
| `DATABASE_URL` | Yes | — | `postgresql+asyncpg://...` |
| `REDIS_URL` | Yes | — | `redis://...` |
| `API_KEYS` | Yes | — | Comma-separated valid API keys |
| `JWT_SECRET` | Yes | — | Secret for signing JWTs |
| `CONFIDENCE_THRESHOLD` | No | `0.65` | Below this score, runs go to needs_review |
| `LLM_MODEL_FAST` | No | `gpt-4o-mini` | Model for classify/plan/replan/fallback |
| `LLM_MODEL_STRONG` | No | `gpt-4o` | Model for execution steps |
| `APP_ENV` | No | `development` | Set to `production` in prod |
| `MAX_TOOL_RETRIES` | No | `3` | Per-step tool retry limit |
| `MAX_CELERY_RETRIES` | No | `3` | Celery task retry limit |
| `STEP_TIMEOUT_SECONDS` | No | `60` | Per-step execution timeout |
| `OTEL_ENABLED` | No | `false` | Enable OpenTelemetry tracing |
| `OTLP_ENDPOINT` | No | — | OTLP HTTP collector (e.g. Jaeger) |

---

## Developer Guide

### Adding a new Tool

1. Create `app/tools/my_tool.py` implementing `BaseTool`:

```python
from app.tools.base import BaseTool, ToolResult
from pydantic import BaseModel


class MyToolInput(BaseModel):
    target: str
    message: str


class MyTool(BaseTool):
    name = "my_tool"
    description = "Send a message to a target system."
    input_schema = MyToolInput

    async def execute(self, arguments: dict) -> ToolResult:
        validated = MyToolInput(**arguments)
        # ... do the work
        return ToolResult(
            tool_name=self.name,
            success=True,
            output={"sent": True, "target": validated.target},
            latency_ms=50,
        )
```

2. Register in `app/main.py` inside `register_tools()` and mirror the registration in `app/workers/celery_app.py` inside `on_worker_process_init`.

3. Add the tool name to `ToolName` in `app/utils/enums.py`.

4. Map the tool to a route in `app/core/router.py` so the PlannerAgent can suggest it.

5. Write tests in `tests/test_tools.py` following the `TestLogAnalysisTool` pattern.

### Adding a new Agent

1. Create `app/agents/my_agent.py` extending `BaseAgent`.
2. Implement: `agent_name`, `model` (property), `build_system_prompt()`, `build_messages()`, `get_output_tool_definition()`, `parse_tool_call()`.
3. Define a Pydantic output model matching the tool's JSON schema — Pydantic validates every response automatically.
4. Wire the agent into `orchestrator.py` or `executor.py`.
5. Write tests following `TestClassifierAgent` — mock `app.agents.base_agent.llm_service.complete_with_tools`.

### Running tests

```bash
pytest tests/ -v                       # All 82 tests
pytest tests/test_agents.py -v         # Agent unit tests + failure injection
pytest tests/test_api.py -v            # API route tests + metrics
pytest tests/test_tasks.py -v          # Celery retry/dead-letter logic
pytest tests/test_migrations.py -v     # Alembic upgrade/downgrade on SQLite
pytest tests/test_auth.py -v           # JWT + API key auth
pytest tests/test_replanner.py -v      # Re-planning mid-run
pytest tests/test_telemetry.py -v      # OTel span helpers
```

---

## Troubleshooting

**`asyncpg.exceptions.InvalidPasswordError` on startup**
The `DATABASE_URL` credentials don't match the Postgres container. Default: `postgresql+asyncpg://postgres:postgres@localhost:5433/workflow_db`. Check `POSTGRES_USER` and `POSTGRES_PASSWORD` in `docker-compose.yml`.

**`celery.exceptions.OperationalError: Cannot connect to redis`**
Inside Docker Compose, use the service hostname (`redis`), not `localhost`. Check `CELERY_BROKER_URL`.

**Workflow stuck in `queued` status**
The Celery worker isn't running or isn't consuming from the `workflows` queue:
```bash
docker-compose logs worker
celery -A app.workers.celery_app inspect ping
```

**Run stuck in `needs_review` status**
The classifier confidence was below the threshold. Either approve it via the API or lower `CONFIDENCE_THRESHOLD` in `.env`.

**Run in `dead_letter` status**
All 3 Celery retries were exhausted. Inspect which step failed, then resubmit:
```bash
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/workflows/{run_id}/steps
curl -X POST -H "Authorization: Bearer $TOKEN" http://localhost:8000/workflows/{run_id}/retry
```

**`LLMResponseError` in logs**
The OpenAI API returned `end_turn` instead of a `tool_use` call. Common causes: context window exceeded, rate limiting, or invalid API key. `BaseAgent` retries automatically up to 2 times; if all retries fail, `FallbackAgent` activates and the step is marked `SKIPPED` with `should_escalate: true`.

**`alembic upgrade head` fails with "relation already exists"**
The database was bootstrapped outside Alembic (e.g., via `create_all` in dev). Tell Alembic the DB is already current:
```bash
alembic stamp head
```

**Grafana shows "No data"**
Prometheus hasn't scraped any metrics yet. Submit a few workflows and wait ~30 seconds. Verify the scrape target is up at `http://localhost:9090/targets`.
