"""Grader registry: dataset tasks name their graders; `GRADERS[name]` is the instance."""

from app.evals.contracts import GraderResult
from app.evals.graders.base import Grader, GradingContext, is_informational, is_skipped
from app.evals.graders.code import CODE_GRADERS
from app.evals.graders.model import MODEL_GRADERS

GRADERS: dict[str, Grader] = {}


def register(grader: Grader) -> Grader:
    if grader.name in GRADERS:
        raise ValueError(f"grader {grader.name!r} already registered")
    GRADERS[grader.name] = grader
    return grader


for _cls in (*CODE_GRADERS, *MODEL_GRADERS):
    register(_cls())


async def run_graders(names: list[str], ctx: GradingContext) -> list[GraderResult]:
    results: list[GraderResult] = []
    for name in names:
        grader = GRADERS[name]
        try:
            results.append(await grader.grade(ctx))
        except Exception as exc:  # a grader bug must not lose the trial
            results.append(
                GraderResult(
                    grader=name,
                    kind=grader.kind,
                    passed=False,
                    score=0.0,
                    weight=grader.weight,
                    reasons=[f"grader crashed: {type(exc).__name__}: {exc}"],
                    details={"informational": grader.informational, "crashed": True},
                )
            )
    return results


__all__ = [
    "GRADERS",
    "Grader",
    "GradingContext",
    "is_informational",
    "is_skipped",
    "register",
    "run_graders",
]
