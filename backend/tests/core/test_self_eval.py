"""Live self-evaluation: deterministic self_check, independent_eval via the (fake) judge, the
recovery router, and the eval_gate retry loop end to end with Echo agents. No network."""

from datetime import timedelta

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.core import eval_hooks, llm
from app.core import judge as judge_module
from app.core.config import get_settings
from app.core.contracts import AgentResult, EvalResult, Evidence, Plan, Subtask, utcnow
from app.core.events import AgentStartedEvent, EvalResultEvent, FinalEvent, RecoveryEvent
from app.core.llm import override_judge_llm, override_llm
from app.core.orchestrator import Orchestrator
from app.data.repositories import platform
from tests.core.echo import EchoSupervisor, RoutedChatModel, answer, register_echo_world
from tests.core.fake_judge import ALL_PASS, GROUNDEDNESS_FAIL, FakeJudgeModel, verdict
from tests.support.fake_llm import tool_call

SUBTASK = Subtask(id="t1", assigned_to="finance", instruction="Spend vs budget for Portal?")
EVIDENCE = [
    Evidence(
        source_type="db",
        source_ref="budgets:id=7",
        summary="Customer Portal 2026-Q4 budget",
        data={"amount": 500000, "period": "2026-Q4"},
    ),
    Evidence(
        source_type="db",
        source_ref="expenses:project_id=3",
        summary="Customer Portal spend 2026-Q4 across 14 expenses",
        data={"total": 452300, "expense_ids": [1, 2, 3]},
    ),
]


def result(answer_text: str, status: str = "ok", evidence=None) -> AgentResult:
    return AgentResult(
        agent="finance",
        subtask_id="t1",
        status=status,  # type: ignore[arg-type]
        answer=answer_text,
        evidence=EVIDENCE if evidence is None else evidence,
        peer_messages=[],
    )


@pytest.fixture
def judge_on(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "eval_judge_enabled", True)
    monkeypatch.setattr(settings, "judge_provider", "groq")
    llm.get_judge_limiter.cache_clear()
    judge_module.reset_judge_usage()


# --- self_check (deterministic) ---


async def test_self_check_passes_when_figures_trace_to_evidence():
    text = (
        "In 2026-Q4 (as of 2026-12-31) Customer Portal spent ₹4,52,300 (about ₹4.5 lakh) of a "
        "₹5,00,000 budget: 90.5% used, ₹47,700 remaining, across 14 expenses."
    )
    evaluation = await eval_hooks.self_check(result(text), SUBTASK)
    assert evaluation.passed, evaluation.reasons
    assert evaluation.score == 1.0 and evaluation.stage == "self"


async def test_self_check_reports_unmatched_figures_with_partial_credit():
    text = "Spend was INR 452,300 against INR 9,99,999 budget, with 42 engineers assigned."
    evaluation = await eval_hooks.self_check(result(text), SUBTASK)
    assert not evaluation.passed
    assert evaluation.score == pytest.approx(1 / 3, abs=1e-3)
    assert "2 of 3 figures" in evaluation.reasons[0]
    assert "9,99,999" in evaluation.reasons[0] and "42" in evaluation.reasons[0]


async def test_self_check_ignores_dates_years_and_single_digits():
    text = "Between 2026-07-01 and 2026-09-30 (Q3 2026) project 3 had 2 open issues."
    evaluation = await eval_hooks.self_check(result(text, evidence=[]), SUBTASK)
    assert evaluation.passed and evaluation.score == 1.0


async def test_self_check_structural_rules():
    empty = await eval_hooks.self_check(result("  "), SUBTASK)
    assert not empty.passed and "answer is empty" in empty.reasons[0]
    blank_ref = Evidence(source_type="db", source_ref=" ", summary="x")
    unresolved = await eval_hooks.self_check(result("Fine.", evidence=[blank_ref]), SUBTASK)
    assert not unresolved.passed and "no source_ref" in unresolved.reasons[0]
    failed = await eval_hooks.self_check(result("", status="failed"), SUBTASK)
    assert failed.passed


