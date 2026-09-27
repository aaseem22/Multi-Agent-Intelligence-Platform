"""Top-level graph end to end with Echo agents and an Echo supervisor (no real departments)."""

import inspect
import json
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.core import orchestrator as orchestrator_module
from app.core.contracts import Plan, Subtask
from app.core.events import (
    AgentResultEvent,
    AgentStartedEvent,
    ClarificationEvent,
    ErrorEvent,
    EvalResultEvent,
    FinalEvent,
    PeerMessageEvent,
    PlanEvent,
)
from app.core.llm import override_llm
from app.core.orchestrator import Orchestrator
from app.data.repositories import platform
from tests.core.echo import (
    Concurrency,
    EchoSupervisor,
    RoutedChatModel,
    answer,
    register_echo_world,
)
from tests.support.fake_llm import tool_call

pytestmark = pytest.mark.usefixtures("clean_registry")


async def collect(orchestrator: Orchestrator, message: str, conversation_id: str | None = None):
    return [event async for event in orchestrator.stream(message, conversation_id)]


def of_type(events, cls):
    return [e for e in events if isinstance(e, cls)]


@pytest.fixture
async def orchestrator():
    orch = Orchestrator(checkpointer=InMemorySaver())
    await orch.start()
    yield orch
    await orch.aclose()


def lookup_then_answer(name: str, key: str):
    return [
        tool_call(f"{name}_lookup", {"key": key}),
        answer("ok", f"{key} is {key.upper()}", [f"{name}_store:key={key}"]),
    ]


async def test_parallel_dispatch_with_dependent_subtask(seeded_db, orchestrator):
    concurrency = Concurrency()
    plan = Plan(
        subtasks=[
            Subtask(id="t1", assigned_to="alpha", instruction="look up a"),
            Subtask(id="t2", assigned_to="beta", instruction="look up b"),
            Subtask(id="t3", assigned_to="gamma", instruction="combine", depends_on=["t1", "t2"]),
        ],
        rationale="two lookups then combine",
    )
    supervisor = EchoSupervisor(plans=[plan])
    register_echo_world("alpha", "beta", "gamma", supervisor=supervisor, concurrency=concurrency)

    def gamma_uses_context(messages):
        prompt = messages[-1].text
        assert "alpha_store:key=a" in prompt and "beta_store:key=b" in prompt
        return answer("ok", "combined", ["alpha_store:key=a", "beta_store:key=b"])

    llm = RoutedChatModel(
        scripts={
            "alpha": lookup_then_answer("alpha", "a"),
            "beta": lookup_then_answer("beta", "b"),
            "gamma": [gamma_uses_context],
        }
    )
    with override_llm(lambda role: llm):
        events = await collect(orchestrator, "Combine a and b")

    assert concurrency.peak == 2, "t1 and t2 should run in parallel"
    plan_events = of_type(events, PlanEvent)
    assert len(plan_events) == 1 and plan_events[0].rationale == "two lookups then combine"

    started = [e.subtask_id for e in of_type(events, AgentStartedEvent)]
    assert set(started[:2]) == {"t1", "t2"} and started[2] == "t3"

    final = of_type(events, FinalEvent)
    assert len(final) == 1 and events[-1] is final[0]
    assert {r.subtask_id for r in final[0].results} == {"t1", "t2", "t3"}
    t3 = next(r for r in final[0].results if r.subtask_id == "t3")
    assert [e.source_ref for e in t3.evidence] == ["alpha_store:key=a", "beta_store:key=b"]

    evals = of_type(events, EvalResultEvent)
    stages = sorted(e.result.stage for e in evals)
    assert stages == ["evidence"] * 3 + ["independent"] * 3 + ["self"] * 3

    messages = [e.message for e in of_type(events, PeerMessageEvent)]
    assert [m.type for m in messages].count("task") == 3
    assert [m.type for m in messages].count("result") == 3

    synth_subtasks, synth_results = supervisor.synth_calls[0]
    assert [s.id for s in synth_subtasks] == ["t1", "t2", "t3"]
    assert len(synth_results) == 3

    conversation_id = final[0].conversation_id
    detail = await platform.get_conversation(conversation_id)
    assert detail["turns"][-1]["kind"] == "final"
    assert detail["turns"][-1]["payload"]["answer"]["answer"] == final[0].answer.answer
    log = await platform.list_a2a_messages(conversation_id=conversation_id)
    assert len(log) == 6


async def test_clarification_dispatches_no_agents(seeded_db, orchestrator):
    register_echo_world(
        "alpha", supervisor=EchoSupervisor(plans=[Plan(clarification="Which area?")])
    )
    llm = RoutedChatModel(scripts={"alpha": []})
    with override_llm(lambda role: llm):
        events = await collect(orchestrator, "How are we doing?")
    assert [type(e) for e in events][-1] is ClarificationEvent
    assert events[-1].question == "Which area?"
    assert not of_type(events, AgentStartedEvent)
    assert not of_type(events, PlanEvent)
    assert llm.seen == []
    detail = await platform.get_conversation(events[-1].conversation_id)
    assert detail["turns"][-1]["kind"] == "clarification"


async def test_empty_plan_becomes_clarification(orchestrator):
    register_echo_world("alpha", supervisor=EchoSupervisor(plans=[Plan()]))
    events = await collect(orchestrator, "???")
    assert isinstance(events[-1], ClarificationEvent)


