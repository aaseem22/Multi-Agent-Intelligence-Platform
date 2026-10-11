"""Runner end to end, in-process (no subprocess, no network): a tiny dataset answered by scripted
Echo agents, graded, aggregated and written to disk exactly as the CLI would."""

import json
from pathlib import Path

import pytest

from app.core import judge as judge_module
from app.core.contracts import Plan, Subtask
from app.core.llm import override_llm
from app.core.registry import registry
from app.data import db
from app.evals.contracts import RunConfig
from app.evals.runner import create_run, execute_run
from app.evals.storage import RunStore
from tests.core.echo import EchoSupervisor, RoutedChatModel, answer, register_echo_world
from tests.support.fake_llm import tool_call

TINY_DATASET = {
    "name": "tiny",
    "version": "0.1.0",
    "description": "two tasks for the runner test",
    "tasks": [
        {
            "id": "echo-001",
            "suite": "regression",
            "category": "single-domain",
            "question": "Look up a for {scenario.over_budget.project_name}",
            "expected": {
                "agents_required": ["alpha"],
                "max_agents": 1,
                "required_facts": [{"description": "value", "any_of": ["A"]}],
                "reference_answer": "a is A",
            },
            "graders": [
                "routing",
                "clarification",
                "required_facts",
                "evidence_valid",
                "no_errors",
                "efficiency",
                "answer_groundedness",
            ],
        },
        {
            "id": "echo-002",
            "suite": "capability",
            "category": "clarification",
            "question": "How are we doing?",
            "expected": {"clarification": True, "max_agents": 0, "reference_answer": "Which area?"},
            "graders": ["clarification", "routing", "no_errors"],
        },
    ],
}


@pytest.fixture
def datasets_dir(tmp_path: Path) -> Path:
    path = tmp_path / "datasets"
    path.mkdir()
    (path / "tiny.json").write_text(json.dumps(TINY_DATASET))
    return path


@pytest.fixture
def echo_world(isolated_registry):
    registry.clear()
    plan = Plan(subtasks=[Subtask(id="t1", assigned_to="alpha", instruction="look up a")])
    # Two trials of echo-001 plan, then echo-002 gets the default clarification.
    supervisor = EchoSupervisor(plans=[plan, plan])
    llm = RoutedChatModel(
        scripts={
            "alpha": [
                tool_call("alpha_lookup", {"key": "a"}),
                answer("ok", "a is A", ["alpha_store:key=a"]),
            ]
            * 2
        }
    )

    def load_agents() -> None:
        register_echo_world("alpha", supervisor=supervisor)

    with override_llm(lambda role: llm):
        yield load_agents, supervisor


async def test_execute_run_end_to_end(evals_root, datasets_dir, echo_world, monkeypatch) -> None:
    load_agents, supervisor = echo_world

    async def not_implemented(rubric, item):
        raise NotImplementedError

    monkeypatch.setattr(judge_module, "judge", not_implemented)
    previous_db = db._url_override
    config = RunConfig(dataset="tiny", trials=2)
    queued = create_run(config, datasets_dir=datasets_dir)
    assert queued.status == "queued" and queued.trials_total == 4

    printed: list[str] = []
    summary = await execute_run(
        queued.run_id, datasets_dir=datasets_dir, load_agents=load_agents, echo=printed.append
    )

    assert summary.status == "completed", summary.error
    assert summary.trials_done == 4
    assert summary.pass_rate == 1.0 and summary.pass_at_k == 1.0 and summary.pass_hat_k == 1.0
    assert summary.by_suite == {"capability": 1.0, "regression": 1.0}
    assert "answer_groundedness" not in summary.grader_pass_rates  # skipped judge never counts
    assert any("estimated" in line for line in printed)

    store = RunStore(queued.run_id)
    assert store.db_path.exists() and store.scenarios_path.exists()
    trials = store.list_trials()
    assert [t.trial_id for t in trials] == [
        "echo-001__0",
        "echo-001__1",
        "echo-002__0",
        "echo-002__1",
    ]
    first = trials[0]
    assert first.question == "Look up a for Customer Portal"  # template resolved from scenarios
    assert first.final_answer == "alpha: a is A"
    assert first.agents_planned == ["alpha"]
    assert first.llm_calls == 2  # two scripted chat model calls by the alpha agent
    assert first.transcript and first.transcript[-1]["type"] == "final"
    skipped = next(g for g in first.graders if g.grader == "answer_groundedness")
    assert skipped.details["skipped"] and "not implemented" in skipped.reasons[0]
    assert trials[2].clarification and trials[2].passed
    assert store.read_progress().status == "completed"
    # each trial planned once with a fresh conversation: no history carried over
    assert all(history == [] for _, history, _ in supervisor.plan_calls)
    assert db._url_override == previous_db  # data layer restored after the run


async def test_execute_run_honours_cancel_file(evals_root, datasets_dir, echo_world) -> None:
    load_agents, _ = echo_world
    queued = create_run(RunConfig(dataset="tiny"), datasets_dir=datasets_dir)
    RunStore(queued.run_id).cancel_path.write_text("cancelled")
    summary = await execute_run(
        queued.run_id, datasets_dir=datasets_dir, load_agents=load_agents, echo=lambda _: None
    )
    assert summary.status == "cancelled" and summary.trials_done == 0


async def test_execute_run_marks_failure(evals_root, datasets_dir) -> None:
    queued = create_run(RunConfig(dataset="tiny"), datasets_dir=datasets_dir)

    def broken_loader() -> None:
        raise RuntimeError("agents failed to import")

    summary = await execute_run(
        queued.run_id, datasets_dir=datasets_dir, load_agents=broken_loader, echo=lambda _: None
    )
    assert summary.status == "failed" and "agents failed to import" in summary.error
