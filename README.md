# AI Workflow Orchestrator

A production-grade LLM orchestration system for multi-step, fault-tolerant workflows with tool execution and state tracking. Built for AI Ops use cases: automated triage of tickets, emails, and log-based incidents.

---

## Problem

Most "AI agent" projects are single-prompt pipelines with no error handling, no state, and no visibility into what happened when they fail. Real production systems need:

- **Multi-step execution** with dependencies between steps
- **Fault tolerance** — retries, fallbacks, dead-letter queues
- **Observability** — per-run traces, token usage, step-level logs
- **Async, distributed execution** that scales across workers
- **Structured agent outputs** — not fragile string parsing

This project is that system.

---

## Architecture

```
Client
  │
  ▼
FastAPI (HTTP boundary)
  │  POST /workflows/submit → returns run_id immediately (202)
  │
  ▼
Celery Task Queue (Redis broker)
  │  execute_workflow_task(run_id) → dispatched async
  │
  ▼
Orchestrator (worker process)
  ├── ClassifierAgent   → determines task_type + route
  ├── PlannerAgent      → generates ordered execution plan (3–6 steps)
  └── ExecutorAgent     → drives each step
        │
        ▼
  Tool Execution Layer
  ├── LogAnalysisTool   → parse errors, extract severity, recommend action
  ├── EmailDraftTool    → generate structured email response
  ├── WebhookTool       → send HTTP notification (PagerDuty, Slack, etc.)
  └── DatabaseQueryTool → query incident/service database
        │
        ▼
  State Layer
  ├── Redis    → live run status + accumulated context (hot path)
  └── Postgres → permanent record: runs, steps, tool calls, LLM traces
```

### Workflow lifecycle

```
PENDING → QUEUED → RUNNING → COMPLETED
                           ↘ FAILED → (retry) → DEAD_LETTER
```

---

## Key Design Decisions

| Decision | Choice | Why |
|---|---|---|
| Agent outputs | OpenAI function calling (`tool_choice: required`) | Forces structured JSON — eliminates hallucinated/malformed output |
| State store | Redis (hot) + Postgres (write-through) | Sub-ms status checks with full audit trail |
| Context passing | Shared `run_context` dict in Redis | Step N can reference any prior step's output |
| Celery ↔ async | `asyncio.run()` in task body | Keeps core logic idiomatic async |
| Retry strategy | Two levels: tool (3×, backoff) + Celery (3×, 30s) | Handles both transient tool failures and worker crashes |
| Route canonicalization | Router layer after classification | Prevents LLM from hallucinating invalid routes |

---

## Stack

- **Python 3.11+** · FastAPI · Pydantic v2 · SQLAlchemy 2.x async · Alembic
- **Celery** · **Redis** (broker + state) · **PostgreSQL** (persistence)
- **OpenAI API** (`gpt-4o`) · **Docker Compose**

---

## Project Structure

```
app/
├── main.py                   FastAPI app factory + tool registration
├── config.py                 Centralized settings (pydantic-settings)
├── api/
│   ├── routes_workflows.py   POST /submit, POST /{id}/retry
│   ├── routes_runs.py        GET /{id}, GET /{id}/steps
│   └── routes_health.py      GET /health, GET /metrics
├── core/
│   ├── orchestrator.py       Run lifecycle owner
│   ├── executor.py           Single step execution + retries
│   ├── planner.py            ExecutionPlan → DB step records
│   ├── router.py             task_type → canonical route mapping
│   └── state_manager.py      Redis + Postgres dual-store abstraction
├── agents/
│   ├── base_agent.py         Claude tool_use invocation contract
│   ├── classifier_agent.py   → ClassificationOutput
│   ├── planner_agent.py      → ExecutionPlan
│   ├── executor_agent.py     → StepExecutionOutput
│   └── fallback_agent.py     Triggered on step failure; marks step SKIPPED
├── tools/
│   ├── base.py               BaseTool, ToolResult, ToolRegistry (singleton)
│   ├── log_tool.py           Parse errors, extract severity
│   ├── email_tool.py         Generate draft email response
│   ├── webhook_tool.py       Send HTTP notification
│   └── database_tool.py      Query incident/service records
├── workers/
│   ├── celery_app.py         Celery config + queue routing
│   └── tasks.py              execute_workflow_task, dead_letter_task
├── db/
│   ├── models.py             4 ORM tables
│   ├── session.py            AsyncSession factory
│   └── schemas.py            Pydantic request/response models
├── services/
│   ├── llm_service.py        Single Anthropic gateway
│   ├── workflow_service.py   DB CRUD for runs/steps/traces
│   ├── logging_service.py    Structured JSON logging (structlog)
│   └── metrics_service.py    Aggregate metrics from DB
└── utils/
    ├── enums.py              InputType, RunStatus, StepStatus, ToolName
    ├── exceptions.py         Typed exceptions per failure mode
    └── helpers.py            generate_run_id, utcnow, ms_since
tests/                        27 tests — tools, agents, API, orchestrator
alembic/versions/             Initial schema migration
```

