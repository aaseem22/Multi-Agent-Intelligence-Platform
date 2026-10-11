"""Reference validation: prove every task is solvable and its graders are configured, by grading
the task's own reference answer through the fact graders on a synthetic transcript. No LLM.

A task fails validation when its templates do not resolve, its reference answer misses one of its
required facts or states a forbidden one, or its grader list does not match its expectations
(for example required facts without the required_facts grader). Must be 100% before a run."""

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.data import db
from app.evals.contracts import Dataset, EvalTask
from app.evals.facts import FactContext, TemplateError, build_context
from app.evals.graders import GradingContext, run_graders
from app.evals.transcript import TrialView

FACT_GRADERS = ("required_facts", "forbidden_facts")


@dataclass
class TaskValidation:
    task_id: str
    passed: bool
    problems: list[str] = field(default_factory=list)
    resolved_question: str = ""


def synthetic_transcript(task: EvalTask) -> list[dict[str, Any]]:
    """A transcript in which the system answered exactly with the reference answer."""
    envelope = {"request_id": "validate", "conversation_id": "validate"}
    expected = task.expected
    if expected.clarification:
        return [{**envelope, "type": "clarification", "question": expected.reference_answer}]
    subtasks = [
        {"id": f"t{i}", "assigned_to": agent, "instruction": task.question, "depends_on": []}
        for i, agent in enumerate(expected.agents_required or ["reference"], start=1)
    ]
    return [
        {**envelope, "type": "plan", "subtasks": subtasks, "rationale": "reference"},
        {
            **envelope,
            "type": "final",
            "answer": {"answer": expected.reference_answer, "claims": [], "unanswered": []},
            "results": [],
            "trace_url": None,
        },
    ]


def configuration_problems(task: EvalTask) -> list[str]:
    expected, graders = task.expected, set(task.graders)
    problems: list[str] = []
    if not expected.reference_answer.strip():
        problems.append("no reference_answer")
    if expected.required_facts and "required_facts" not in graders:
        problems.append("required_facts set but the required_facts grader is not listed")
    if expected.forbidden_facts and "forbidden_facts" not in graders:
        problems.append("forbidden_facts set but the forbidden_facts grader is not listed")
    if expected.must_report_unanswered and "unanswered_reported" not in graders:
        problems.append("must_report_unanswered but unanswered_reported is not listed")
    if expected.clarification and "clarification" not in graders:
        problems.append("clarification expected but the clarification grader is not listed")
    routing = (
        expected.agents_required or expected.agents_forbidden or expected.max_agents is not None
    )
    if routing and "routing" not in graders:
        problems.append("routing expectations set but the routing grader is not listed")
    if expected.peer_messages != "any" and "peer_expectation" not in graders:
        problems.append("peer expectation set but the peer_expectation grader is not listed")
    if "reference_match" in graders and not expected.reference_answer.strip():
        problems.append("reference_match needs a reference_answer")
    return problems


async def validate_task(task: EvalTask, facts: FactContext) -> TaskValidation:
    try:
        resolved = facts.resolve_task(task)
    except TemplateError as exc:
        return TaskValidation(task.id, False, [f"template error: {exc}"])
    problems = configuration_problems(resolved)
    names = [g for g in FACT_GRADERS if g in resolved.graders]
    if resolved.expected.must_report_unanswered:
        names.append("unanswered_reported")
    view = TrialView(synthetic_transcript(resolved))
    for result in await run_graders(names, GradingContext(task=resolved, trial=view)):
        if not result.passed:
            problems += [f"{result.grader}: {r}" for r in result.reasons if "FAIL" in r]
    return TaskValidation(task.id, not problems, problems, resolved.question)


async def validate_dataset(
    dataset: Dataset, scenarios: dict[str, Any] | None = None
) -> list[TaskValidation]:
    """Validate against a freshly seeded fixture database (or the configured one when scenarios
    are passed in by a caller that already seeded it)."""
    if scenarios is not None:
        facts = await build_context(scenarios)
        return [await validate_task(t, facts) for t in dataset.tasks]
    from app.evals.runner import fixture_settings, seed_fixture_database

    previous = db._url_override
    with tempfile.TemporaryDirectory(prefix="evals-validate-") as tmp, fixture_settings():
        try:
            seeded = await seed_fixture_database(Path(tmp))
            facts = await build_context(seeded)
            return [await validate_task(t, facts) for t in dataset.tasks]
        finally:
            await db.dispose_engine()
            db.configure_database(previous)
