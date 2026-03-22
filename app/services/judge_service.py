"""
LLM-as-judge evaluation service.

After every completed workflow, a judge LLM independently evaluates the output
quality across five dimensions. Scores are stored in the DB and aggregated in
the /metrics endpoint, enabling quality trend tracking over time.

This is the same evaluation paradigm used by frontier AI labs (MT-Bench,
Alpaca-Eval, Claude's constitutional evaluation) — having one model grade
another's output on structured criteria.

Dimensions:
  - accuracy (0-1): Did the system correctly identify the issue/intent?
  - actionability (0-1): Are next steps specific and implementable?
  - completeness (0-1): Were all relevant aspects addressed?
  - tone (0-1): Is the response calibrated to context and severity?
  - safety (0-1): Does the output avoid harmful or dangerous advice?

Overall = weighted average (accuracy 0.30, actionability 0.30,
                            completeness 0.20, tone 0.10, safety 0.10)
"""

from dataclasses import dataclass

from app.services.llm_service import LLMRequest, LLMResponse, complete_with_tools
from app.services.logging_service import get_logger

logger = get_logger(__name__)

_WEIGHTS = {
    "accuracy":      0.30,
    "actionability": 0.30,
    "completeness":  0.20,
    "tone":          0.10,
    "safety":        0.10,
}

_JUDGE_TOOL = {
    "type": "function",
    "function": {
        "name": "quality_assessment",
        "description": "Score the quality of an AI workflow output.",
        "parameters": {
            "type": "object",
            "required": ["accuracy", "actionability", "completeness", "tone", "safety", "reasoning"],
            "properties": {
                "accuracy": {
                    "type": "number",
                    "description": "0.0-1.0. Did the system correctly identify the core issue and its root cause?",
                },
                "actionability": {
                    "type": "number",
                    "description": "0.0-1.0. Are the recommended next steps specific, concrete, and immediately implementable?",
                },
                "completeness": {
                    "type": "number",
                    "description": "0.0-1.0. Were all relevant aspects of the input addressed, with no important details missed?",
                },
                "tone": {
                    "type": "number",
                    "description": "0.0-1.0. Is the response appropriately calibrated to the severity and context (e.g. urgent for P1, empathetic for angry customer)?",
                },
                "safety": {
                    "type": "number",
                    "description": "0.0-1.0. Does the output avoid harmful recommendations, sensitive data exposure, or dangerous advice?",
                },
                "reasoning": {
                    "type": "string",
                    "description": "2-3 sentence justification of the scores, highlighting the strongest and weakest aspects.",
                },
            },
        },
    },
}

_SYSTEM_PROMPT = """You are an expert evaluator for an AI workflow orchestration system.

Your job is to objectively score the quality of AI-generated triage outputs.

You will be given:
1. The original input (ticket, email, or log)
2. The AI system's final output

Score each dimension from 0.0 (completely wrong/missing) to 1.0 (perfect).
Use the full range — a 0.7 is a good output with minor gaps, not a mediocre one.
Be critical but fair. Focus on what the output actually achieved, not what it tried to do."""


@dataclass
class JudgeResult:
    overall_score: float
    dimensions: dict[str, float]
    reasoning: str


async def evaluate_output(
    input_type: str,
    raw_input: str,
    final_output: str,
) -> JudgeResult | None:
    """
    Run the LLM judge on a completed workflow output.

    Returns None on any failure — judge errors must never propagate to the
    main pipeline. Quality scoring is best-effort enrichment, not critical path.
    """
    try:
        prompt = f"""Input Type: {input_type}

--- ORIGINAL INPUT ---
{raw_input[:1500]}

--- AI SYSTEM OUTPUT ---
{final_output[:2000]}

Please evaluate the quality of this AI triage output."""

        request = LLMRequest(
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
            tools=[_JUDGE_TOOL],
            model="gpt-4o-mini",
            max_tokens=512,
            temperature=0.1,
        )

        response: LLMResponse = await complete_with_tools(request)

        if not response.tool_calls:
            logger.warning("judge_no_tool_call")
            return None

        scores = response.tool_calls[0]["input"]

        dimensions = {
            dim: round(float(scores.get(dim, 0.5)), 3)
            for dim in _WEIGHTS
        }

        overall = round(
            sum(dimensions[dim] * weight for dim, weight in _WEIGHTS.items()),
            3,
        )

        result = JudgeResult(
            overall_score=overall,
            dimensions=dimensions,
            reasoning=str(scores.get("reasoning", "")),
        )

        logger.info(
            "judge_completed",
            overall_score=result.overall_score,
            dimensions=result.dimensions,
        )
        return result

    except Exception as e:
        logger.error("judge_evaluation_failed", error=str(e))
        return None
