"""Evaluation hooks. STUBS for this phase: the next phase replaces only the function bodies."""

from typing import Literal

from app.core.contracts import AgentResult, EvalResult, Subtask

RecoveryAction = Literal["pass", "retry", "replan", "clarify"]


async def self_check(result: AgentResult, subtask: Subtask) -> EvalResult:
    return EvalResult(passed=True, stage="self", reasons=["stub: self-check not implemented"])


async def independent_eval(result: AgentResult, subtask: Subtask) -> EvalResult:
    return EvalResult(passed=True, stage="independent", reasons=["stub: judge not implemented"])


async def evidence_check(result: AgentResult) -> EvalResult:
    passed = bool(result.evidence) or result.status != "ok"
    reasons = [] if passed else ["status is ok but no evidence was attached"]
    return EvalResult(
        passed=passed, stage="evidence", reasons=reasons, score=1.0 if passed else 0.0
    )


def recovery_router(eval_result: EvalResult) -> RecoveryAction:
    return "pass"
