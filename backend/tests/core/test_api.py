"""HTTP API and SSE streaming through httpx's ASGI transport (no server, no Gemini)."""

import json

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.core.contracts import AgentCard, Plan, Skill, Subtask
from app.core.events import stream_event_adapter
from app.core.llm import override_llm
from app.core.orchestrator import Orchestrator
from app.core.registry import registry
from app.main import create_app
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
async def client():
    orchestrator = Orchestrator(checkpointer=InMemorySaver())
    app = create_app(orchestrator)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
    await orchestrator.aclose()


def parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.replace("\r\n", "\n").split("\n\n"):
        name, data = None, []
        for line in block.split("\n"):
            if line.startswith("event:"):
                name = line.removeprefix("event:").strip()
            elif line.startswith("data:"):
                data.append(line.removeprefix("data:").strip())
        if name and data:
            events.append((name, json.loads("\n".join(data))))
    return events


async def test_chat_streams_sse_events(seeded_db, client):
    plan = Plan(subtasks=[Subtask(id="t1", assigned_to="alpha", instruction="look up a")])
    register_echo_world("alpha", supervisor=EchoSupervisor(plans=[plan]))
    llm = RoutedChatModel(
        scripts={
            "alpha": [
                tool_call("alpha_lookup", {"key": "a"}),
                answer("ok", "a is A", ["alpha_store:key=a"]),
            ]
        }
    )
    with override_llm(lambda role: llm):
        response = await client.post("/api/chat", json={"message": "What is a?"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(response.text)
    names = [name for name, _ in events]
    assert names[0] == "plan" and names[-1] == "final"
    for name in ("agent_started", "tool_call", "peer_message", "agent_result", "eval_result"):
        assert name in names
    for name, data in events:
        parsed = stream_event_adapter.validate_python(data)
        assert parsed.type == name
    final = events[-1][1]
    assert final["answer"]["claims"][0]["evidence_refs"] == ["alpha_store:key=a"]

    conversation_id = final["conversation_id"]
    listing = (await client.get("/api/conversations")).json()
    assert conversation_id in [c["id"] for c in listing]
    detail = (await client.get(f"/api/conversations/{conversation_id}")).json()
    assert detail["turns"][0]["kind"] == "final"
    assert detail["turns"][0]["question"] == "What is a?"
    a2a = (await client.get(f"/api/conversations/{conversation_id}/a2a")).json()
    assert [m["type"] for m in a2a] == ["task", "result"]


async def test_chat_continues_a_conversation(seeded_db, client):
    supervisor = EchoSupervisor(
        plans=[Plan(clarification="Which one?"), Plan(clarification="Still unclear")]
    )
    register_echo_world("alpha", supervisor=supervisor)
    first = parse_sse((await client.post("/api/chat", json={"message": "hi"})).text)
    conversation_id = first[-1][1]["conversation_id"]
    second = parse_sse(
        (
            await client.post(
                "/api/chat", json={"message": "that one", "conversation_id": conversation_id}
            )
        ).text
    )
    assert second[-1][0] == "clarification"
    assert second[-1][1]["conversation_id"] == conversation_id
    assert len(supervisor.plan_calls[1][1]) == 2


async def test_chat_rejects_empty_message(client):
    response = await client.post("/api/chat", json={"message": ""})
    assert response.status_code == 422


async def test_unknown_conversation_is_404(seeded_db, client):
    assert (await client.get("/api/conversations/nope")).status_code == 404


async def test_health(seeded_db, client):
    register_echo_world("alpha", supervisor=EchoSupervisor())
    body = (await client.get("/api/health")).json()
    assert body["status"] == "ok"
    assert body["database"] is True
    assert body["agents"] == ["ceo", "alpha"]
    assert set(body) == {"status", "database", "github_token", "langfuse", "agents"}


async def test_dummy_extra_department_appears_without_core_changes(client):
    register_echo_world("alpha", "beta", supervisor=EchoSupervisor())
    cards = (await client.get("/api/agents")).json()
    assert [c["name"] for c in cards] == ["ceo", "alpha", "beta"]

    extra = make_echo_agent("legal", description="Owns contracts and compliance records.")
    registry.register(extra)
    cards = (await client.get("/api/agents")).json()
    legal = next(c for c in cards if c["name"] == "legal")
    assert AgentCard.model_validate(legal).owned_data == ["legal_store"]
    assert (
        legal["skills"][0]
        == Skill(name="lookup", description="Look up keys", example_questions=["key?"]).model_dump()
    )

    from app.core.a2a import build_ask_agent_tool

    assert "Owns contracts and compliance records." in build_ask_agent_tool("alpha").description


async def test_cors_allows_only_the_vite_origin(client):
    ok = await client.options(
        "/api/agents",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    bad = await client.options(
        "/api/agents",
        headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in bad.headers
