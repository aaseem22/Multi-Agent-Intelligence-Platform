"""Evaluation hooks used by the live request path. Department-agnostic.

- `self_check`: a deterministic code grader (no LLM), run at the end of every agent subgraph.
- `independent_eval`: the independent LLM judge (app.core.judge), run in the orchestrator's
  eval_gate. `independent_eval_detailed` also returns the JudgeVerdict for events and logs.
- `evidence_check`: a deterministic evidence presence check.
- `recovery_router`: decides what to do with a failed evaluation; attempt limits are enforced
  by the caller (orchestrator.eval_gate).
"""

import math
import re
from collections.abc import Iterable
from typing import Any, Literal

from app.core.config import get_settings
from app.core.contracts import AgentResult, EvalResult, Evidence, Subtask
from app.core.judge import AGENT_ANSWER_RUBRIC, JudgeInput, JudgeVerdict, judge

RecoveryAction = Literal["pass", "retry", "replan", "clarify"]

FIGURE_MATCH_THRESHOLD = 0.8  # share of figures in the answer that must trace to evidence
RELATIVE_TOLERANCE = 0.005
MAX_EVIDENCE_NUMBERS = 300  # caps the pairwise derived-figure search
MAX_REASONS = 8

_UNITS = {
    "k": 1e3,
    "thousand": 1e3,
    "l": 1e5,
    "lakh": 1e5,
    "lakhs": 1e5,
    "lac": 1e5,
    "cr": 1e7,
    "crore": 1e7,
    "crores": 1e7,
    "m": 1e6,
    "mn": 1e6,
    "million": 1e6,
    "b": 1e9,
    "bn": 1e9,
    "billion": 1e9,
}
_DATE = re.compile(
    r"\b\d{4}-\d{2}(?:-\d{2})?(?:[T ][\d:.]+Z?)?\b|\b\d{4}-Q[1-4]\b|\bQ[1-4]\b", re.I
)
_FIGURE = re.compile(
    r"(?P<cur>[₹$€£]|\bINR\b|\bRs\.?|\bUSD\b)?\s*"
    r"(?<![\w])(?P<num>\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?:\s*(?P<pct>%|percent\b)|\s*(?P<unit>thousand|lakhs?|lac|crores?|cr|million|mn|"
    r"billion|bn|k|l|m|b)\b)?",
    re.I,
)
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


class Figure:
    def __init__(self, text: str, value: float, tolerance: float, percent: bool) -> None:
        self.text = text
        self.value = value
        self.tolerance = tolerance
        self.percent = percent

    def matches(self, candidate: float) -> bool:
        limit = max(self.tolerance, abs(self.value) * RELATIVE_TOLERANCE)
        return abs(candidate - self.value) <= limit


def extract_figures(text: str) -> list[Figure]:
    """Amounts, percentages and counts of two or more digits; dates and years are skipped."""
    cleaned = _DATE.sub(" ", text)
    figures: list[Figure] = []
    for match in _FIGURE.finditer(cleaned):
        raw = match.group("num")
        digits = raw.replace(",", "")
        has_marker = bool(match.group("cur") or match.group("pct") or match.group("unit"))
        integer_digits = len(digits.split(".")[0].lstrip("0"))
        if not has_marker and integer_digits < 2:
            continue
        value = float(digits)
        if not has_marker and "." not in digits and 1900 <= value <= 2100:
            continue  # a year
        decimals = len(digits.split(".")[1]) if "." in digits else 0
        multiplier = _UNITS.get((match.group("unit") or "").lower(), 1.0)
        tolerance = 0.5 * 10 ** (-decimals) * multiplier
        figures.append(
            Figure(
                text=match.group(0).strip(),
                value=value * multiplier,
                tolerance=tolerance,
                percent=bool(match.group("pct")),
            )
        )
    return figures


def _walk(value: Any) -> Iterable[float]:
    if isinstance(value, bool):
        return
    if isinstance(value, int | float):
        if math.isfinite(value):
            yield float(value)
    elif isinstance(value, str):
        for token in _NUMBER.findall(value.replace(",", "")):
            yield float(token)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, list | tuple):
        yield float(len(value))  # counts of listed records are citable
        for item in value:
            yield from _walk(item)


def evidence_numbers(evidence: list[Evidence]) -> list[float]:
    numbers: dict[float, None] = {float(len(evidence)): None}
    for item in evidence:
        for value in _walk([item.source_ref, item.summary, item.data or {}]):
            numbers.setdefault(value, None)
    return list(numbers)[:MAX_EVIDENCE_NUMBERS]


