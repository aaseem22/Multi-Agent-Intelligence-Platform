"""Model graders: the independent judge (app.core.judge.judge) grades the final answer against a
rubric with one dimension each. The judge never sees agent prompts, only the question, the answer,
the cited evidence and (for reference_match) the golden reference answer.

A model grader is *skipped* (does not count towards the trial score) when the judge is disabled for
the run, not implemented, raises, returns an error verdict or answers "unknown" on every dimension.
Calibrate these graders against human labels (POST /api/evals/runs/{id}/labels)."""

import logging

from app.core import judge as judge_module
from app.core.contracts import Evidence
from app.core.judge import JudgeInput, JudgeVerdict, Rubric, RubricDimension
from app.evals.contracts import GraderResult
from app.evals.graders.base import Grader, GradingContext

logger = logging.getLogger(__name__)

MAX_EVIDENCE = 40

GROUNDEDNESS_RUBRIC = Rubric(
    name="final_answer_groundedness",
    dimensions=[
        RubricDimension(
            name="groundedness",
            question="Is every figure, name, date and conclusion in the answer supported by the "
            "evidence listed?",
            pass_description="All factual statements appear in, or follow directly from, the "
            "evidence; gaps are stated rather than filled in.",
            fail_description="At least one statement is absent from or contradicts the evidence, "
            "or a cause/recommendation is invented.",
        )
    ],
)

COMPLETENESS_RUBRIC = Rubric(
    name="final_answer_completeness",
    dimensions=[
        RubricDimension(
            name="completeness",
            question="Does the answer address every part of the stakeholder's question?",
            pass_description="Each part of the question is answered, or the answer says plainly "
            "which part could not be answered and why.",
            fail_description="Some part of the question is ignored without saying so.",
        )
    ],
)

REFERENCE_RUBRIC = Rubric(
    name="final_answer_reference_match",
    dimensions=[
        RubricDimension(
            name="reference_match",
            question="Does the answer agree with the reference answer on the key facts (names, "
            "figures, conclusions)? Extra correct detail and different wording are fine.",
            pass_description="Every key fact of the reference answer is present and none is "
            "contradicted.",
            fail_description="A key fact of the reference answer is missing or contradicted.",
        )
    ],
)


class ModelGrader(Grader):
    kind = "model"
    rubric: Rubric
    uses_reference = False

    async def grade(self, ctx: GradingContext) -> GraderResult:
        trial = ctx.trial
        if not ctx.judge_enabled:
            return self.skipped("judge disabled for this run")
        if trial.final is None:
            return self.skipped("no final answer to judge")
        reference = ctx.task.expected.reference_answer if self.uses_reference else None
        if self.uses_reference and not reference:
            return self.skipped("task has no reference answer")
        item = JudgeInput(
            question=ctx.task.question,
            answer=trial.answer_text,
            evidence=[Evidence.model_validate(e) for e in trial.evidence[:MAX_EVIDENCE]],
            reference_answer=reference,
            context=f"Agents involved: {', '.join(trial.involved_agents) or 'none'}",
        )
        try:
            verdict = await judge_module.judge(self.rubric, item)
        except NotImplementedError:
            return self.skipped("judge not implemented")
        except Exception as exc:
            logger.warning("Judge failed for %s: %s", self.name, exc)
            return self.skipped(f"judge failed: {type(exc).__name__}: {exc}")
        if verdict.error:
            return self.skipped(f"judge error: {verdict.error}", verdict)
        if verdict.score is None:
            return self.skipped("judge answered unknown on every dimension", verdict)
        reasons = [f"{d.dimension}: {d.verdict} — {d.reasoning}" for d in verdict.dimensions]
        return self.result(
            verdict.score,
            reasons or [f"judge score {verdict.score:.2f}"],
            passed=verdict.passed,
            judge=verdict,
            details={"model": verdict.model},
        )

    def skipped(self, reason: str, verdict: JudgeVerdict | None = None) -> GraderResult:
        return self.result(
            0.0,
            [f"model grader skipped: {reason}"],
            passed=True,
            weight=0.0,
            judge=verdict,
            details={"skipped": True},
        )


class AnswerGroundednessGrader(ModelGrader):
    name = "answer_groundedness"
    rubric = GROUNDEDNESS_RUBRIC


class AnswerCompletenessGrader(ModelGrader):
    name = "answer_completeness"
    rubric = COMPLETENESS_RUBRIC


class ReferenceMatchGrader(ModelGrader):
    name = "reference_match"
    rubric = REFERENCE_RUBRIC
    uses_reference = True


MODEL_GRADERS: list[type[Grader]] = [
    AnswerGroundednessGrader,
    AnswerCompletenessGrader,
    ReferenceMatchGrader,
]
