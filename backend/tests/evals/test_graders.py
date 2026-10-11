import pytest

from app.core import judge as judge_module
from app.core.judge import DimensionVerdict, JudgeVerdict
from app.evals.contracts import EvalTask, ExpectedBehaviour, RequiredFact
from app.evals.graders import GRADERS, GradingContext, is_skipped, run_graders
from app.evals.transcript import TrialView
from tests.evals.conftest import event, final_event, peer_event, plan_event, result_event


def make_task(
    graders: list[str] | None = None, tags: list[str] | None = None, **expected
) -> EvalTask:
    return EvalTask(
        id="t",
        suite="regression",
        category="single-domain",
        question="What is the spend on Customer Portal?",
        expected=ExpectedBehaviour(**expected),
        graders=graders or [],
        tags=tags or [],
    )


async def grade(name: str, task: EvalTask, events: list[dict], **view) -> object:
    ctx = GradingContext(task=task, trial=TrialView(events, **view))
    return await GRADERS[name].grade(ctx)


ANSWERED = [
    plan_event("finance"),
    event("agent_started", agent="finance", subtask_id="t1", mode="task", instruction="x"),
    result_event("finance", ["budgets:id=1", "expenses:project_id=1"]),
    final_event(
        "Customer Portal spent ₹43.74 lakh against ₹32.4 lakh (35% over).",
        claims=[("spent 4374000", ["expenses:project_id=1"]), ("budget", ["budgets:id=1"])],
    ),
]


# --- routing ---


async def test_routing_passes_for_required_single_agent() -> None:
    task = make_task(agents_required=["finance"], agents_forbidden=["hr"], max_agents=1)
    result = await grade("routing", task, ANSWERED)
    assert result.passed and result.score == 1.0


async def test_routing_counts_peer_recipients_and_gives_partial_credit() -> None:
    task = make_task(agents_required=["finance"], agents_forbidden=["hr"], max_agents=1)
    events = [*ANSWERED, peer_event("finance", "hr")]
    result = await grade("routing", task, events)
    assert not result.passed
    assert result.score == pytest.approx(1 / 3, abs=1e-3)
    assert result.details["involved"] == ["finance", "hr"]


async def test_routing_ignores_refused_peer_requests() -> None:
    task = make_task(agents_forbidden=["hr"])
    result = await grade("routing", task, [*ANSWERED, peer_event("finance", "hr", refused=True)])
    assert result.passed


# --- clarification ---


async def test_clarification_expected_and_given() -> None:
    task = make_task(clarification=True)
    result = await grade("clarification", task, [event("clarification", question="Which area?")])
    assert result.passed


async def test_clarification_expected_but_agents_dispatched() -> None:
    task = make_task(clarification=True)
    result = await grade("clarification", task, ANSWERED)
    assert not result.passed and result.score == 0.0


async def test_clarification_not_wanted_but_asked() -> None:
    task = make_task(clarification=False)
    result = await grade("clarification", task, [event("clarification", question="Which?")])
    assert not result.passed
    assert (await grade("clarification", task, ANSWERED)).passed


# --- peer expectation ---


@pytest.mark.parametrize(
    ("expectation", "events", "passed"),
    [
        ("required", [peer_event("tech", "hr")], True),
        ("required", [peer_event("tech", "hr", refused=True)], False),
        ("required", [], False),
        ("forbidden", [], True),
        ("forbidden", [peer_event("tech", "hr", refused=True)], False),
        ("any", [peer_event("tech", "hr")], True),
    ],
)
async def test_peer_expectation(expectation: str, events: list, passed: bool) -> None:
    result = await grade("peer_expectation", make_task(peer_messages=expectation), events)
    assert result.passed is passed


# --- facts ---


async def test_required_facts_partial_credit_and_number_normalisation() -> None:
    task = make_task(
        required_facts=[
            RequiredFact(description="actual", any_of=["₹4,374,000"]),
            RequiredFact(description="pct", any_of=["35.0%"]),
            RequiredFact(description="lead", any_of=["Gayathri Chaudry"]),
        ]
    )
    result = await grade("required_facts", task, ANSWERED)
    assert not result.passed
    assert result.score == pytest.approx(2 / 3, abs=1e-3)
    assert result.details["found"]["lead"] is None


async def test_required_facts_read_claims_and_unanswered_too() -> None:
    task = make_task(required_facts=[RequiredFact(description="d", any_of=["not tracked"])])
    events = [final_event("short", unanswered=["Revenue is not tracked by any agent"])]
    assert (await grade("required_facts", task, events)).passed


async def test_forbidden_facts() -> None:
    task = make_task(
        forbidden_facts=[
            RequiredFact(description="invented lead", any_of=["John Smith"]),
            RequiredFact(description="wrong figure", any_of=["₹9,999,999"]),
        ]
    )
    clean = await grade("forbidden_facts", task, ANSWERED)
    assert clean.passed
    dirty = await grade("forbidden_facts", task, [final_event("John Smith leads it")])
    assert not dirty.passed and dirty.score == 0.5