---

## Database Schema

```
workflow_runs          workflow_steps
─────────────          ──────────────
id (PK)                id (PK)
input_type             run_id (FK)
raw_input              step_name
status                 step_order
priority               status
created_at             input_data  (JSON)
updated_at             output_data (JSON)
final_output           error_message
                       started_at
                       completed_at

tool_calls             llm_traces
──────────             ──────────
id (PK)                id (PK)
run_id (FK)            run_id (FK)
step_id (FK)           agent_name
tool_name              prompt_summary
arguments  (JSON)      model_name
result     (JSON)      tokens_in
success                tokens_out
latency_ms             latency_ms
```

---

## API Reference

| Method | Endpoint | Description | Response |
|---|---|---|---|
| `POST` | `/workflows/submit` | Submit a triage job | `202` + `run_id` |
| `GET` | `/workflows/{run_id}` | Get run status + final output | `200` |
| `GET` | `/workflows/{run_id}/steps` | Step-by-step execution trace | `200` |
| `POST` | `/workflows/{run_id}/retry` | Requeue a failed/dead-letter run | `202` |
| `GET` | `/health` | Liveness check | `200` |
| `GET` | `/metrics` | Aggregated metrics | `200` |

### Submit a workflow

```bash
curl -X POST http://localhost:8000/workflows/submit \
  -H "Content-Type: application/json" \
  -d '{
    "input_type": "log",
    "raw_input": "2026-03-20 03:14:00 ERROR DB connection timeout\n2026-03-20 03:14:01 ERROR Retry failed after 3 attempts",
    "priority": 2
  }'
```

```json
{
  "run_id": "run_a3f9c12b8e01",
  "status": "queued",
  "input_type": "log",
  "priority": 2,
  "created_at": "2026-03-20T03:14:05Z",
  "updated_at": "2026-03-20T03:14:05Z",
  "final_output": null
}
```

### Poll status

```bash
curl http://localhost:8000/workflows/run_a3f9c12b8e01
```

### Inspect steps

```bash
curl http://localhost:8000/workflows/run_a3f9c12b8e01/steps
```

### Check metrics

```bash
curl http://localhost:8000/metrics
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

Worker crash / OOM
  └── Celery: retry 3× with 30s delay
        └── on exhaustion: dead_letter_task fires, run → DEAD_LETTER

Semantic failure (LLM returns invalid structure)
  └── BaseAgent: retry up to 2× before raising LLMResponseError
        └── FallbackAgent invoked, step → SKIPPED, run can still COMPLETE

Retry a dead-letter run
  └── POST /workflows/{run_id}/retry → requeues from scratch
```

---

## Local Setup

**Requirements:** Docker, Docker Compose, an Anthropic API key.

```bash
# 1. Clone and configure
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY

# 2. Start all services
docker-compose up --build

# 3. Run database migrations (first time only)
docker-compose exec api alembic upgrade head

# 4. Submit a test workflow
curl -X POST http://localhost:8000/workflows/submit \
  -H "Content-Type: application/json" \
  -d '{"input_type": "log", "raw_input": "ERROR: payment-api returned 502 after 3 retries"}'

# 5. Check the docs
open http://localhost:8000/docs
```

**Run tests (no Docker needed):**

```bash
pip install -r requirements.txt
pytest tests/ -v
```

---

## Tradeoffs

**Static plan vs. dynamic re-planning**
The planner generates the full execution plan before any step runs. This makes runs fully auditable and deterministic. The tradeoff is less adaptability — a step can't change the plan based on what it discovered. Dynamic re-planning is a natural Phase 2 extension.

**Redis + Postgres dual-store**
Redis handles the hot path (status checks during execution). Postgres is the source of truth for history and metrics. The tradeoff is a consistency window: if a worker crashes between writing Redis and Postgres, the states can diverge briefly. The `GET /workflows/{id}` endpoint reconciles this by syncing from Redis on read.

**`asyncio.run()` in Celery tasks**
Celery workers are synchronous by default. The bridge pattern keeps all core logic in idiomatic async Python at the cost of creating a new event loop per task. For long-running, I/O-bound workflows this overhead is negligible.

---

## Database Migrations

