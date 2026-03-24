"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { EXAMPLES } from "@/lib/examples";
import type {
  InputType,
  RunStatus,
  WorkflowRun,
  WorkflowStep,
  Metrics,
  SubmitPayload,
} from "@/lib/types";

const POLL_INTERVAL_MS = 2000;
const MAX_POLL_MS = 120_000;

const TERMINAL: Set<RunStatus> = new Set([
  "completed",
  "failed",
  "dead_letter",
  "needs_review",
]);

const STATUS_COLOR: Record<RunStatus, string> = {
  pending:      "text-gray-400",
  queued:       "text-yellow-400",
  running:      "text-blue-400",
  completed:    "text-emerald-400",
  failed:       "text-red-400",
  dead_letter:  "text-red-500",
  needs_review: "text-orange-400",
};

const STEP_COLOR: Record<string, string> = {
  pending:   "bg-gray-700 text-gray-300",
  running:   "bg-blue-900 text-blue-200",
  completed: "bg-emerald-900 text-emerald-200",
  failed:    "bg-red-900 text-red-200",
  skipped:   "bg-yellow-900 text-yellow-200",
};

const TYPE_LABEL: Record<InputType, string> = {
  ticket: "Support Ticket",
  email:  "Customer Email",
  log:    "System Log",
};

const STACK = [
  "FastAPI", "Celery", "Redis", "PostgreSQL",
  "GPT-4o", "GPT-4o-mini", "OpenTelemetry", "AWS ECS",
];

// ── MetricsBar ────────────────────────────────────────────────────────────────

function MetricsBar({ metrics }: { metrics: Metrics | null }) {
  if (!metrics) {
    return (
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[...Array(4)].map((_, i) => (
          <div key={i} className="h-16 bg-gray-800 rounded-lg animate-pulse" />
        ))}
      </div>
    );
  }

  const stats = [
    { label: "Total Runs",   value: metrics.total_runs.toLocaleString() },
    { label: "Success Rate", value: `${(metrics.success_rate * 100).toFixed(1)}%` },
    { label: "Avg Latency",  value: `${(metrics.avg_latency_ms / 1000).toFixed(1)}s` },
    { label: "Total Cost",   value: `$${metrics.total_cost_usd.toFixed(2)}` },
  ];

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-center">
      {stats.map((s) => (
        <div
          key={s.label}
          className="bg-gray-800/60 border border-gray-700 rounded-lg p-3"
        >
          <div className="text-xl font-bold text-indigo-400">{s.value}</div>
          <div className="text-xs text-gray-500 mt-0.5">{s.label}</div>
        </div>
      ))}
    </div>
  );
}

const SEVERITY_COLOR: Record<string, string> = {
  critical: "bg-red-900/60 text-red-300 border-red-700/50",
  high:     "bg-orange-900/60 text-orange-300 border-orange-700/50",
  medium:   "bg-yellow-900/60 text-yellow-300 border-yellow-700/50",
  low:      "bg-gray-800 text-gray-400 border-gray-700",
};

function formatDuration(ms: number): string {
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  return `${ms}ms`;
}

// ── StepCard ──────────────────────────────────────────────────────────────────

