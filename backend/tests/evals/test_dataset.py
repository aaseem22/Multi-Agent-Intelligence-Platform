from collections import Counter

import pytest

from app.evals.contracts import Dataset, EvalTask, ExpectedBehaviour, RequiredFact, RunConfig
from app.evals.datasets import DatasetError, check_dataset, load_dataset, select_tasks
from app.evals.facts import FactContext, TemplateError
from app.evals.validate import configuration_problems, validate_dataset

SCENARIOS = {
    "as_of": "2026-10-11",
    "currency": "INR",
    "scenarios": [
        {"id": "over_budget", "project_name": "Customer Portal", "budget": 3240000.0},
        {"id": "understaffed", "overlapping_leave_window": ["2026-10-16", "2026-11-02"]},
    ],
}


@pytest.fixture(scope="module")
def golden() -> Dataset:
    return load_dataset("golden")


def test_golden_loads_and_is_balanced(golden: Dataset) -> None:
    assert golden.version == "1.0.1"
    assert 25 <= len(golden.tasks) <= 35
    suites = Counter(t.suite for t in golden.tasks)
    assert suites["regression"] >= 10 and suites["capability"] >= 10
    clarify = [t.expected.clarification for t in golden.tasks if "clarification" in t.graders]
    assert clarify.count(True) >= 2 and clarify.count(False) >= 10  # ask back and don't
    peers = Counter(t.expected.peer_messages for t in golden.tasks)
    assert peers["required"] >= 2 and peers["forbidden"] >= 2
    assert sum(t.expected.must_report_unanswered for t in golden.tasks) >= 2
    for task in golden.tasks:
        assert task.notes and task.expected.reference_answer, task.id
        assert configuration_problems(task) == [], task.id


def test_golden_covers_the_five_spec_questions(golden: Dataset) -> None:
    tags = {tag for t in golden.tasks for tag in t.tags}
    assert {f"spec-q{i}" for i in range(1, 6)} <= tags


async def test_golden_reference_answers_validate_100_percent(golden: Dataset) -> None:
    results = await validate_dataset(golden)
    failures = {r.task_id: r.problems for r in results if not r.passed}
    assert failures == {}


def test_check_dataset_rejects_unknown_graders_and_duplicates() -> None:
    task = EvalTask(
        id="x",
        suite="regression",
        category="c",
        question="q",
        expected=ExpectedBehaviour(),
        graders=["nope"],
    )
    with pytest.raises(DatasetError, match="unknown graders"):
        check_dataset(Dataset(name="d", version="1", description="", tasks=[task]))
    ok = task.model_copy(update={"graders": ["routing"]})
    with pytest.raises(DatasetError, match="duplicate"):
        check_dataset(Dataset(name="d", version="1", description="", tasks=[ok, ok]))


def test_select_tasks(golden: Dataset) -> None:
    regression = select_tasks(golden, RunConfig(suites=["regression"]))
    assert {t.suite for t in regression} == {"regression"}
    picked = select_tasks(golden, RunConfig(suites=["regression"], task_ids=["cap-refuse-revenue"]))
    assert [t.id for t in picked] == ["cap-refuse-revenue"]  # explicit ids win over suites
    with pytest.raises(DatasetError, match="unknown task ids"):
        select_tasks(golden, RunConfig(task_ids=["missing"]))


def test_load_dataset_errors() -> None:
    with pytest.raises(DatasetError):
        load_dataset("does-not-exist")
    with pytest.raises(DatasetError):
        load_dataset("../etc/passwd")


# --- templates ---


def test_template_resolution() -> None:
    ctx = FactContext(SCENARIOS, {"current_period": "2026-Q4"})
    assert ctx.resolve("{scenario.over_budget.project_name} in {db.current_period}") == (
        "Customer Portal in 2026-Q4"
    )
    assert ctx.resolve("{scenario.over_budget.budget}") == "3240000"
    assert ctx.resolve("{scenario.currency}") == "INR"
    assert ctx.resolve("{scenario.understaffed.overlapping_leave_window}") == (
        "2026-10-16, 2026-11-02"
    )
    assert ctx.resolve("no templates {here}") == "no templates {here}"
    for bad in ("{db.missing}", "{scenario.nope.x}", "{scenario.over_budget.nope}"):
        with pytest.raises(TemplateError):
            ctx.resolve(bad)


def test_resolve_task_resolves_question_facts_and_reference() -> None:
    task = EvalTask(
        id="x",
        suite="regression",
        category="c",
        question="Spend on {scenario.over_budget.project_name}?",
        expected=ExpectedBehaviour(
            required_facts=[RequiredFact(description="p", any_of=["{db.current_period}"])],
            reference_answer="{scenario.over_budget.project_name} in {db.current_period}",
        ),
        graders=["required_facts"],
    )
    resolved = FactContext(SCENARIOS, {"current_period": "2026-Q4"}).resolve_task(task)
    assert resolved.question == "Spend on Customer Portal?"
    assert resolved.expected.required_facts[0].any_of == ["2026-Q4"]
    assert resolved.expected.reference_answer == "Customer Portal in 2026-Q4"
    assert task.question.startswith("Spend on {")  # original untouched
