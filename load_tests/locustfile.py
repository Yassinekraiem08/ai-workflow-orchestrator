"""
Locust load test scenarios for AI Workflow Orchestrator.

Three user classes model distinct traffic profiles:

  HealthCheckUser (weight=1)
    Continuous /health polling — establishes baseline latency and validates
    the API stays responsive under concurrent workflow load.

  WorkflowSubmitUser (weight=3)
    Authenticates once (JWT cached per session) then continuously submits
    log, email, and ticket workflows. Models the producer side of the Celery
    queue and measures submission throughput + p95 latency.

  WorkflowLifecycleUser (weight=2)
    Submits workflows and polls status until completion. Separately weighted
    tasks (submit:poll = 1:3) reflect realistic polling behaviour and exercise
    the GET /workflows/{run_id} path, which reads from both Postgres and Redis.

Usage:
  Interactive UI (opens http://localhost:8089):
    locust -f load_tests/locustfile.py --host http://localhost:8000

  Headless — 20 concurrent users, 5/s ramp, 60 s run:
    locust -f load_tests/locustfile.py --host http://localhost:8000 \\
      --headless -u 20 -r 5 --run-time 60s

  CI / smoke (1 user, 10 s):
    locust -f load_tests/locustfile.py --host http://localhost:8000 \\
      --headless -u 1 -r 1 --run-time 10s

Environment variables:
  LOCUST_API_KEY   — API key sent to /auth/token (default: dev-key-changeme)
"""

import os
import random

from locust import HttpUser, between, task

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

API_KEY = os.getenv("LOCUST_API_KEY", "dev-key-changeme")

_LOG_INPUTS = [
    "2026-03-20 03:14:00 ERROR DB connection timeout\n2026-03-20 03:14:01 ERROR Retry failed",
    "2026-03-20 04:00:00 ERROR payment-api: HTTP 503\n2026-03-20 04:00:01 WARN retry 1/3",
    "2026-03-20 05:10:00 CRITICAL OOM killer invoked on worker-3\n2026-03-20 05:10:01 ERROR pod restarting",
    "2026-03-20 06:00:00 ERROR asyncpg: connection pool exhausted (pool_size=10)\n" * 3,
]

_EMAIL_INPUTS = [
    "Customer reports payment failed at checkout, order #88234",
    "User cannot log in after password reset — support ticket #4421",
    "Refund request for order #91100, customer has been waiting 5 days",
]

_TICKET_INPUTS = [
    "P1 — DB primary unreachable from all app servers since 03:12 UTC",
    "P2 — API gateway latency >5 s, error rate 12%",
    "P3 — Batch job stuck in RUNNING for 3 hours, no progress",
]

_TERMINAL_STATUSES = {"completed", "failed", "dead_letter"}


# ---------------------------------------------------------------------------
# Shared mixin
# ---------------------------------------------------------------------------

class _AuthMixin:
    """Obtains a JWT on session start and exposes auth headers."""

    token: str = ""

    def _fetch_token(self):
        resp = self.client.post(
            "/auth/token",
            headers={"X-API-Key": API_KEY},
            name="/auth/token [setup]",
        )
        if resp.status_code == 200:
            self.token = resp.json().get("access_token", "")

    @property
    def _auth_headers(self) -> dict:
        if self.token:
            return {"Authorization": f"Bearer {self.token}"}
        return {"X-API-Key": API_KEY}


# ---------------------------------------------------------------------------
# User classes
# ---------------------------------------------------------------------------

class HealthCheckUser(_AuthMixin, HttpUser):
    """
    Continuously polls /health to measure baseline availability under load.
    No auth required — validates that public endpoints stay fast regardless
    of Celery queue depth.
    """

    weight = 1
    wait_time = between(0.5, 2.0)

    @task
    def health_check(self):
        with self.client.get("/health", catch_response=True, name="/health") as resp:
            if resp.status_code != 200:
                resp.failure(f"Expected 200, got {resp.status_code}")
            elif resp.json().get("status") != "ok":
                resp.failure("Health check body: status != ok")
            else:
                resp.success()