# --- independent_eval ---


async def test_independent_eval_disabled_by_default_in_tests():
    evaluation, verdict_ = await eval_hooks.independent_eval_detailed(result("ok"), SUBTASK)
    assert evaluation.passed and verdict_ is None and evaluation.reasons == ["judge disabled"]


async def test_independent_eval_uses_judge_verdict(judge_on):
    fake = FakeJudgeModel([GROUNDEDNESS_FAIL])
    with override_judge_llm(lambda: fake):
        evaluation, detail = await eval_hooks.independent_eval_detailed(
            result("Spend was INR 452,300."), SUBTASK
        )
    assert detail is not None and not detail.passed
    assert not evaluation.passed and evaluation.stage == "independent"
    assert evaluation.score == detail.score
    assert evaluation.reasons == ["groundedness: groundedness fail"]
    assert SUBTASK.instruction in fake.calls[0][1].text


async def test_independent_eval_skips_failed_results_and_survives_judge_errors(judge_on):
    fake = FakeJudgeModel([RuntimeError("groq down")])
    with override_judge_llm(lambda: fake):
        skipped, none = await eval_hooks.independent_eval_detailed(result("", "failed"), SUBTASK)
        broken, detail = await eval_hooks.independent_eval_detailed(result("x"), SUBTASK)
    assert skipped.passed and none is None and not fake.calls[1:]
    assert broken.passed and detail is not None and detail.error
    assert broken.reasons[0].startswith("judge unavailable: ")


def test_recovery_router(monkeypatch: pytest.MonkeyPatch):
    failed = EvalResult(passed=False, stage="independent", reasons=["x"])
    passed = EvalResult(passed=True, stage="self")
    monkeypatch.setattr(get_settings(), "eval_recovery", "retry")
    assert eval_hooks.recovery_router(failed) == "retry"
    assert eval_hooks.recovery_router(passed) == "pass"
    monkeypatch.setattr(get_settings(), "eval_recovery", "observe")
    assert eval_hooks.recovery_router(failed) == "pass"


# --- eval_gate recovery, end to end with Echo agents ---


@pytest.fixture
async def orchestrator(clean_registry):
    orch = Orchestrator(checkpointer=InMemorySaver())
    await orch.start()
    yield orch
    await orch.aclose()


@pytest.fixture
def recovery_on(monkeypatch: pytest.MonkeyPatch, judge_on) -> None:
    monkeypatch.setattr(get_settings(), "eval_recovery", "retry")
    monkeypatch.setattr(get_settings(), "eval_max_retries", 1)


def alpha_run(text: str) -> list:
    return [
        tool_call("alpha_lookup", {"key": "a"}),
        answer("ok", text, ["alpha_store:key=a"]),
    ]


async def run_alpha(orchestrator: Orchestrator, scripts: list, judge_outputs: list):
    plan = Plan(subtasks=[Subtask(id="t1", assigned_to="alpha", instruction="look up a")])
    register_echo_world("alpha", supervisor=EchoSupervisor(plans=[plan]))
    chat = RoutedChatModel(scripts={"alpha": scripts})
    fake_judge = FakeJudgeModel(judge_outputs)
    since = utcnow() - timedelta(seconds=1)
    with override_llm(lambda role: chat), override_judge_llm(lambda: fake_judge):
        events = [e async for e in orchestrator.stream("look up a")]
    request_id = events[0].request_id
    records = [
        r for r in await platform.list_eval_records(since=since) if r["request_id"] == request_id
    ]
    return events, chat, fake_judge, records


def of_type(events, cls):
    return [e for e in events if isinstance(e, cls)]


