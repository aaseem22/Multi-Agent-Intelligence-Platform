"""Independent LLM judge (Groq by default). Interface frozen; bodies are implemented in Phase 3.

Design (from "Demystifying evals for AI agents"):
- one rubric dimension per judgement where the token budget allows, structured output, and an
  explicit "unknown" escape so the judge does not guess when information is missing;
- the judge sees only the question, the answer, the cited evidence (summaries + small data
  excerpts) and optionally a reference answer — never the agent's prompt;
- the judge model must differ from the agent model (settings.judge_provider / groq_judge_model).

Used by: app.core.eval_hooks.independent_eval (live self-evaluation) and the offline eval
harness in app.evals (model-based graders).
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Literal, TypeVar

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.core import prompts
from app.core.config import get_settings
from app.core.contracts import Evidence
from app.core.llm import (
    MAX_JUDGE_WAIT_SECONDS,
    estimate_tokens,
    get_judge_limiter,
    get_judge_llm,
    groq_retry_delay,
    judge_model_name,
    with_llm_retries,
)

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

Verdict = Literal["pass", "fail", "unknown"]


class RubricDimension(BaseModel):
    name: str  # e.g. "groundedness"
    question: str  # what the judge must decide, phrased as a yes/no question
    pass_description: str  # what a passing answer looks like
    fail_description: str  # what a failing answer looks like
    weight: float = 1.0


class Rubric(BaseModel):
    name: str  # e.g. "agent_answer", "final_answer"
    dimensions: list[RubricDimension]
    pass_threshold: float = 0.7  # weighted score needed to pass; "unknown" dimensions are excluded


class DimensionVerdict(BaseModel):
    dimension: str
    verdict: Verdict
    score: float = Field(ge=0.0, le=1.0)  # 1 pass, 0 fail, partial credit allowed
    reasoning: str  # one or two sentences, cites the evidence refs it relied on


class JudgeVerdict(BaseModel):
    rubric: str
    passed: bool
    score: float | None  # weighted mean over non-unknown dimensions; None if all unknown
    dimensions: list[DimensionVerdict]
    model: str
    feedback: str = ""  # actionable feedback an agent can use on a retry
    error: str | None = None  # set when the judge could not run (quota, parse failure)


class JudgeInput(BaseModel):
    question: str  # the subtask instruction or the stakeholder question
    answer: str
    evidence: list[Evidence] = []
    reference_answer: str | None = None  # golden datasets only
    context: str = ""  # optional extra facts, e.g. which agent produced the answer


AGENT_ANSWER_RUBRIC = Rubric(
    name="agent_answer",
    dimensions=[
        RubricDimension(
            name="groundedness",
            question="Is every factual claim in the answer supported by the cited evidence?",
            pass_description="All figures, names and dates appear in or follow from the evidence.",
            fail_description="Some claim is absent from, or contradicts, the evidence.",
        ),
        RubricDimension(
            name="completeness",
            question=(
                "Does the answer provide every piece of information the instruction asks for? "
                "Directions about how to work (which agents or tools to consult) are not "
                "requirements on the answer."
            ),
            pass_description="Each requested item is answered, or a gap is stated plainly.",
            fail_description="Requested information is missing without saying so.",
        ),
        RubricDimension(
            name="scope",
            question="Does the answer stay within the instruction and avoid speculation?",
            pass_description="No invented causes, no unsupported recommendations.",
            fail_description="Speculates or answers a different question.",
            weight=0.5,
        ),
    ],
)


async def judge(rubric: Rubric, item: JudgeInput, *, isolated: bool = False) -> JudgeVerdict:
    """Grade one item against a rubric. Never raises: failures return error set and
    passed=True with score=None so a judge outage never blocks an answer.

    Default: one structured call that returns every dimension, each judged on its own.
    `isolated=True` makes one call per dimension (more faithful, more tokens), meant for the
    offline harness where the token budget allows it."""
    model = ""
    try:
        model = judge_model_name()
        material = render_material(item)
        if isolated:
            outputs: list[_DimensionOut] = []
            feedback_parts: list[str] = []
            for dimension in rubric.dimensions:
                out = await _call(_DimensionOut, _prompt([dimension], material, single=True))
                outputs.append(out.model_copy(update={"dimension": dimension.name}))
                if out.verdict == "fail":
                    feedback_parts.append(f"{dimension.name}: {out.reasoning}")
            feedback = " ".join(feedback_parts)
        else:
            verdict_out = await _call(_VerdictOut, _prompt(rubric.dimensions, material))
            outputs, feedback = verdict_out.dimensions, verdict_out.feedback
        return _aggregate(rubric, outputs, feedback, model)
    except Exception as exc:
        logger.warning("Judge failed (%s): %s", rubric.name, str(exc)[:300])
        return JudgeVerdict(
            rubric=rubric.name,
            passed=True,
            score=None,
            dimensions=[],
            model=model,
            error=f"{type(exc).__name__}: {str(exc)[:300]}",
        )


# --- implementation ---

# Input budget: the whole prompt must stay near ~2.5K tokens so a call fits Groq's 8K TPM.
QUESTION_CHARS = 800
ANSWER_CHARS = 3000
EVIDENCE_CHARS = 7000
EVIDENCE_DATA_CHARS = 240
PEER_ANSWER_CHARS = 700
PEER_EVIDENCE_ITEMS = 8
REFERENCE_CHARS = 1000
CONTEXT_CHARS = 400


class _DimensionOut(BaseModel):
    dimension: str
    verdict: Verdict
    score: float
    reasoning: str


class _VerdictOut(BaseModel):
    dimensions: list[_DimensionOut]
    feedback: str


@dataclass
class JudgeUsage:
    """Cumulative judge token usage in this process (reported by the harness and live runs)."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    last: dict[str, int] = field(default_factory=dict)


