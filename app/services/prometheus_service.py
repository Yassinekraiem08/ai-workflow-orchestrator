"""
Prometheus metrics for the AI Workflow Orchestrator.

All counters and histograms are defined here and imported where needed.
Note: in a multi-process Celery deployment, these metrics only reflect
the API process (submissions, HTTP layer). End-to-end accuracy is provided
by the DB-backed GET /metrics endpoint. For full multi-process Prometheus
support, set PROMETHEUS_MULTIPROC_DIR and use prometheus_client multiprocess mode.
"""

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Histogram,
    generate_latest,
)

__all__ = [
    "CONTENT_TYPE_LATEST",
    "generate_latest",
    "WORKFLOW_SUBMISSIONS",
    "WORKFLOW_COMPLETIONS",
    "LLM_CALLS",
    "LLM_COST_USD",
    "LLM_TOKENS",
    "WORKFLOW_DURATION",
]

WORKFLOW_SUBMISSIONS = Counter(
    "workflow_submissions_total",
    "Total workflow submissions by input type",
    ["input_type"],
)

WORKFLOW_COMPLETIONS = Counter(
    "workflow_completions_total",
    "Total workflow terminal transitions by final status",
    ["input_type", "status"],
)

LLM_CALLS = Counter(
    "llm_calls_total",
    "Total LLM API calls by model and agent",
    ["model", "agent"],
)

LLM_COST_USD = Counter(
    "llm_cost_usd_total",
    "Cumulative LLM cost in USD by model and agent",
    ["model", "agent"],
)

LLM_TOKENS = Counter(
    "llm_tokens_total",
    "Total LLM tokens by model, agent, and direction (in/out)",
    ["model", "agent", "direction"],
)

WORKFLOW_DURATION = Histogram(
    "workflow_duration_seconds",
    "End-to-end workflow execution time in seconds",
    ["input_type"],
    buckets=[5, 10, 20, 30, 45, 60, 90, 120, 180, 300],
)
