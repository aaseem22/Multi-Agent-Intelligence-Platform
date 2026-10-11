"""Trial verdicts and run aggregation (pass rate, pass@k, pass^k, per suite/category/grader).

- A trial passes when every non-informational code grader passes and the weighted score over the
  graders that ran (skipped model graders excluded) is at least PASS_THRESHOLD.
- pass@k for a task: at least one of its k trials passed. pass^k: all k passed. The run-level
  numbers are the share of tasks meeting each. With per-trial success rate p, pass^k ≈ p**k
  (75% → 42% at k=3) and pass@k ≈ 1-(1-p)**k; `pass_at_k_estimate` is the unbiased estimator
  for n trials with c passes."""

from collections import defaultdict
from collections.abc import Iterable
from math import comb

from app.evals.contracts import EvalTask, GraderResult, TaskSummary, TrialResult
from app.evals.graders import is_informational, is_skipped

PASS_THRESHOLD = 0.7


def weighted_score(graders: list[GraderResult]) -> float:
    counted = [g for g in graders if not is_skipped(g) and g.weight > 0]
    total = sum(g.weight for g in counted)
    if not total:
        return 0.0
    return round(sum(g.score * g.weight for g in counted) / total, 4)


def trial_passed(graders: list[GraderResult], threshold: float = PASS_THRESHOLD) -> bool:
    required = [g for g in graders if g.kind == "code" and not is_informational(g)]
    return all(g.passed for g in required) and weighted_score(graders) >= threshold


def pass_at_k_estimate(n: int, c: int, k: int) -> float:
    """Probability that at least one of k samples passes, given c passes in n trials."""
    if k > n:
        raise ValueError("k cannot exceed n")
    if n - c < k:
        return 1.0
    return 1.0 - comb(n - c, k) / comb(n, k)


def pass_hat_k_estimate(p: float, k: int) -> float:
    """Probability that k independent trials all pass at per-trial success rate p."""
    return p**k


def grader_pass_rates(trials: Iterable[TrialResult]) -> dict[str, float]:
    counts: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for trial in trials:
        for g in trial.graders:
            if is_skipped(g):
                continue
            counts[g.grader][0] += int(g.passed)
            counts[g.grader][1] += 1
    return {name: round(p / n, 4) for name, (p, n) in sorted(counts.items()) if n}


def _rate(trials: list[TrialResult]) -> float:
    return round(sum(t.passed for t in trials) / len(trials), 4) if trials else 0.0


def summarise_task(task: EvalTask, trials: list[TrialResult]) -> TaskSummary:
    passes = sum(t.passed for t in trials)
    return TaskSummary(
        task_id=task.id,
        suite=task.suite,
        category=task.category,
        question=trials[0].question if trials else task.question,
        trials=len(trials),
        passes=passes,
        pass_at_k=passes > 0,
        pass_hat_k=bool(trials) and passes == len(trials),
        mean_score=round(sum(t.score for t in trials) / len(trials), 4) if trials else 0.0,
        grader_pass_rates=grader_pass_rates(trials),
    )


def aggregate(tasks: list[EvalTask], trials: list[TrialResult]) -> dict[str, object]:
    """Fields of RunSummary computed from the trials done so far."""
    by_task: dict[str, list[TrialResult]] = defaultdict(list)
    for trial in trials:
        by_task[trial.task_id].append(trial)
    summaries = [summarise_task(t, by_task[t.id]) for t in tasks if by_task.get(t.id)]
    task_of = {t.id: t for t in tasks}
    by_suite: dict[str, list[TrialResult]] = defaultdict(list)
    by_category: dict[str, list[TrialResult]] = defaultdict(list)
    for trial in trials:
        task = task_of.get(trial.task_id)
        if task:
            by_suite[task.suite].append(trial)
            by_category[task.category].append(trial)
    done = bool(trials)
    return {
        "trials_done": len(trials),
        "pass_rate": _rate(trials) if done else None,
        "pass_at_k": round(sum(s.pass_at_k for s in summaries) / len(summaries), 4)
        if summaries
        else None,
        "pass_hat_k": round(sum(s.pass_hat_k for s in summaries) / len(summaries), 4)
        if summaries
        else None,
        "mean_score": round(sum(t.score for t in trials) / len(trials), 4) if done else None,
        "by_suite": {k: _rate(v) for k, v in sorted(by_suite.items())},
        "by_category": {k: _rate(v) for k, v in sorted(by_category.items())},
        "grader_pass_rates": grader_pass_rates(trials),
        "tasks": summaries,
    }