# --- evidence ---


async def test_evidence_valid_all_refs_known() -> None:
    assert (await grade("evidence_valid", make_task(), ANSWERED)).passed


async def test_evidence_valid_flags_invented_and_missing_refs() -> None:
    events = [
        result_event("finance", ["budgets:id=1"]),
        final_event(
            "x",
            claims=[("ok", ["budgets:id=1"]), ("bad", ["budgets:id=999"]), ("none", [])],
        ),
    ]
    result = await grade("evidence_valid", make_task(), events)
    assert not result.passed
    assert result.score == pytest.approx(1 / 3, abs=1e-3)
    assert result.details["invalid"] == ["budgets:id=999"]


async def test_evidence_valid_without_final() -> None:
    clar = [event("clarification", question="?")]
    assert (await grade("evidence_valid", make_task(clarification=True), clar)).passed
    assert not (await grade("evidence_valid", make_task(), clar)).passed


# --- unanswered / errors / efficiency ---


@pytest.mark.parametrize(
    ("events", "passed"),
    [
        ([final_event("x", unanswered=["revenue: no agent owns it"])], True),
        ([event("clarification", question="Revenue is not something we track; what else?")], True),
        ([final_event("Revenue data is not available to any agent.")], True),
        ([final_event("Revenue was ₹12 crore.")], False),
    ],
)
async def test_unanswered_reported(events: list, passed: bool) -> None:
    task = make_task(must_report_unanswered=True)
    assert (await grade("unanswered_reported", task, events)).passed is passed


async def test_no_errors() -> None:
    assert (await grade("no_errors", make_task(), ANSWERED)).passed
    failed = [result_event("hr", [], status="failed", error="boom"), final_event("x")]
    assert not (await grade("no_errors", make_task(), failed)).passed
    allowed = make_task(tags=["allow-agent-failure"])
    assert (await grade("no_errors", allowed, failed)).passed
    errored = [event("error", message="Planning failed")]
    assert not (await grade("no_errors", make_task(), errored)).passed


async def test_efficiency_is_informational() -> None:
    task = make_task(tags=["budget:llm=10", "budget:seconds=60"])
    result = await grade("efficiency", task, ANSWERED, llm_calls=20, duration_ms=30_000)
    assert result.score == pytest.approx(0.75)
    assert result.details["informational"] is True
    assert result.weight == 0.25


# --- model graders ---


def verdict(passed: bool, score: float | None, error: str | None = None) -> JudgeVerdict:
    return JudgeVerdict(
        rubric="r",
        passed=passed,
        score=score,
        dimensions=[
            DimensionVerdict(dimension="groundedness", verdict="pass", score=1.0, reasoning="ok")
        ],
        model="judge-model",
        error=error,
    )


async def test_model_grader_skipped_when_judge_not_implemented(monkeypatch) -> None:
    async def not_implemented(rubric, item):
        raise NotImplementedError

    monkeypatch.setattr(judge_module, "judge", not_implemented)
    result = await grade("answer_groundedness", make_task(), ANSWERED)
    assert is_skipped(result) and result.weight == 0.0 and result.passed


async def test_model_grader_skipped_on_error_verdict(monkeypatch) -> None:
    async def erroring(rubric, item):
        return verdict(True, None, error="quota")

    monkeypatch.setattr(judge_module, "judge", erroring)
    result = await grade("answer_completeness", make_task(), ANSWERED)
    assert is_skipped(result)
    assert "quota" in result.reasons[0]


async def test_model_grader_uses_verdict_and_reference(monkeypatch) -> None:
    seen = {}

    async def fake(rubric, item):
        seen["rubric"], seen["item"] = rubric, item
        return verdict(False, 0.4)

    monkeypatch.setattr(judge_module, "judge", fake)
    task = make_task(reference_answer="Customer Portal is 35% over budget.")
    result = await grade("reference_match", task, ANSWERED)
    assert not is_skipped(result)
    assert not result.passed and result.score == 0.4 and result.judge is not None
    assert seen["item"].reference_answer == "Customer Portal is 35% over budget."
    assert {e.source_ref for e in seen["item"].evidence} == {
        "budgets:id=1",
        "expenses:project_id=1",
    }
    assert seen["rubric"].name == "final_answer_reference_match"


async def test_model_grader_skipped_when_disabled() -> None:
    ctx = GradingContext(task=make_task(), trial=TrialView(ANSWERED), judge_enabled=False)
    result = await GRADERS["answer_groundedness"].grade(ctx)
    assert is_skipped(result)


async def test_run_graders_survives_a_crashing_grader(monkeypatch) -> None:
    async def boom(self, ctx):
        raise RuntimeError("bug")

    monkeypatch.setattr(type(GRADERS["routing"]), "grade", boom)
    [result] = await run_graders(["routing"], GradingContext(task=make_task(), trial=TrialView([])))
    assert not result.passed and "bug" in result.reasons[0]