def _derived(numbers: list[float]) -> Iterable[float]:
    """Simple arithmetic an answer may state: sums, differences, ratios as percentages."""
    for i, a in enumerate(numbers):
        yield a * 100
        for b in numbers[i + 1 :]:
            yield a + b
            yield abs(a - b)
            for top, bottom in ((a, b), (b, a)):
                if bottom:
                    yield top / bottom * 100
                    yield (top - bottom) / abs(bottom) * 100


def unmatched_figures(answer: str, evidence: list[Evidence]) -> tuple[list[Figure], list[Figure]]:
    """Split the answer's figures into (matched, unmatched) against the evidence."""
    figures = extract_figures(answer)
    if not figures:
        return [], []
    numbers = evidence_numbers(evidence)
    matched: list[Figure] = []
    unmatched: list[Figure] = []
    pending: list[Figure] = []
    for figure in figures:
        (matched if any(figure.matches(n) for n in numbers) else pending).append(figure)
    if pending:
        derived = list(_derived(numbers))
        for figure in pending:
            (matched if any(figure.matches(n) for n in derived) else unmatched).append(figure)
    return matched, unmatched


async def self_check(result: AgentResult, subtask: Subtask) -> EvalResult:
    """Deterministic grader: status/answer consistency, resolvable evidence, and figures in the
    answer that trace back to evidence data or summaries. Failed results pass trivially."""
    if result.status == "failed":
        return EvalResult(passed=True, stage="self", score=None, reasons=["agent reported failure"])
    reasons: list[str] = []
    structural_ok = True
    if not result.answer.strip():
        structural_ok = False
        reasons.append(f"status is {result.status} but the answer is empty")
    blank_refs = [e for e in result.evidence if not e.source_ref.strip()]
    if blank_refs:
        structural_ok = False
        reasons.append(f"{len(blank_refs)} evidence item(s) have no source_ref")
    matched, unmatched = unmatched_figures(result.answer, result.evidence)
    total = len(matched) + len(unmatched)
    score = len(matched) / total if total else 1.0
    if unmatched:
        shown = ", ".join(f"'{f.text}'" for f in unmatched[:MAX_REASONS])
        reasons.append(
            f"{len(unmatched)} of {total} figures in the answer do not appear in the evidence: "
            f"{shown}"
        )
    passed = structural_ok and score >= FIGURE_MATCH_THRESHOLD
    return EvalResult(
        passed=passed,
        stage="self",
        score=round(score if structural_ok else 0.0, 4),
        reasons=reasons,
    )


async def independent_eval_detailed(
    result: AgentResult, subtask: Subtask
) -> tuple[EvalResult, JudgeVerdict | None]:
    """The independent judge's EvalResult plus the full JudgeVerdict (None when skipped)."""
    settings = get_settings()
    if not settings.eval_judge_enabled:
        return EvalResult(passed=True, stage="independent", reasons=["judge disabled"]), None
    if result.status not in ("ok", "partial"):
        reason = f"not judged: status {result.status}"
        return EvalResult(passed=True, stage="independent", reasons=[reason]), None
    verdict = await judge(
        AGENT_ANSWER_RUBRIC,
        JudgeInput(
            question=subtask.instruction,
            answer=result.answer,
            evidence=result.evidence,
            context=f"Answer produced by the {result.agent} agent (status {result.status}).",
        ),
    )
    if verdict.error:
        evaluation = EvalResult(
            passed=True, stage="independent", reasons=[f"judge unavailable: {verdict.error}"]
        )
        return evaluation, verdict
    reasons = [f"{d.dimension}: {d.reasoning}" for d in verdict.dimensions if d.verdict == "fail"]
    evaluation = EvalResult(
        passed=verdict.passed, stage="independent", score=verdict.score, reasons=reasons
    )
    return evaluation, verdict


async def independent_eval(result: AgentResult, subtask: Subtask) -> EvalResult:
    evaluation, _ = await independent_eval_detailed(result, subtask)
    return evaluation


async def evidence_check(result: AgentResult) -> EvalResult:
    passed = bool(result.evidence) or result.status != "ok"
    reasons = [] if passed else ["status is ok but no evidence was attached"]
    return EvalResult(
        passed=passed, stage="evidence", reasons=reasons, score=1.0 if passed else 0.0
    )


def recovery_router(eval_result: EvalResult) -> RecoveryAction:
    """ "retry" for a failed evaluation when recovery is enabled; otherwise "pass"."""
    if eval_result.passed or get_settings().eval_recovery != "retry":
        return "pass"
    return "retry"
