"""ask_agent guards and end-to-end peer delegation with Echo agents."""

import json

import pytest

from app.core import a2a
from app.core.a2a import ask_agent, build_ask_agent_tool, check_guards
from app.core.config import get_settings
from app.core.context import AgentInvocation, invocation_scope
from app.core.events import AgentResultEvent, AgentStartedEvent, PeerMessageEvent
from app.core.llm import override_llm
from app.data.repositories import platform
from tests.core.echo import (
    EchoSupervisor,
    RoutedChatModel,
    answer,
    make_echo_agent,
    register_echo_world,
)
from tests.support.fake_llm import tool_call

pytestmark = pytest.mark.usefixtures("clean_registry")


@pytest.fixture
def world():
    register_echo_world("alpha", "beta", "gamma", supervisor=EchoSupervisor())
    from app.core.registry import registry

    registry.register(make_echo_agent("closed", accepts_peer_requests=False))


# --- pure guard checks ---


def test_valid_request_passes(world):
    assert check_guards("alpha", "beta", 1, ["alpha"], 0) is None


def test_self_call_is_refused(world):
    assert "self-call" in check_guards("alpha", "alpha", 1, ["alpha"], 0)


def test_supervisor_target_is_refused(world):
    assert "supervisor" in check_guards("alpha", "ceo", 1, ["alpha"], 0)


def test_unknown_target_is_refused(world):
    reason = check_guards("alpha", "nobody", 1, ["alpha"], 0)
    assert "unknown agent 'nobody'" in reason
    assert "beta" in reason and "closed" not in reason


def test_target_not_accepting_peer_requests_is_refused(world):
    assert "does not accept" in check_guards("alpha", "closed", 1, ["alpha"], 0)


def test_cycle_is_refused(world):
    assert "cycle" in check_guards("beta", "alpha", 2, ["alpha", "beta"], 0)


def test_hop_limit_is_refused(world, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_peer_hops", 2)
    assert check_guards("beta", "gamma", 2, ["alpha", "beta"], 0) is None
    register_echo_world("delta")
    assert "hop limit" in check_guards("gamma", "delta", 3, ["alpha", "beta", "gamma"], 0)


def test_call_limit_is_refused(world, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_peer_calls_per_agent", 3)
    assert check_guards("alpha", "beta", 1, ["alpha"], 2) is None
    assert "call limit" in check_guards("alpha", "beta", 1, ["alpha"], 3)


# --- ask_agent behaviour ---


async def test_refusal_is_returned_not_raised_and_streamed(world, request_ctx):
    invocation = AgentInvocation(agent="alpha", subtask_id="t1", mode="task")
    with invocation_scope(invocation):
        reply = await ask_agent("alpha", "alpha", "hello?")
    assert reply.startswith("REFUSED: self-call")
    events = request_ctx.drain()
    assert len(events) == 1 and isinstance(events[0], PeerMessageEvent)
    assert events[0].refused and "self-call" in events[0].refusal_reason
    assert events[0].message.payload["refused"] is True
    assert events[0].message.id in invocation.peer_messages
    assert request_ctx.ctx.peer_calls["alpha"] == 0


async def test_per_agent_call_limit_across_a_request(world, request_ctx, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_peer_calls_per_agent", 1)
    llm = RoutedChatModel(scripts={"beta": [answer("ok", "b1")]})
    invocation = AgentInvocation(agent="alpha", subtask_id="t1", mode="task")
    with override_llm(lambda role: llm), invocation_scope(invocation):
        first = await ask_agent("alpha", "beta", "q1")
        second = await ask_agent("alpha", "beta", "q2")
    assert json.loads(first)["answer"] == "b1"
    assert second.startswith("REFUSED: call limit")


async def test_hop_limit_through_invocation(world, request_ctx, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_peer_hops", 1)
    invocation = AgentInvocation(
        agent="beta", subtask_id="t1/beta", mode="peer", hop_count=1, chain=["alpha"]
    )
    with invocation_scope(invocation):
        reply = await ask_agent("beta", "gamma", "q")
    assert reply.startswith("REFUSED: hop limit")


async def test_cycle_through_invocation(world, request_ctx):
    invocation = AgentInvocation(
        agent="beta", subtask_id="t1/beta", mode="peer", hop_count=1, chain=["alpha"]
    )
    with invocation_scope(invocation):
        reply = await ask_agent("beta", "alpha", "q")
    assert reply.startswith("REFUSED: cycle")


def test_tool_description_is_generated_from_registry(world):
    tool = build_ask_agent_tool("alpha")
    assert tool is not None and tool.name == "ask_agent"
    assert "Owns the beta store" in tool.description
    assert "- gamma (Gamma)" in tool.description
    assert "- alpha " not in tool.description
    assert "closed" not in tool.description
    assert "ceo" not in tool.description


def test_no_tool_without_peers(clean_registry):
    register_echo_world("solo")
    assert build_ask_agent_tool("solo") is None


def test_a2a_module_names_no_department():
    import inspect

    source = inspect.getsource(a2a).lower()
    for name in ("finance", '"hr"', "'hr'", "tech"):
        assert name not in source


async def test_peer_delegation_end_to_end(seeded_db, request_ctx):
    agents = register_echo_world("alpha", "beta", supervisor=EchoSupervisor())

    def cite_peer(messages):
        reply = json.loads(messages[-1].text)
        assert reply["from"] == "beta"
        assert reply["peer_evidence"][0]["source_ref"] == "beta_store:key=x"
        return answer("ok", f"beta says {reply['answer']}", [reply["source_ref"]])

    llm = RoutedChatModel(
        scripts={
            "alpha": [
                tool_call("ask_agent", {"target": "beta", "question": "what is x?"}),
                cite_peer,
            ],
            "beta": [
                tool_call("beta_lookup", {"key": "x"}),
                answer("ok", "x is X", ["beta_store:key=x"]),
            ],
        }
    )
    with override_llm(lambda role: llm):
        result = await agents["alpha"].run("Ask beta about x", subtask_id="t1")

    assert result.status == "ok"
    assert len(result.evidence) == 1
    evidence = result.evidence[0]
    assert evidence.source_type == "peer"
    assert evidence.source_ref.startswith("peer:beta:msg_")
    assert evidence.data["peer_evidence"][0]["source_ref"] == "beta_store:key=x"
    assert len(result.peer_messages) == 2

    beta_system = next(m for name, m in llm.seen if name == "beta")[0].text
    assert "Mode: peer request" in beta_system

    events = request_ctx.drain()
    peer_events = [e for e in events if isinstance(e, PeerMessageEvent)]
    assert [e.message.type for e in peer_events] == ["peer_request", "peer_response"]
    request, response = (e.message for e in peer_events)
    assert (request.sender, request.recipient, request.hop_count, request.chain) == (
        "alpha",
        "beta",
        1,
        ["alpha"],
    )
    assert response.payload["in_reply_to"] == request.id
    assert response.chain == ["alpha", "beta"]
    assert evidence.source_ref == f"peer:beta:{response.id}"
    started = [(e.agent, e.mode) for e in events if isinstance(e, AgentStartedEvent)]
    assert started == [("alpha", "task"), ("beta", "peer")]
    modes = [(e.result.agent, e.mode) for e in events if isinstance(e, AgentResultEvent)]
    assert modes == [("beta", "peer"), ("alpha", "task")]

    logged = await platform.list_a2a_messages(request_id="req-test")
    assert [m.id for m in logged] == [request.id, response.id]
    assert request_ctx.ctx.peer_calls["alpha"] == 1
