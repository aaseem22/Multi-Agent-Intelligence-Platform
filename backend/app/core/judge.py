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

from typing import Literal

from pydantic import BaseModel, Field

from app.core.contracts import Evidence

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
            question="Does the answer address every part of the instruction?",
            pass_description="Each requested item is answered, or a gap is stated plainly.",
            fail_description="Part of the instruction is ignored without saying so.",
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


async def judge(rubric: Rubric, item: JudgeInput) -> JudgeVerdict:
    """Grade one item against a rubric. Never raises: failures return error set and
    passed=True with score=None so a judge outage never blocks an answer."""
    raise NotImplementedError("judge() is implemented in Phase 3")
