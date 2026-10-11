"""Grader interface. A grader checks one aspect of a trial and returns a GraderResult with partial
credit. Graders are looked up by name from the registry in app.evals.graders."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar

from app.evals.contracts import EvalTask, GraderKind, GraderResult
from app.evals.transcript import TrialView


@dataclass
class GradingContext:
    task: EvalTask  # templates already resolved
    trial: TrialView
    judge_enabled: bool = True


class Grader(ABC):
    name: ClassVar[str]
    kind: ClassVar[GraderKind] = "code"
    weight: ClassVar[float] = 1.0
    # Informational graders are reported but never decide whether a trial passes.
    informational: ClassVar[bool] = False

    @abstractmethod
    async def grade(self, ctx: GradingContext) -> GraderResult: ...

    def result(
        self,
        score: float,
        reasons: list[str],
        *,
        passed: bool | None = None,
        details: dict[str, Any] | None = None,
        weight: float | None = None,
        **extra: Any,
    ) -> GraderResult:
        score = max(0.0, min(1.0, score))
        return GraderResult(
            grader=self.name,
            kind=self.kind,
            passed=score >= 1.0 if passed is None else passed,
            score=round(score, 4),
            weight=self.weight if weight is None else weight,
            reasons=reasons,
            details={"informational": self.informational, **(details or {})},
            **extra,
        )


def is_skipped(result: GraderResult) -> bool:
    return bool(result.details.get("skipped"))


def is_informational(result: GraderResult) -> bool:
    return bool(result.details.get("informational"))