async def test_history_persists_across_turns(orchestrator):
    supervisor = EchoSupervisor(
        plans=[
            Plan(clarification="Which project?"),
            Plan(subtasks=[Subtask(id="t1", assigned_to="alpha", instruction="look up a")]),
        ]
    )
    register_echo_world("alpha", supervisor=supervisor)
    llm = RoutedChatModel(scripts={"alpha": lookup_then_answer("alpha", "a")})
    with override_llm(lambda role: llm):
        first = await collect(orchestrator, "Tell me about the project")
        conversation_id = first[-1].conversation_id
        second = await collect(orchestrator, "Project a", conversation_id)

    assert isinstance(second[-1], FinalEvent)
    assert len(second[-1].results) == 1
    question, history, cards = supervisor.plan_calls[1]
    assert question == "Project a"
    assert history == [
        {"role": "user", "content": "Tell me about the project"},
        {"role": "assistant", "content": "Which project?"},
    ]
    assert cards == ["alpha"]


async def test_unknown_agent_and_unresolvable_deps_fail_gracefully(orchestrator):
    plan = Plan(
        subtasks=[
            Subtask(id="t1", assigned_to="ghost", instruction="?"),
            Subtask(id="t2", assigned_to="alpha", instruction="x", depends_on=["t3"]),
            Subtask(id="t3", assigned_to="alpha", instruction="y", depends_on=["t2"]),
        ]
    )
    supervisor = EchoSupervisor(plans=[plan])
    register_echo_world("alpha", supervisor=supervisor)
    events = await collect(orchestrator, "q")
    final = events[-1]
    assert isinstance(final, FinalEvent)
    statuses = {r.subtask_id: (r.status, r.error) for r in final.results}
    assert statuses["t1"][0] == "failed" and "unknown agent" in statuses["t1"][1]
    assert statuses["t2"][0] == "failed" and "unresolvable" in statuses["t2"][1]
    assert statuses["t3"][0] == "failed"
    assert len(of_type(events, AgentResultEvent)) == 3


async def test_failed_agent_is_reported_and_synthesis_fallback(orchestrator):
    plan = Plan(subtasks=[Subtask(id="t1", assigned_to="alpha", instruction="x")])
    supervisor = EchoSupervisor(plans=[plan], synthesise_error=RuntimeError("synth down"))
    register_echo_world("alpha", supervisor=supervisor)
    llm = RoutedChatModel(scripts={"alpha": [ValueError("llm broke")]})
    with override_llm(lambda role: llm):
        events = await collect(orchestrator, "q")
    errors = of_type(events, ErrorEvent)
    assert errors and "synth down" in errors[0].message
    final = events[-1]
    assert isinstance(final, FinalEvent)
    assert final.results[0].status == "failed"
    assert any("alpha could not answer" in u for u in final.answer.unanswered)
    result_messages = [e.message for e in of_type(events, PeerMessageEvent)]
    assert result_messages[-1].type == "error"


async def test_planner_failure_emits_error(orchestrator):
    class BrokenSupervisor(EchoSupervisor):
        async def plan(self, question, history, cards):
            raise ValueError("planner broke")

    register_echo_world("alpha", supervisor=BrokenSupervisor())
    events = await collect(orchestrator, "q")
    assert isinstance(events[-1], ErrorEvent)
    assert "planner broke" in events[-1].message


async def test_no_supervisor_emits_error(orchestrator):
    register_echo_world("alpha")
    events = await collect(orchestrator, "q")
    assert isinstance(events[-1], ErrorEvent)


async def test_peer_message_inside_orchestrated_run(seeded_db, orchestrator):
    plan = Plan(subtasks=[Subtask(id="t1", assigned_to="alpha", instruction="ask beta")])
    register_echo_world("alpha", "beta", supervisor=EchoSupervisor(plans=[plan]))

    def cite(messages):
        return answer("ok", "from beta", [json.loads(messages[-1].text)["source_ref"]])

    llm = RoutedChatModel(
        scripts={
            "alpha": [tool_call("ask_agent", {"target": "beta", "question": "b?"}), cite],
            "beta": lookup_then_answer("beta", "b"),
        }
    )
    with override_llm(lambda role: llm):
        events = await collect(orchestrator, "q")
    types = [e.message.type for e in of_type(events, PeerMessageEvent)]
    assert types == ["task", "peer_request", "peer_response", "result"]
    final = events[-1]
    assert final.results[0].evidence[0].source_type == "peer"
    log = await platform.list_a2a_messages(conversation_id=final.conversation_id)
    assert [m.type for m in log] == types


async def test_sqlite_checkpointer_round_trips_state(tmp_path: Path, caplog):
    register_echo_world(
        "alpha",
        supervisor=EchoSupervisor(
            plans=[
                Plan(subtasks=[Subtask(id="t1", assigned_to="alpha", instruction="x")]),
                Plan(clarification="more?"),
            ]
        ),
    )
    orch = Orchestrator(checkpoint_path=str(tmp_path / "checkpoints.db"))
    llm = RoutedChatModel(scripts={"alpha": lookup_then_answer("alpha", "a")})
    try:
        with override_llm(lambda role: llm), caplog.at_level("WARNING"):
            first = await collect(orch, "q1")
            second = await collect(orch, "q2", first[-1].conversation_id)
    finally:
        await orch.aclose()
    assert isinstance(first[-1], FinalEvent) and isinstance(second[-1], ClarificationEvent)
    assert not [r for r in caplog.records if "serializ" in r.getMessage().lower()]


def test_core_names_no_department():
    from app.core import a2a, agent_runtime, observability, prompts, state

    for module in (orchestrator_module, a2a, agent_runtime, observability, prompts, state):
        source = inspect.getsource(module).lower()
        for name in ("finance", "tech agent", '"hr"', "'hr'", '"tech"', "'tech'"):
            assert name not in source, f"{module.__name__} mentions {name}"
