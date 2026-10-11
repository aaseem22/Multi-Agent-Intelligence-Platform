from datetime import UTC, datetime

import pytest

from app.evals.contracts import EvalTask, ExpectedBehaviour, GraderResult, TrialResult
from app.evals.scoring import (
    aggregate,
    pass_at_k_estimate,
    pass_hat_k_estimate,
    trial_passed,
    weighted_score,
)


def g(name: str, passed: bool, score: float, weight: float = 1.0, **details) -> GraderResult:
    kind = details.pop("kind", "code")
    return GraderResult(
        grader=name, kind=kind, passed=passed, score=score, weight=weight, details=details
    )


def test_weighted_score_excludes_skipped_model_graders() -> None:
    graders = [
        g("required_facts", True, 1.0, 2.0),
        g("routing", True, 0.5),
        g("reference_match", True, 0.0, 0.0, kind="model", skipped=True),
    ]
    assert weighted_score(graders) == pytest.approx(2.5 / 3, abs=1e-3)


def test_trial_requires_every_non_informational_code_grader() -> None:
    passing = [g("routing", True, 1.0), g("efficiency", False, 0.1, 0.25, informational=True)]
    assert trial_passed(passing)
    failing = [g("routing", False, 0.9), g("required_facts", True, 1.0, 2.0)]
    assert not trial_passed(failing)


def test_trial_needs_threshold_score_even_when_code_graders_pass() -> None:
    graders = [g("routing", True, 1.0), g("answer_groundedness", False, 0.0, 3.0, kind="model")]
    assert weighted_score(graders) == 0.25
    assert not trial_passed(graders)


def test_pass_hat_k_matches_the_article_example() -> None:
    assert pass_hat_k_estimate(0.75, 3) == pytest.approx(0.42, abs=0.005)


def test_pass_at_k_estimate() -> None:
    assert pass_at_k_estimate(4, 3, 1) == pytest.approx(0.75)
    assert pass_at_k_estimate(4, 3, 2) == 1.0
    assert pass_at_k_estimate(4, 0, 3) == 0.0
    assert pass_at_k_estimate(5, 1, 2) == pytest.approx(1 - 6 / 10)


def _task(task_id: str, suite: str, category: str) -> EvalTask:
    return EvalTask(
        id=task_id,
        suite=suite,
        category=category,
        question=task_id,
        expected=ExpectedBehaviour(),
        graders=["routing"],
    )


def _trial(task_id: str, index: int, passed: bool, score: float) -> TrialResult:
    return TrialResult(
        trial_id=f"{task_id}__{index}",
        run_id="run",
        task_id=task_id,
        index=index,
        status="passed" if passed else "failed",
        score=score,
        passed=passed,
        graders=[g("routing", passed, score)],
        question=task_id,
        started_at=datetime(2026, 10, 11, tzinfo=UTC),
    )


def test_aggregate_pass_at_k_and_pass_hat_k() -> None:
    tasks = [_task("a", "regression", "single"), _task("b", "capability", "a2a")]
    trials = [
        _trial("a", 0, True, 1.0),
        _trial("a", 1, True, 1.0),
        _trial("a", 2, True, 1.0),
        _trial("a", 3, False, 0.5),  # task a: 75% per trial
        _trial("b", 0, False, 0.0),
        _trial("b", 1, False, 0.0),
        _trial("b", 2, False, 0.0),
        _trial("b", 3, False, 0.0),
    ]
    summary = aggregate(tasks, trials)
    assert summary["pass_rate"] == 0.375
    assert summary["pass_at_k"] == 0.5  # only task a has a passing trial
    assert summary["pass_hat_k"] == 0.0  # no task passed every trial
    assert summary["by_suite"] == {"capability": 0.0, "regression": 0.75}
    assert summary["by_category"] == {"a2a": 0.0, "single": 0.75}
    assert summary["grader_pass_rates"] == {"routing": 0.375}
    a = next(t for t in summary["tasks"] if t.task_id == "a")
    assert a.passes == 3 and a.pass_at_k and not a.pass_hat_k and a.mean_score == 0.875


def test_aggregate_without_trials() -> None:
    summary = aggregate([_task("a", "regression", "x")], [])
    assert summary["pass_rate"] is None and summary["tasks"] == []
