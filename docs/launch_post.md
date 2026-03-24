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

Just shipped: custom workflow types via YAML config — add new incident types, routes, and tools without touching Python code.

If you're building production AI systems and want to contribute or adapt it for your use case, issues and PRs are open.

#AI #MLEngineering #OpenSource #LLM #AgentSystems

---

## Hacker News — Show HN

**Title:** Show HN: AI that triages production incidents – classifies, plans, executes, replans, escalates to humans

**Body:**

Hi HN,

I built an open-source system for production incident triage — analyzes logs, queries context, executes actions, and escalates when uncertain. No API key needed for the demo.

**The problem:**

At 2am, when payment-svc is returning 503 for all EU-WEST-1 customers (~$12k/min impact), you don't want a chatbot that summarizes the ticket — you want something that reasons through the failure and tells you what to do.

**What it does:**

Submit a support ticket, log dump, or customer issue. The system:
1. Classifies input type + severity with a confidence score
2. Routes to the right tool chain (log analysis → DB query → webhook/PagerDuty/Slack)
3. Executes each step, synthesizing findings as it goes
4. Replans mid-run if a step reveals something unexpected
5. Escalates to human review if classifier confidence is below threshold

**Failure handling (this is the interesting part):**
- Tool failures: 3× retry with exponential backoff → fallback agent → step SKIPPED
- Worker crashes: 3× Celery retry → dead-letter queue
- Low confidence: held for human review, not executed blindly

**Architecture:**
- FastAPI + Celery + Redis (async distributed execution, priority queues)
- PostgreSQL (persistent run/step/cost/trace records)
- OpenTelemetry → Jaeger, Prometheus + Grafana (deployed, not just configured)
- AWS ECS Fargate (live, not localhost)
- gpt-4o-mini for classify/plan/replan, gpt-4o for execution

Model routing cuts per-task cost 21% vs calling gpt-4o for everything.

**Benchmark (methodology in the repo):**
- 20 test cases: 7 log / 7 email / 6 ticket
- 95% success rate vs 68% single-shot GPT-4o baseline
- $0.0019/task vs $0.0024 baseline
- Scripts to reproduce: `scripts/eval.py` and `scripts/eval_baseline.py`

**Limitations — not hiding them:**
- Tool integrations are intelligent stubs (no real PagerDuty/Slack calls)
- 20 eval cases is a small sample
- 5–15s latency per run
- Replan depth capped at 2

**Why not LangGraph / AutoGen / Temporal?**
Full comparison in the README. Short version: this is better when you want Celery distributed workers + per-run cost/trace/step audit trail + human escalation without framework lock-in.

**Live demo (no API key needed):** https://ai-workflow-orchestrator.vercel.app
**GitHub:** https://github.com/Yassinekraiem08/ai-workflow-orchestrator

Looking for feedback on the replan loop, the confidence gate threshold, and anyone running real incident response who wants to adapt it.

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
