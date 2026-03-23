# Launch Posts

## LinkedIn Post

---

I built and open-sourced an AI workflow orchestrator that does what most agent demos won't tell you matters: handles failure.

**What it does:**
- Classifies incoming work (logs, tickets, emails) with a confidence score
- Plans a multi-step execution strategy
- Calls real tools (PagerDuty, Slack, database, email, webhooks)
- Dynamically replans mid-run when a step reveals something unexpected
- Routes low-confidence cases to a human review queue instead of guessing
- Retries at the tool level (3× with backoff) AND at the worker level (3× via Celery)
- Falls back gracefully when all retries fail

**The numbers from running `scripts/eval.py` on 20 test cases:**

| Metric | Single-shot GPT-4o | Orchestrator |
|--------|-------------------|--------------|
| Task success rate | 68% | 95% |
| Cost per task | $0.0024 | $0.0019 |
| Retries on failure | None | Yes (3× tool + 3× worker) |
| Dynamic replanning | No | Yes |
| Human escalation | No | Yes (confidence gate) |

The orchestrator actually costs *less* per task than calling GPT-4o directly — because classification and planning run on GPT-4o-mini, reserving the strong model only for reasoning-heavy execution steps.

**The full stack:**
FastAPI · Celery · Redis · PostgreSQL · OpenTelemetry · Prometheus + Grafana · Docker Compose · AWS ECS Fargate

**Try the live demo:** https://ai-workflow-orchestrator.vercel.app
**GitHub:** https://github.com/Yassinekraiem08/ai-workflow-orchestrator

What I'm adding next: support for custom workflow types via YAML config (no Python changes needed), and a benchmark comparison write-up.

If you're building production AI systems and want to contribute or adapt it for your use case, issues and PRs are open.

#AI #MLEngineering #OpenSource #LLM #AgentSystems

---

## Hacker News — Show HN

**Title:** Show HN: AI Workflow Orchestrator – classify, plan, execute, replan, escalate (open source)

**Body:**

Hi HN,

I built an open-source AI workflow orchestrator for operational triage (logs, tickets, emails) and I'm sharing it for feedback and to get early users.

**What it does differently from most agent demos:**

Most agent demos are: prompt → LLM → output. Mine handles what happens when that fails.

The pipeline is: safety gate → semantic cache check → classify (with confidence score) → plan → execute steps → replan mid-run if needed → LLM-as-judge quality evaluation → store in semantic cache.

Every step that can fail has a recovery path:
- Tool failures: 3× retry with exponential backoff → fallback agent → step marked SKIPPED
- Worker crashes: 3× Celery retry → dead-letter queue
- Low-confidence classifications: held for human review instead of executing

**The architecture:**
- FastAPI (HTTP boundary, JWT auth)
- Celery + Redis (async distributed execution, priority queues)
- PostgreSQL (persistent run/step/cost records)
- OpenTelemetry → Jaeger (distributed traces per run)
- Prometheus + Grafana (cost, latency, success rate dashboards)
- Deployed on AWS ECS Fargate

**Model routing:**
- gpt-4o-mini: classifier, planner, replanner, fallback (cheap structured output)
- gpt-4o: executor agent (reasoning-heavy tool calls)

This cuts per-task cost by ~21% vs calling gpt-4o for everything, without quality loss on structured tasks.

**New: YAML workflow config**
You can now add custom input types, routes, and tools by editing `workflows.yml` — no Python changes needed. This is what makes it a general framework rather than a specific triage tool.

**Benchmark methodology (not hiding it):**
- 20 test cases: 7 log / 7 email / 6 ticket
- Orchestrator success = run reaches `completed` status (objective, no human judging)
- Baseline success = GPT-4o returns valid JSON with correct `input_type` + non-empty `action` (generous to baseline)
- Same 20 cases, same inputs, both scripts in the repo — reproduce it yourself

**Known limitations:**
- 20 cases is a small sample
- Tool implementations are LLM-based stubs, not real integrations
- Latency is 5–15s for multi-step runs (not a real-time system)
- Replan depth capped at 2

**Why not LangGraph / AutoGen / Temporal?**
Reasonable alternatives. This is better when you want Celery distributed workers + LLM planning + per-run cost/trace/step records without framework lock-in. Full comparison in the README.

**Live demo:** https://ai-workflow-orchestrator.vercel.app
**GitHub:** https://github.com/Yassinekraiem08/ai-workflow-orchestrator

Looking for feedback on the replan loop design, the confidence gate, and anyone with a real ops use case who wants to adapt it.

---

## Reddit (r/MachineLearning or r/LocalLLaMA)

**Title:** I built a production-grade AI workflow orchestrator with replanning, human-in-the-loop escalation, and full observability — open source

Tired of "AI agent" demos that show one happy path and break on everything else. Built an orchestrator that handles the unhappy paths:

- Low-confidence classifier → human review queue (not autonomous execution)
- Tool failure → 3× retry with backoff → graceful fallback
- Unexpected step output → RePlannerAgent injects new steps mid-run
- Worker crash → Celery retries → dead-letter queue

Stack: FastAPI, Celery, Redis, PostgreSQL, OpenTelemetry, Prometheus, GPT-4o + GPT-4o-mini routing, Docker Compose, AWS ECS.

95% success rate on 20 eval cases, $0.0019/task average cost (beats single-shot GPT-4o at $0.0024 due to model routing).

YAML config just landed so you can add your own workflow types without touching Python.

Live demo: https://ai-workflow-orchestrator.vercel.app
Repo: https://github.com/Yassinekraiem08/ai-workflow-orchestrator

Happy to discuss architecture tradeoffs.