_usage = JudgeUsage()


def judge_usage() -> JudgeUsage:
    return _usage


def reset_judge_usage() -> None:
    global _usage
    _usage = JudgeUsage()


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 15] + " ...[truncated]"


def _evidence_line(evidence: Evidence) -> str:
    line = f"- {evidence.source_ref}: {_clip(evidence.summary, 200)}"
    if evidence.source_type == "peer" and evidence.data:
        return line + _peer_detail(evidence.data)
    if evidence.data:
        data = json.dumps(evidence.data, default=str, separators=(",", ":"))
        line += f" | data: {_clip(data, EVIDENCE_DATA_CHARS)}"
    return line


def _peer_detail(data: dict[str, Any]) -> str:
    """A peer's answer and the evidence it cited, so multi-hop figures can be checked."""
    lines = []
    if answer := data.get("answer"):
        lines.append(f"\n  peer answer: {_clip(str(answer), PEER_ANSWER_CHARS)}")
    for item in (data.get("peer_evidence") or [])[:PEER_EVIDENCE_ITEMS]:
        if isinstance(item, dict):
            lines.append(
                f"\n  - {item.get('source_ref', '')}: {_clip(str(item.get('summary', '')), 160)}"
            )
    return "".join(lines)


def render_material(item: JudgeInput) -> str:
    """The compact, budgeted material the judge sees (never the agent's system prompt)."""
    sections = [
        f"## Question\n{_clip(item.question, QUESTION_CHARS)}",
        f"## Answer\n{_clip(item.answer, ANSWER_CHARS) or '(empty)'}",
    ]
    lines: list[str] = []
    used = 0
    for evidence in item.evidence:
        line = _evidence_line(evidence)
        if used + len(line) > EVIDENCE_CHARS:
            break
        lines.append(line)
        used += len(line)
    omitted = len(item.evidence) - len(lines)
    if omitted:
        lines.append(f"- ({omitted} more evidence items omitted for length)")
    sections.append(f"## Evidence ({len(item.evidence)} items)\n" + ("\n".join(lines) or "(none)"))
    if item.reference_answer:
        sections.append(f"## Reference answer\n{_clip(item.reference_answer, REFERENCE_CHARS)}")
    if item.context:
        sections.append(f"## Context\n{_clip(item.context, CONTEXT_CHARS)}")
    return "\n\n".join(sections)


