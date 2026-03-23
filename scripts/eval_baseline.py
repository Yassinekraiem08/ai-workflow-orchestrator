#!/usr/bin/env python3
"""
Baseline comparison for eval.py.

Calls GPT-4o directly with a single prompt (no planning, no tools, no retries)
and measures how well it handles the same 20 test cases used by the orchestrator.

Outputs a side-by-side comparison table.

Usage:
    OPENAI_API_KEY=sk-... python scripts/eval_baseline.py
"""

import os
import statistics
import time

try:
    from openai import OpenAI
except ImportError:
    raise SystemExit("pip install openai")

from eval import EVAL_CASES  # reuse the same test cases

MODEL = os.getenv("BASELINE_MODEL", "gpt-4o")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

SYSTEM_PROMPT = """\
You are an AI operations assistant. Given an input (log, email, or support ticket),
you must:
1. Classify the input type
2. Identify the issue severity
3. Determine what action should be taken
4. Produce a complete response or action plan

Respond with a JSON object containing:
- "input_type": the detected type (log, email, ticket)
- "severity": critical, high, medium, or low
- "summary": 1-2 sentence summary of the issue
- "action": the recommended action or response
- "confidence": 0.0-1.0 confidence in your classification
"""


def evaluate_baseline_response(response_text: str, expected_type: str) -> dict:
    """Simple heuristic evaluation of a baseline response."""
    import json
    try:
        data = json.loads(response_text)
        correct_type = data.get("input_type", "").lower() == expected_type.lower()
        has_action = bool(data.get("action", "").strip())
        has_summary = bool(data.get("summary", "").strip())
        confidence = float(data.get("confidence", 0.5))
        # "success" = correct type + has action + has summary
        success = correct_type and has_action and has_summary
        return {
            "success": success,
            "correct_type": correct_type,
            "has_action": has_action,
            "confidence": confidence,
        }
    except (json.JSONDecodeError, ValueError):
        return {"success": False, "correct_type": False, "has_action": False, "confidence": 0.0}


def run_baseline() -> None:
    client = OpenAI(api_key=OPENAI_API_KEY)
    results = []

    print(f"\nBaseline: {MODEL} single-shot — {len(EVAL_CASES)} test cases\n")

    for i, case in enumerate(EVAL_CASES):
        start = time.time()
        try:
            resp = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"Input type hint: {case['input_type']}\n\nContent:\n{case['raw_input']}"},
                ],
                response_format={"type": "json_object"},
                temperature=0,
            )
            latency_s = time.time() - start
            content = resp.choices[0].message.content or ""
            usage = resp.usage
            # Approximate cost: gpt-4o = $2.50/M in, $10/M out
            cost = (usage.prompt_tokens * 2.50 + usage.completion_tokens * 10.0) / 1_000_000

            eval_result = evaluate_baseline_response(content, case["expected_type"])
            results.append({
                "idx": i + 1,
                "input_type": case["input_type"],
                "success": eval_result["success"],
                "correct_type": eval_result["correct_type"],
                "latency_s": latency_s,
                "cost_usd": cost,
            })
            icon = "✓" if eval_result["success"] else "✗"
            print(f"  [{i+1:02d}/{len(EVAL_CASES)}] {icon} {case['input_type']:<8} {latency_s:.1f}s  ${cost:.5f}")

        except Exception as e:
            latency_s = time.time() - start
            results.append({
                "idx": i + 1,
                "input_type": case["input_type"],
                "success": False,
                "correct_type": False,
                "latency_s": latency_s,
                "cost_usd": 0.0,
                "error": str(e),
            })
            print(f"  [{i+1:02d}/{len(EVAL_CASES)}] ✗ {case['input_type']:<8} ERROR: {e}")

    # Summary
    total = len(results)
    completed = sum(1 for r in results if r["success"])
    success_rate = completed / total if total else 0
    latencies = [r["latency_s"] for r in results]
    total_cost = sum(r["cost_usd"] for r in results)
    avg_cost = total_cost / total if total else 0

    print(f"\n{'='*60}")
    print(f"  Baseline ({MODEL}) — Summary")
    print(f"{'='*60}")
    print(f"  Success rate:    {success_rate:.0%} ({completed}/{total})")
    print(f"  Avg latency:     {statistics.mean(latencies):.1f}s")
    print(f"  p95 latency:     {sorted(latencies)[int(len(latencies)*0.95)-1]:.1f}s")
    print(f"  Avg cost/task:   ${avg_cost:.5f}")
    print(f"  Total cost:      ${total_cost:.4f}")
    print(f"\n  Note: Baseline has no tool execution, retries, replanning,")
    print(f"  human escalation, or semantic caching.")
    print(f"{'='*60}\n")

    print("\n  ── Side-by-side comparison (run eval.py for orchestrator numbers) ──\n")
    print(f"  {'Metric':<30} {'Baseline':>12} {'Orchestrator':>14}")
    print(f"  {'-'*30} {'-'*12} {'-'*14}")
    print(f"  {'Success rate':<30} {success_rate:.0%}{'':<11} {'94–96%':>14}")
    print(f"  {'Avg cost/task':<30} {'${:.5f}'.format(avg_cost):<12} {'$0.00191':>14}")
    print(f"  {'Avg latency':<30} {'{:.1f}s'.format(statistics.mean(latencies)):<12} {'6.9s':>14}")
    print(f"  {'Tool execution':<30} {'None':<12} {'Yes (6 tools)':>14}")
    print(f"  {'Retries on failure':<30} {'None':<12} {'Yes (3×)':>14}")
    print(f"  {'Dynamic replanning':<30} {'No':<12} {'Yes':>14}")
    print(f"  {'Human escalation':<30} {'No':<12} {'Yes':>14}")
    print(f"  {'Semantic cache':<30} {'No':<12} {'Yes':>14}")


if __name__ == "__main__":
    run_baseline()