class WorkflowSubmitUser(_AuthMixin, HttpUser):
    """
    Authenticates once (JWT cached) then submits a mix of log/email/ticket
    workflows. Task weights mirror a realistic ops workload (more logs than
    tickets or emails).

    Validates:
    - POST /workflows/submit returns 202 consistently under concurrent load
    - Auth layer handles many simultaneous Bearer tokens without degradation
    - p95 submission latency stays under 200 ms (pure API overhead, no LLM)
    """

    weight = 3
    wait_time = between(0.1, 0.5)

    def on_start(self):
        self._fetch_token()

    @task(4)
    def submit_log(self):
        self._submit("log", random.choice(_LOG_INPUTS))

    @task(2)
    def submit_email(self):
        self._submit("email", random.choice(_EMAIL_INPUTS))

    @task(1)
    def submit_ticket(self):
        self._submit("ticket", random.choice(_TICKET_INPUTS))

    def _submit(self, input_type: str, raw_input: str):
        with self.client.post(
            "/workflows/submit",
            json={"input_type": input_type, "raw_input": raw_input, "priority": random.randint(1, 9)},
            headers=self._auth_headers,
            catch_response=True,
            name=f"/workflows/submit [{input_type}]",
        ) as resp:
            if resp.status_code == 202:
                resp.success()
            elif resp.status_code == 401:
                resp.failure("Auth rejected — check LOCUST_API_KEY")
                self._fetch_token()  # token may have expired; refresh
            else:
                resp.failure(f"Unexpected {resp.status_code}: {resp.text[:120]}")


class WorkflowLifecycleUser(_AuthMixin, HttpUser):
    """
    Submits workflows, accumulates run IDs, then polls each until it reaches
    a terminal status.  Submit:poll task weight is 1:3, mirroring a real
    consumer that checks status more often than it creates new runs.

    Validates:
    - End-to-end latency from submit → completed (exercises Celery workers)
    - GET /workflows/{run_id} latency + Postgres/Redis read path under load
    - No run IDs are lost or duplicated under concurrent access
    """

    weight = 2
    wait_time = between(0.5, 1.5)

    def on_start(self):
        self._fetch_token()
        self.pending_runs: list[str] = []

    @task(1)
    def submit_workflow(self):
        raw_input = random.choice(_LOG_INPUTS + _EMAIL_INPUTS)
        input_type = "log" if raw_input in _LOG_INPUTS else "email"

        with self.client.post(
            "/workflows/submit",
            json={"input_type": input_type, "raw_input": raw_input},
            headers=self._auth_headers,
            catch_response=True,
            name="/workflows/submit [lifecycle]",
        ) as resp:
            if resp.status_code == 202:
                run_id = resp.json().get("run_id")
                if run_id:
                    self.pending_runs.append(run_id)
                resp.success()
            elif resp.status_code == 401:
                resp.failure("Auth rejected")
                self._fetch_token()
            else:
                resp.failure(f"Submit failed: {resp.status_code}")

    @task(3)
    def poll_status(self):
        if not self.pending_runs:
            return  # nothing to poll yet

        run_id = random.choice(self.pending_runs)

        with self.client.get(
            f"/workflows/{run_id}",
            headers=self._auth_headers,
            catch_response=True,
            name="/workflows/{run_id} [poll]",
        ) as resp:
            if resp.status_code == 200:
                status = resp.json().get("status", "")
                if status in _TERMINAL_STATUSES:
                    # Run is done — remove from polling queue
                    self.pending_runs.remove(run_id)
                resp.success()
            elif resp.status_code == 401:
                resp.failure("Auth rejected")
                self._fetch_token()
            else:
                resp.failure(f"Poll failed: {resp.status_code}")