This project uses [Alembic](https://alembic.sqlalchemy.org/) for all schema changes. `Base.metadata.create_all()` is intentionally absent from production code; the Docker Compose setup runs migrations on API startup.

**Apply pending migrations:**
```bash
# Inside the running container
docker-compose exec api alembic upgrade head

# Or directly (with DATABASE_URL set in your environment)
alembic upgrade head
```

**Generate a new migration after changing a model:**
```bash
alembic revision --autogenerate -m "add_column_x_to_workflow_runs"
# Review the generated file in alembic/versions/ before applying
alembic upgrade head
```

**Roll back one migration:**
```bash
alembic downgrade -1
```

**Roll back to empty schema:**
```bash
alembic downgrade base
```

**Check current state:**
```bash
alembic current
alembic history --verbose
```

**Stamp an existing database** (if it was previously initialized outside Alembic):
```bash
alembic stamp head  # tells Alembic the DB is already at the latest version
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

Monitor the dead-letter queue (runs that exhausted all retries):
```bash
celery -A app.workers.celery_app inspect active_queues
```

### Redis persistence

By default Redis stores data in memory only. Enable AOF persistence for production:
```yaml
# In docker-compose.yml, update the redis service:
redis:
  image: redis:7-alpine
  command: redis-server --appendonly yes
```

### Monitoring

Poll the `/metrics` endpoint for live aggregates:
```bash
watch -n 60 'curl -s http://localhost:8000/metrics | python3 -m json.tool'
```

For structured log ingestion, the app emits JSON via `structlog` — forward to Datadog, Grafana Loki, or any log aggregator.

### Key environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | — | Anthropic Claude API key |
| `DATABASE_URL` | Yes | — | `postgresql+asyncpg://...` |
| `REDIS_URL` | Yes | — | `redis://...` |
| `APP_ENV` | No | `development` | Set to `production` in prod |
| `MAX_TOOL_RETRIES` | No | `3` | Per-step tool retry limit |
| `MAX_CELERY_RETRIES` | No | `3` | Celery task retry limit |
| `STEP_TIMEOUT_SECONDS` | No | `60` | Per-step execution timeout |

---

## Developer Guide

### Adding a new Tool

1. Create `app/tools/my_tool.py` implementing `BaseTool`:

```python
from app.tools.base import BaseTool, ToolResult
from pydantic import BaseModel

class MyToolInput(BaseModel):
    param_one: str

class MyTool(BaseTool):
    name = "my_tool"
    description = "What this tool does."
    input_schema = MyToolInput

    async def execute(self, arguments: dict) -> ToolResult:
        validated = MyToolInput(**arguments)
        return ToolResult(
            tool_name=self.name,
            success=True,
            output={"result": "..."},
            latency_ms=50,
        )
```

2. Register in `app/main.py` inside `register_tools()`:
```python
from app.tools.my_tool import MyTool
tool_registry.register(MyTool())
```

3. Add the tool name to the `ToolName` enum in `app/utils/enums.py`.

4. Map the tool to a route in `app/core/router.py` so the PlannerAgent can suggest it.

5. Write tests in `tests/test_tools.py` following the existing `TestLogAnalysisTool` pattern.

### Adding a new Agent

1. Create `app/agents/my_agent.py` extending `BaseAgent`.
2. Implement: `agent_name`, `build_system_prompt()`, `build_messages()`, `get_output_tool_definition()`, `parse_tool_call()`.
3. Define a Pydantic output model matching the tool's JSON schema.
4. Wire the agent into the relevant core module (`orchestrator.py` or `executor.py`).
5. Write tests following `TestClassifierAgent` — mock `app.agents.base_agent.llm_service.complete_with_tools`.

### Running tests

```bash
pytest tests/ -v                      # All tests
pytest tests/test_agents.py -v        # Agent unit tests
pytest tests/test_api.py -v           # API route tests
pytest tests/test_tasks.py -v         # Celery task tests
pytest tests/test_migrations.py -v    # Migration upgrade/downgrade
```

---

## Troubleshooting

**`asyncpg.exceptions.InvalidPasswordError` on startup**
The `DATABASE_URL` in `.env` doesn't match the Postgres container credentials. Default: `postgresql+asyncpg://postgres:postgres@localhost:5432/workflow_db`. Check `POSTGRES_USER` / `POSTGRES_PASSWORD` in `docker-compose.yml`.

**`celery.exceptions.OperationalError: Cannot connect to redis`**
The worker can't reach Redis. When running in Docker Compose, use the service hostname (`redis`), not `localhost`. Check `CELERY_BROKER_URL`.

**Workflow stuck in `queued` status**
The Celery worker is not running or not consuming from the `workflows` queue:
```bash
docker-compose logs worker
celery -A app.workers.celery_app inspect ping
```

**Run in `dead_letter` status**
All retries were exhausted. Resubmit via:
```bash
curl -X POST http://localhost:8000/workflows/{run_id}/retry
```
Inspect which step failed:
```bash
curl http://localhost:8000/workflows/{run_id}/steps
```

**`LLMResponseError` in logs**
The Claude API returned an `end_turn` response instead of a `tool_use` call. Common causes: context window exceeded, invalid API key, or rate limiting. The `BaseAgent` retries automatically up to 2 times. If all retries fail, the `FallbackAgent` activates and the workflow still completes with `should_escalate: true`.

**`alembic upgrade head` fails with "relation already exists"**
The database was previously initialized via `create_all` (dev mode). Stamp the current state to tell Alembic it's already up to date:
```bash
alembic stamp head
```