function StepCard({ step, index }: { step: WorkflowStep; index: number }) {
  const [expanded, setExpanded] = useState(false);
  const [showRaw, setShowRaw] = useState(false);
  const cls = STEP_COLOR[step.status] ?? "bg-gray-700 text-gray-300";
  const o = step.output_data as Record<string, unknown> | null;
  const hasOutput = o && Object.keys(o).length > 0;
  const isFallback = !!o?.["_fallback_used"];

  let durationMs: number | null = null;
  if (step.started_at && step.completed_at) {
    durationMs =
      new Date(step.completed_at).getTime() -
      new Date(step.started_at).getTime();
  }

  return (
    <div className="border border-gray-700 rounded-lg overflow-hidden animate-fade-in">
      <button
        type="button"
        disabled={!hasOutput}
        onClick={() => setExpanded((e) => !e)}
        className="w-full flex items-center gap-3 p-3 hover:bg-gray-800/40 transition-colors text-left disabled:cursor-default"
      >
        <span className="w-5 h-5 rounded-full bg-gray-700 text-xs flex items-center justify-center text-gray-400 font-mono flex-shrink-0">
          {index + 1}
        </span>
        <span className="flex-1 text-sm font-medium text-gray-200">
          {step.step_name.replace(/_/g, " ")}
        </span>
        {durationMs !== null && (
          <span className="text-xs text-gray-600 mr-1">{formatDuration(durationMs)}</span>
        )}
        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${cls}`}>
          {step.status}
        </span>
        {hasOutput && (
          <svg
            className={`w-4 h-4 text-gray-600 transition-transform flex-shrink-0 ${
              expanded ? "rotate-180" : ""
            }`}
            fill="none" stroke="currentColor" viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        )}
      </button>

      {expanded && hasOutput && (
        <div className="px-4 pb-4 bg-gray-900/60 border-t border-gray-700 space-y-3 pt-3">
          {isFallback ? (
            // Fallback / skipped step view
            <div className="space-y-2">
              <p className="text-xs text-yellow-400 font-medium">Step failed — fallback response generated</p>
              {!!o?.["safe_response"] && (
                <p className="text-sm text-gray-300">{String(o["safe_response"])}</p>
              )}
              {Array.isArray(o?.["recommended_next_steps"]) && (o["recommended_next_steps"] as string[]).length > 0 && (
                <div>
                  <p className="text-xs text-gray-500 mb-1">Recommended next steps:</p>
                  <ul className="space-y-0.5">
                    {(o["recommended_next_steps"] as string[]).map((s, i) => (
                      <li key={i} className="text-xs text-gray-400 flex gap-1.5">
                        <span className="text-gray-600 flex-shrink-0">›</span>{s}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          ) : (
            // Normal completed step view
            <div className="space-y-3">
              {!!o?.["severity"] && (
                <span className={`inline-block text-xs px-2 py-0.5 rounded-full border font-medium ${
                  SEVERITY_COLOR[String(o["severity"]).toLowerCase()] ?? SEVERITY_COLOR.low
                }`}>
                  {String(o["severity"]).toUpperCase()}
                </span>
              )}
              {!!o?.["summary"] && (
                <p className="text-sm text-gray-200 leading-relaxed">{String(o["summary"])}</p>
              )}
              {Array.isArray(o?.["key_findings"]) && (o["key_findings"] as string[]).length > 0 && (
                <div>
                  <p className="text-xs text-gray-500 mb-1.5">Key findings:</p>
                  <ul className="space-y-1">
                    {(o["key_findings"] as string[]).map((f, i) => (
                      <li key={i} className="text-xs text-gray-300 flex gap-2">
                        <span className="text-indigo-500 flex-shrink-0">•</span>{f}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {!!o?.["next_action"] && (
                <div className="bg-gray-800/60 rounded-lg px-3 py-2">
                  <p className="text-xs text-gray-500 mb-0.5">Next action</p>
                  <p className="text-xs text-gray-300">{String(o["next_action"])}</p>
                </div>
              )}
            </div>
          )}
          <button
            type="button"
            onClick={(e) => { e.stopPropagation(); setShowRaw((r) => !r); }}
            className="text-xs text-gray-600 hover:text-gray-400 transition-colors"
          >
            {showRaw ? "Hide raw JSON" : "Show raw JSON"}
          </button>
          {showRaw && (
            <pre className="text-xs text-gray-500 overflow-x-auto leading-relaxed border border-gray-800 rounded p-2">
              {JSON.stringify(o, null, 2)}
            </pre>
          )}
        </div>
      )}

      {step.error_message && (
        <div className="px-4 pb-3 pt-1 text-xs text-red-400 border-t border-red-900/40">
          {step.error_message}
        </div>
      )}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function HomePage() {
  const [exampleIdx, setExampleIdx]   = useState(0);
  const [inputType, setInputType]     = useState<InputType>(EXAMPLES[0].input_type);
  const [rawInput, setRawInput]       = useState(EXAMPLES[0].raw_input);
  const [priority, setPriority]       = useState(EXAMPLES[0].priority);
  const [customMode, setCustomMode]   = useState(false);

  const [openaiKey, setOpenaiKey]     = useState("");
  const [submitting, setSubmitting]   = useState(false);
  const [runId, setRunId]             = useState<string | null>(null);
  const [run, setRun]                 = useState<WorkflowRun | null>(null);
  const [steps, setSteps]             = useState<WorkflowStep[]>([]);
  const [error, setError]             = useState<string | null>(null);
  const [elapsed, setElapsed]         = useState(0);
  const [metrics, setMetrics]         = useState<Metrics | null>(null);

  const pollRef    = useRef<ReturnType<typeof setInterval> | null>(null);
  const tickRef    = useRef<ReturnType<typeof setInterval> | null>(null);
  const startedRef = useRef(0);

  useEffect(() => {
    fetch("/api/metrics")
      .then((r) => r.ok ? r.json() : null)
      .then((d) => d && setMetrics(d))
      .catch(() => {});
  }, []);

  const stopPolling = useCallback(() => {
    if (pollRef.current) clearInterval(pollRef.current);
    if (tickRef.current) clearInterval(tickRef.current);
    pollRef.current = tickRef.current = null;
  }, []);

  useEffect(() => () => stopPolling(), [stopPolling]);

  const refreshMetrics = useCallback(() => {
    fetch("/api/metrics")
      .then((r) => r.ok ? r.json() : null)
      .then((d) => d && setMetrics(d))
      .catch(() => {});
  }, []);

  const startPolling = useCallback(
    (id: string) => {
      startedRef.current = Date.now();

      tickRef.current = setInterval(() => {
        setElapsed(Math.floor((Date.now() - startedRef.current) / 1000));
      }, 1000);

      pollRef.current = setInterval(async () => {
        if (Date.now() - startedRef.current > MAX_POLL_MS) {
          stopPolling();
          setError("Timed out after 120 seconds.");
          return;
        }
        try {
          const [sRes, stRes] = await Promise.all([
            fetch(`/api/status/${id}`, { cache: "no-store" }),
            fetch(`/api/steps/${id}`,  { cache: "no-store" }),
          ]);
          if (sRes.ok) {
            const r: WorkflowRun = await sRes.json();
            setRun(r);
            if (TERMINAL.has(r.status)) {
              stopPolling();
              if (r.status === "completed") refreshMetrics();
            }
          }
          if (stRes.ok) {
            const d = await stRes.json();
            setSteps(d.steps ?? []);
          }
        } catch {/* network glitch — next poll will retry */}
      }, POLL_INTERVAL_MS);
    },
    [stopPolling, refreshMetrics]
  );

  function applyExample(idx: number) {
    const ex = EXAMPLES[idx];
    setExampleIdx(idx);
    setInputType(ex.input_type);
    setRawInput(ex.raw_input);
    setPriority(ex.priority);
    setCustomMode(false);
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (submitting) return;

    stopPolling();
    setError(null);
    setRun(null);
    setSteps([]);
    setRunId(null);
    setElapsed(0);
    setSubmitting(true);

    const payload = { input_type: inputType, raw_input: rawInput, priority, ...(openaiKey.trim() && { openai_api_key: openaiKey.trim() }) };

    try {
      const res = await fetch("/api/submit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();

      if (!res.ok) {
        setError(data.detail ?? data.error ?? "Submission failed.");
        return;
      }

      setRunId(data.run_id);
      setRun(data);
      startPolling(data.run_id);
    } catch {
      setError("Network error — could not reach the demo server.");
    } finally {
      setSubmitting(false);
    }
  }

  const isTerminal = run ? TERMINAL.has(run.status) : false;

  return (
    <main className="max-w-4xl mx-auto px-4 py-10 space-y-10">

      {/* Header */}
      <header className="space-y-4">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-indigo-600 flex items-center justify-center text-white font-bold text-sm">
            AI
          </div>
          <div>
            <h1 className="text-2xl font-bold text-gray-100 leading-none">
              AI Workflow Orchestrator
            </h1>
            <p className="text-xs text-gray-500 mt-0.5">Live Demo</p>
          </div>
          <a
            href="https://github.com/Yassinekraiem08/ai-workflow-orchestrator"
            target="_blank"
            rel="noopener noreferrer"
            className="ml-auto text-xs text-gray-500 hover:text-gray-300 transition-colors border border-gray-700 px-3 py-1.5 rounded-lg"
          >
            View on GitHub
          </a>
        </div>

        <p className="text-sm text-gray-400 leading-relaxed max-w-2xl">
          Production-grade LLM orchestration for automated triage — multi-step execution,
          fault tolerance, cost tracking, and full observability. Submit a workflow and
          watch the orchestrator classify, plan, and execute in real time.
        </p>

        <div className="flex flex-wrap gap-1.5">
          {STACK.map((t) => (
            <span
              key={t}
              className="text-xs bg-gray-800/80 border border-gray-700 text-gray-400 px-2 py-0.5 rounded-full"
            >
              {t}
            </span>
          ))}
        </div>
      </header>

      {/* Metrics */}
      <section>
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">
          Live System Metrics
        </h2>
        <MetricsBar metrics={metrics} />
      </section>

      {/* Form */}
      <section>
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-4">
          Submit a Workflow
        </h2>

        <form onSubmit={handleSubmit} className="space-y-5">
          {/* Example buttons */}
          <div>
            <p className="text-xs text-gray-500 mb-2">Choose an example or write your own:</p>
            <div className="flex flex-wrap gap-2">
              {EXAMPLES.map((ex, i) => (
                <button
                  key={i}
                  type="button"
                  onClick={() => applyExample(i)}
                  className={`text-sm px-3 py-1.5 rounded-lg border transition-colors ${
                    !customMode && exampleIdx === i
                      ? "bg-indigo-600 border-indigo-500 text-white"
                      : "bg-gray-800 border-gray-700 text-gray-300 hover:border-gray-500"
                  }`}
                >
                  {ex.label}
                </button>
              ))}
              <button
                type="button"
                onClick={() => setCustomMode(true)}
                className={`text-sm px-3 py-1.5 rounded-lg border transition-colors ${
                  customMode
                    ? "bg-indigo-600 border-indigo-500 text-white"
                    : "bg-gray-800 border-gray-700 text-gray-300 hover:border-gray-500"
                }`}
              >
                Custom
              </button>
            </div>
          </div>

          {/* Type + Priority */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs text-gray-400 mb-1.5" htmlFor="input-type">
                Input Type
              </label>
              <select
                id="input-type"
                value={inputType}
                onChange={(e) => {
                  setInputType(e.target.value as InputType);
                  setCustomMode(true);
                }}
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-indigo-500"
              >
                <option value="ticket">Support Ticket</option>
                <option value="email">Customer Email</option>
                <option value="log">System Log</option>
              </select>
            </div>
            <div>
              <label className="block text-xs text-gray-400 mb-1.5" htmlFor="priority">
                Priority <span className="text-gray-600">(1 = highest)</span>
              </label>
              <input
                id="priority"
                type="number"
                min={1}
                max={10}
                value={priority}
                onChange={(e) => {
                  setPriority(Number(e.target.value));
                  setCustomMode(true);
                }}
                className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-indigo-500"
              />
            </div>
          </div>

          {/* Textarea */}
          <div>
            <label className="block text-xs text-gray-400 mb-1.5" htmlFor="raw-input">
              Raw Input
            </label>
            <textarea
              id="raw-input"
              rows={8}
              value={rawInput}
              onChange={(e) => {
                setRawInput(e.target.value);
                setCustomMode(true);
              }}
              placeholder="Paste a ticket, email, or log snippet…"
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2.5 text-sm text-gray-200 font-mono leading-relaxed resize-y focus:outline-none focus:border-indigo-500 placeholder-gray-600"
            />
          </div>

          <div className="border border-gray-700 rounded-lg p-4 space-y-2 bg-gray-800/30">
            <label className="block text-xs text-gray-400" htmlFor="openai-key">
              OpenAI API Key <span className="text-gray-600">(optional — use your own key)</span>
            </label>
            <input
              id="openai-key"
              type="password"
              value={openaiKey}
              onChange={(e) => setOpenaiKey(e.target.value)}
              placeholder="sk-... (leave empty to use the shared demo key)"
              className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-200 font-mono focus:outline-none focus:border-indigo-500 placeholder-gray-600"
            />
            <p className="text-xs text-gray-600">Your key is never stored — it&apos;s used only for this run and discarded immediately.</p>
          </div>

          <button
            type="submit"
            disabled={submitting || rawInput.trim().length === 0}
            className="px-6 py-2.5 bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold rounded-lg transition-colors text-sm"
          >
            {submitting ? "Submitting…" : "Run Workflow"}
          </button>

          {error && (
            <p className="text-sm text-red-400 bg-red-950/40 border border-red-800 rounded-lg px-4 py-2">
              {error}
            </p>
          )}
        </form>
      </section>

      {/* Live Tracker */}
      {runId && (
        <section className="space-y-5 animate-fade-in">
          <div className="flex items-center justify-between">
            <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
              Live Execution
            </h2>
            {!isTerminal && (
              <span className="text-xs text-gray-600 font-mono">{elapsed}s elapsed</span>
            )}
          </div>

          {/* Run card */}
          {run && (
            <div className="bg-gray-800/50 border border-gray-700 rounded-xl p-4 space-y-1.5">
              <div className="flex items-center justify-between">
                <span className="font-mono text-xs text-gray-500">{run.run_id}</span>
                <span className={`font-semibold text-sm ${STATUS_COLOR[run.status]}`}>
                  {!isTerminal && (
                    <span className="inline-block w-2 h-2 rounded-full bg-current mr-1.5 animate-pulse" />
                  )}
                  {run.status.replace(/_/g, " ")}
                </span>
              </div>
              <div className="text-xs text-gray-500">
                {TYPE_LABEL[run.input_type]} · Priority {run.priority}
              </div>
            </div>
          )}

          {/* Spinner while waiting for plan */}
          {steps.length === 0 && !isTerminal && (
            <div className="flex items-center gap-2 text-sm text-gray-500">
              <svg
                className="w-4 h-4 animate-spin text-indigo-500"
                fill="none"
                viewBox="0 0 24 24"
              >
                <circle
                  className="opacity-25"
                  cx="12"
                  cy="12"
                  r="10"
                  stroke="currentColor"
                  strokeWidth="4"
                />
                <path
                  className="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                />
              </svg>
              Waiting for execution plan…
            </div>
          )}

          {/* Steps */}
          {steps.length > 0 && (
            <div className="space-y-2">
              <p className="text-xs text-gray-500">
                {steps.length} step{steps.length !== 1 ? "s" : ""} — click any completed step to see output
              </p>
              {steps.map((s, i) => (
                <StepCard key={s.step_id} step={s} index={i} />
              ))}
            </div>
          )}

          {/* ML feature badges */}
          {run && isTerminal && (
            <div className="flex flex-wrap gap-2 animate-fade-in">
              {run.cache_hit && (
                <span className="text-xs px-3 py-1 rounded-full bg-cyan-900/50 border border-cyan-700/60 text-cyan-300 font-medium">
                  ⚡ Served from semantic cache
                </span>
              )}
              {run.safety_flagged && (
                <span className="text-xs px-3 py-1 rounded-full bg-red-900/50 border border-red-700/60 text-red-300 font-medium">
                  🛡 Blocked by safety filter
                </span>
              )}
              {run.quality_score !== null && run.quality_score !== undefined && (
                <span className={`text-xs px-3 py-1 rounded-full border font-medium ${
                  run.quality_score >= 0.7
                    ? "bg-emerald-900/50 border-emerald-700/60 text-emerald-300"
                    : run.quality_score >= 0.4
                    ? "bg-yellow-900/50 border-yellow-700/60 text-yellow-300"
                    : "bg-red-900/50 border-red-700/60 text-red-300"
                }`}>
                  🧑‍⚖️ Quality score: {(run.quality_score * 100).toFixed(0)}%
                </span>
              )}
              {run.quality_breakdown && (
                <details className="w-full mt-1">
                  <summary className="text-xs text-gray-500 cursor-pointer hover:text-gray-300 transition-colors">
                    View quality breakdown
                  </summary>
                  <div className="mt-2 grid grid-cols-2 sm:grid-cols-5 gap-2">
                    {Object.entries(run.quality_breakdown).map(([dim, score]) => (
                      <div key={dim} className="bg-gray-800/60 border border-gray-700 rounded-lg p-2 text-center">
                        <div className="text-sm font-bold text-indigo-400">{((score as number) * 100).toFixed(0)}%</div>
                        <div className="text-xs text-gray-500 mt-0.5 capitalize">{dim}</div>
                      </div>
                    ))}
                  </div>
                </details>
              )}
            </div>
          )}

          {/* Final output */}
          {run?.final_output && (
            <div className="animate-fade-in">
              <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">
                Final Output
              </h3>
              <div className="bg-gray-900 border border-emerald-800/40 rounded-xl p-5 space-y-3">
                {run.final_output.split(/\n\n+/).map((chunk, i) => {
                  const match = chunk.match(/^\[(.+?)\]\s*([\s\S]+)$/);
                  if (match) {
                    return (
                      <div key={i}>
                        <p className="text-xs text-indigo-400 font-medium mb-1">{match[1]}</p>
                        <p className="text-sm text-gray-200 leading-relaxed">{match[2].trim()}</p>
                      </div>
                    );
                  }
                  return (
                    <p key={i} className="text-sm text-gray-200 leading-relaxed">{chunk.trim()}</p>
                  );
                })}
              </div>
            </div>
          )}

          {/* Needs review */}
          {run?.status === "needs_review" && (
            <div className="bg-orange-950/30 border border-orange-700/50 rounded-xl p-4 text-sm text-orange-300">
              <strong className="font-semibold">Held for human review.</strong>{" "}
              The classifier confidence score fell below the 0.65 threshold. In production a
              reviewer approves or rejects this via <code className="font-mono text-xs">POST /workflows/{"{run_id}"}/approve</code>.
            </div>
          )}

          {/* Failed / dead letter */}
          {(run?.status === "failed" || run?.status === "dead_letter") && (
            <div className="bg-red-950/30 border border-red-800/50 rounded-xl p-4 text-sm text-red-300">
              <strong className="font-semibold">Workflow failed.</strong>{" "}
              {run.status === "dead_letter"
                ? "All 3 Celery retries were exhausted. Check the step trace above for the root cause."
                : "An unrecoverable error occurred. The system retried automatically before failing."}
            </div>
          )}
        </section>
      )}

      {/* Footer */}
      <footer className="pt-6 border-t border-gray-800 text-xs text-gray-600 flex flex-wrap justify-between gap-2">
        <span>AI Workflow Orchestrator — portfolio demo</span>
        <span>FastAPI + Celery + AWS ECS Fargate</span>
      </footer>
    </main>
  );
}
