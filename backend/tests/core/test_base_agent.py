"""DepartmentAgent.run: structured output, evidence resolution, events and failure handling."""

import pytest

from app.core.agent_runtime import _tools_for
from app.core.config import get_settings
from app.core.contracts import AgentResult, Evidence
from app.core.events import (
    AgentResultEvent,
    AgentStartedEvent,
    EvalResultEvent,
    ToolCallEvent,
)
from app.core.llm import override_llm
from tests.core.echo import RoutedChatModel, answer, register_echo_world
from tests.support.fake_llm import ScriptedChatModel, text, tool_call
from tests.support.markers import RUNTIME_READY

pytestmark = pytest.mark.usefixtures("clean_registry")


class RateLimited(Exception):
    status_code = 429


def test_runtime_is_marked_ready():
    assert RUNTIME_READY


async def test_run_returns_ok_result_with_cited_evidence(request_ctx):
    agents = register_echo_world("echo")
    llm = RoutedChatModel(
        scripts={
            "echo": [
                tool_call("echo_lookup", {"key": "alpha"}),
                answer("ok", "alpha is ALPHA", ["echo_store:key=alpha"]),
            ]
        }
    )
    with override_llm(lambda role: llm):
        result = await agents["echo"].run("What is alpha?", subtask_id="t1")

    assert result.status == "ok"
    assert result.answer == "alpha is ALPHA"
    assert [e.source_ref for e in result.evidence] == ["echo_store:key=alpha"]
    assert result.evidence[0].source_type == "db"

    events = request_ctx.drain()
    types = [type(e) for e in events]
    assert types[0] is AgentStartedEvent
    tool_events = [e for e in events if isinstance(e, ToolCallEvent)]
    assert [(e.tool, e.args) for e in tool_events] == [("echo_lookup", {"key": "alpha"})]
    evals = [e for e in events if isinstance(e, EvalResultEvent)]
    assert [e.result.stage for e in evals] == ["self"]
    assert isinstance(events[-1], AgentResultEvent) and events[-1].mode == "task"


async def test_invented_evidence_refs_are_dropped():
    agents = register_echo_world("echo")
    llm = RoutedChatModel(
        scripts={
            "echo": [
                tool_call("echo_lookup", {"key": "alpha"}),
                answer("ok", "done", ["budgets:id=999", "echo_store:key=alpha", "made:up"]),
            ]
        }
    )
    with override_llm(lambda role: llm):
        result = await agents["echo"].run("q", subtask_id="t1")
    assert [e.source_ref for e in result.evidence] == ["echo_store:key=alpha"]


async def test_no_valid_refs_falls_back_to_collected_evidence():
    agents = register_echo_world("echo")
    llm = RoutedChatModel(
        scripts={
            "echo": [
                tool_call("echo_lookup", {"key": "a"}),
                answer("ok", "done", ["nope"]),
            ]
        }
    )
    with override_llm(lambda role: llm):
        result = await agents["echo"].run("q", subtask_id="t1")
    assert [e.source_ref for e in result.evidence] == ["echo_store:key=a"]


async def test_evidence_without_any_tool_call_is_empty():
    agents = register_echo_world("echo")
    llm = RoutedChatModel(scripts={"echo": [answer("ok", "made up", ["echo_store:key=x"])]})
    with override_llm(lambda role: llm):
        result = await agents["echo"].run("q", subtask_id="t1")
    assert result.evidence == []


async def test_llm_error_returns_failed_result_instead_of_raising(request_ctx):
    agents = register_echo_world("echo")
    llm = RoutedChatModel(scripts={"echo": [ValueError("model exploded")]})
    with override_llm(lambda role: llm):
        result = await agents["echo"].run("q", subtask_id="t1")
    assert result.status == "failed"
    assert "model exploded" in (result.error or "")
    assert isinstance(request_ctx.drain()[-1], AgentResultEvent)


async def test_rate_limit_is_retried_then_succeeds():
    agents = register_echo_world("echo")
    llm = RoutedChatModel(scripts={"echo": [RateLimited("429 slow down"), answer("ok", "fine")]})
    with override_llm(lambda role: llm):
        result = await agents["echo"].run("q", subtask_id="t1")
    assert result.status == "ok"


async def test_exhausted_retries_surface_as_failed(monkeypatch):
    monkeypatch.setattr(get_settings(), "llm_max_retries", 1)
    agents = register_echo_world("echo")
    llm = RoutedChatModel(scripts={"echo": [RateLimited("429"), RateLimited("429")]})
    with override_llm(lambda role: llm):
        result = await agents["echo"].run("q", subtask_id="t1")
    assert result.status == "failed"


async def test_non_retryable_error_is_not_retried():
    agents = register_echo_world("echo")
    llm = RoutedChatModel(scripts={"echo": [ValueError("bad request"), answer("ok", "never")]})
    with override_llm(lambda role: llm):
        result = await agents["echo"].run("q", subtask_id="t1")
    assert result.status == "failed"


async def test_tool_exception_is_reported_to_the_llm():
    agents = register_echo_world("echo")

    def check_error(messages):
        assert "store unavailable" in messages[-1].text
        return answer("partial", "store down")

    llm = RoutedChatModel(
        scripts={"echo": [tool_call("echo_lookup", {"key": "boom"}), check_error]}
    )
    with override_llm(lambda role: llm):
        result = await agents["echo"].run("q", subtask_id="t1")
    assert result.status == "partial"
    assert result.answer == "store down"


async def test_missing_structured_answer_is_partial_with_last_text():
    agents = register_echo_world("echo")
    llm = ScriptedChatModel(responses=[text("plain text answer")])
    with override_llm(lambda role: llm):
        result = await agents["echo"].run("q", subtask_id="t1")
    assert result.status == "partial"
    assert result.answer == "plain text answer"


async def test_context_evidence_can_be_cited():
    agents = register_echo_world("echo")
    prior = AgentResult(
        agent="other",
        subtask_id="t0",
        status="ok",
        answer="prior answer",
        evidence=[Evidence(source_type="db", source_ref="other_store:id=1", summary="prior")],
        peer_messages=[],
    )

    def check_prompt(messages):
        assert "prior answer" in messages[-1].text
        assert "other_store:id=1" in messages[-1].text
        return answer("ok", "used prior", ["other_store:id=1"])

    llm = RoutedChatModel(scripts={"echo": [check_prompt]})
    with override_llm(lambda role: llm):
        result = await agents["echo"].run("q", subtask_id="t1", context=[prior])
    assert [e.source_ref for e in result.evidence] == ["other_store:id=1"]


def test_ask_agent_tool_only_when_peers_exist_and_hops_allow(monkeypatch):
    agents = register_echo_world("echo")
    assert [t.name for t in _tools_for(agents["echo"], "task", 0)] == ["echo_lookup"]

    register_echo_world("peer")
    assert "ask_agent" in [t.name for t in _tools_for(agents["echo"], "task", 0)]
    monkeypatch.setattr(get_settings(), "max_peer_hops", 1)
    assert "ask_agent" in [t.name for t in _tools_for(agents["echo"], "peer", 0)]
    assert "ask_agent" not in [t.name for t in _tools_for(agents["echo"], "peer", 1)]


async def test_system_prompt_includes_core_rules_and_peers():
    agents = register_echo_world("echo", "peer")
    llm = RoutedChatModel(scripts={"echo": [answer("ok", "x")]})
    with override_llm(lambda role: llm):
        await agents["echo"].run("q", subtask_id="t1")
    system = llm.seen[0][1][0].text
    assert "Rules that apply to every department agent" in system
    assert "peer (Peer)" in system
    assert "Mode: task" in system