def _prompt(
    dimensions: list[RubricDimension], material: str, *, single: bool = False
) -> list[BaseMessage]:
    rubric_lines = "\n".join(
        prompts.JUDGE_DIMENSION_LINE.format(
            name=d.name, question=d.question, passing=d.pass_description, failing=d.fail_description
        )
        for d in dimensions
    )
    task = (
        "Judge only this dimension."
        if single
        else "Return one entry per dimension, in this order, named exactly as listed.\n"
        + prompts.JUDGE_FEEDBACK_RULE
    )
    return [
        SystemMessage(prompts.JUDGE_SYSTEM),
        HumanMessage(f"## Rubric\n{rubric_lines}\n\n{task}\n\n{material}"),
    ]


def _structured(llm: Any, schema: type[BaseModel]) -> Any:
    if get_settings().judge_provider == "groq":
        return llm.with_structured_output(
            schema, method="json_schema", strict=True, include_raw=True
        )
    return llm.with_structured_output(schema, method="json_schema", include_raw=True)


def _usage_of(raw: Any) -> tuple[int, int]:
    usage = getattr(raw, "usage_metadata", None) or {}
    return int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))


async def _call(schema: type[T], messages: list[BaseMessage]) -> T:
    settings = get_settings()
    runnable = _structured(get_judge_llm(), schema)
    estimate = estimate_tokens("".join(str(m.content) for m in messages)) + 600
    limiter = get_judge_limiter()

    async def attempt() -> dict[str, Any]:
        await limiter.acquire(estimate)
        return await runnable.ainvoke(messages)

    out = await with_llm_retries(
        attempt,
        max_retries=settings.judge_max_retries,
        delay_hint=groq_retry_delay,
        max_wait=MAX_JUDGE_WAIT_SECONDS,
    )
    input_tokens, output_tokens = _usage_of(out.get("raw"))
    if input_tokens or output_tokens:
        limiter.settle(estimate, input_tokens + output_tokens)
    _usage.calls += 1
    _usage.input_tokens += input_tokens
    _usage.output_tokens += output_tokens
    _usage.last = {"input_tokens": input_tokens, "output_tokens": output_tokens}
    logger.info("Judge call: %d input + %d output tokens", input_tokens, output_tokens)
    if out.get("parsing_error") is not None or out.get("parsed") is None:
        raise ValueError(f"judge output could not be parsed: {out.get('parsing_error')}")
    parsed = out["parsed"]
    return parsed if isinstance(parsed, schema) else schema.model_validate(parsed)


def _aggregate(
    rubric: Rubric, outputs: list[_DimensionOut], feedback: str, model: str
) -> JudgeVerdict:
    by_name = {o.dimension.strip().lower(): o for o in outputs}
    dimensions: list[DimensionVerdict] = []
    weighted = total = 0.0
    for index, dimension in enumerate(rubric.dimensions):
        out = by_name.get(dimension.name.lower())
        if out is None and index < len(outputs) and len(outputs) == len(rubric.dimensions):
            out = outputs[index]  # the model renamed the dimension; fall back to its position
        if out is None:
            dimensions.append(
                DimensionVerdict(
                    dimension=dimension.name,
                    verdict="unknown",
                    score=0.0,
                    reasoning="The judge returned no verdict for this dimension.",
                )
            )
            continue
        score = 0.0 if out.verdict == "unknown" else min(1.0, max(0.0, float(out.score)))
        if out.verdict == "pass" and score == 0.0:
            score = 1.0
        dimensions.append(
            DimensionVerdict(
                dimension=dimension.name,
                verdict=out.verdict,
                score=score,
                reasoning=out.reasoning.strip(),
            )
        )
        if out.verdict != "unknown":
            weighted += dimension.weight * score
            total += dimension.weight
    score_value = round(weighted / total, 4) if total else None
    passed = score_value is None or score_value >= rubric.pass_threshold
    feedback = feedback.strip()
    if not passed and not feedback:
        feedback = " ".join(
            f"{d.dimension}: {d.reasoning}" for d in dimensions if d.verdict == "fail"
        )
    return JudgeVerdict(
        rubric=rubric.name,
        passed=passed,
        score=score_value,
        dimensions=dimensions,
        model=model,
        feedback=feedback if not passed or any(d.verdict == "fail" for d in dimensions) else "",
    )