async def test_retry_happens_once_with_feedback_and_passing_result_wins(
    seeded_db, orchestrator, recovery_on
):
    events, chat, fake_judge, records = await run_alpha(
        orchestrator,
        alpha_run("a is A, probably") + alpha_run("a is A"),
        [GROUNDEDNESS_FAIL, ALL_PASS],
    )
    recoveries = of_type(events, RecoveryEvent)
    assert [(r.action, r.attempt) for r in recoveries] == [("retry", 2)]
    assert recoveries[0].feedback.startswith("- Remove the unsupported figure.")
    assert len(of_type(events, AgentStartedEvent)) == 2

    retry_prompt = [m for name, m in chat.seen if name == "alpha"][2][-1].text
    assert "Reviewer feedback from a previous attempt" in retry_prompt
    assert "Remove the unsupported figure." in retry_prompt

    independent = [e for e in of_type(events, EvalResultEvent) if e.result.stage == "independent"]
    assert [(e.attempt, e.result.passed) for e in independent] == [(1, False), (2, True)]
    assert independent[0].judge is not None and independent[0].judge.dimensions
    self_events = [e for e in of_type(events, EvalResultEvent) if e.result.stage == "self"]
    assert [e.attempt for e in self_events] == [1, 2]

    final = of_type(events, FinalEvent)[0]
    assert final.results[0].answer == "a is A" and final.results[0].status == "ok"

    kinds = sorted((r["kind"], r["stage"] or r["action"], r["attempt"]) for r in records)
    assert kinds == [
        ("eval", "evidence", 1),
        ("eval", "evidence", 2),
        ("eval", "independent", 1),
        ("eval", "independent", 2),
        ("eval", "self", 1),
        ("eval", "self", 2),
        ("recovery", "retry", 2),
    ]
    judged = next(r for r in records if r["stage"] == "independent" and r["attempt"] == 1)
    assert judged["payload"]["judge"]["dimensions"][0]["dimension"] == "groundedness"
    assert judged["passed"] is False


async def test_retry_stops_after_limit_and_keeps_better_result(
    seeded_db, orchestrator, recovery_on
):
    first = verdict("Fix it.", groundedness="fail", completeness="pass", scope="pass")  # 0.6
    worse = verdict("Fix more.", groundedness="fail", completeness="fail", scope="pass")  # 0.2
    events, _, fake_judge, records = await run_alpha(
        orchestrator,
        alpha_run("first answer") + alpha_run("second answer"),
        [first, worse],
    )
    assert len(fake_judge.calls) == 2  # exactly one retry
    assert len(of_type(events, AgentStartedEvent)) == 2
    assert [(r.action, r.attempt) for r in of_type(events, RecoveryEvent)] == [
        ("retry", 2),
        ("give_up", 2),
    ]
    final = of_type(events, FinalEvent)[0].results[0]
    assert final.answer == "first answer"  # 0.6 beats 0.2
    assert final.status == "partial" and final.error.startswith("Failed self-evaluation")
    assert sorted(r["action"] for r in records if r["kind"] == "recovery") == ["give_up", "retry"]


async def test_observe_mode_never_retries(seeded_db, orchestrator, judge_on, monkeypatch):
    monkeypatch.setattr(get_settings(), "eval_recovery", "observe")
    events, _, fake_judge, records = await run_alpha(
        orchestrator, alpha_run("a is A"), [GROUNDEDNESS_FAIL]
    )
    assert not of_type(events, RecoveryEvent)
    assert len(of_type(events, AgentStartedEvent)) == 1
    final = of_type(events, FinalEvent)[0].results[0]
    assert final.status == "ok"
    assert not [r for r in records if r["kind"] == "recovery"]
    independent = next(r for r in records if r["stage"] == "independent")
    assert independent["passed"] is False


async def test_judge_outage_does_not_block_or_retry(seeded_db, orchestrator, recovery_on):
    events, _, _, _ = await run_alpha(orchestrator, alpha_run("a is A"), [RuntimeError("boom")])
    assert not of_type(events, RecoveryEvent)
    independent = [e for e in of_type(events, EvalResultEvent) if e.result.stage == "independent"]
    assert independent[0].result.passed and independent[0].judge.error
    assert of_type(events, FinalEvent)[0].results[0].status == "ok"
