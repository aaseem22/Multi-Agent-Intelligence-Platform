"""Observability dashboard endpoints, with the Langfuse REST API mocked by respx (no network).

The mocks mirror the current read APIs: GET /api/public/v2/observations (cursor pagination,
`fields` groups, io as raw strings) and GET /api/public/v3/scores (trace id under `subject`).
"""

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from langgraph.checkpoint.memory import InMemorySaver

from app.core import observability_queries
from app.core.config import get_settings
from app.core.contracts import A2AMessage
from app.core.orchestrator import Orchestrator
from app.data.db import init_db
from app.data.repositories import platform
from app.main import create_app

HOST = "https://langfuse.test"
OBSERVATIONS_URL = f"{HOST}/api/public/v2/observations"
SCORES_URL = f"{HOST}/api/public/v3/scores"
pytestmark = pytest.mark.usefixtures("clean_registry")


@pytest.fixture
async def client():
    orchestrator = Orchestrator(checkpointer=InMemorySaver())
    app = create_app(orchestrator)
    transport = httpx.ASGITransport(app=app)
    await init_db()
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
    await orchestrator.aclose()


@pytest.fixture(autouse=True)
def fresh_cache():
    observability_queries.reset_cache()
    yield
    observability_queries.reset_cache()


@pytest.fixture
def langfuse_keys(no_langfuse, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "langfuse_public_key", "pk-test")
    monkeypatch.setattr(settings, "langfuse_secret_key", "sk-test")
    monkeypatch.setattr(settings, "langfuse_host", HOST)


def iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


NOW = datetime.now(UTC) - timedelta(hours=1)


def obs(obs_id, name, obs_type, start_s, end_s, parent=None, **extra):
    return {
        "id": obs_id,
        "traceId": extra.pop("trace_id", "t1"),
        "projectId": "p1",
        "name": name,
        "type": obs_type,
        "startTime": iso(NOW + timedelta(seconds=start_s)),
        "endTime": iso(NOW + timedelta(seconds=end_s)),
        "parentObservationId": parent,
        "isRootObservation": extra.pop("root", False),
        "level": extra.pop("level", "DEFAULT"),
        "statusMessage": extra.pop("statusMessage", ""),
        "usageDetails": extra.pop("usage", {}),
        "totalUsage": extra.pop("total_usage", 0),
        "totalCost": extra.pop("cost", None),
        "metadata": extra.pop("metadata", {}),
        **extra,
    }


def observations(root_level: str = "DEFAULT"):
    return [
        # The logical root points at a physical parent that is not part of the trace.
        obs("root", "stakeholder_request", "AGENT", 0, 20, "ghost", root=True, level=root_level),
        obs("plan", "plan", "CHAIN", 0.1, 2, "root"),
        obs(
            "g1",
            "ChatGoogleGenerativeAI",
            "GENERATION",
            0.2,
            1.9,
            "plan",
            total_usage=300,
            cost=0.0007,
            level="ERROR",
            statusMessage="503 UNAVAILABLE (retried)",
        ),
        obs(
            "tech", "agent:tech", "AGENT", 2, 15, "root", metadata={"agent": "tech", "hop_count": 0}
        ),
        obs("tool1", "repo_activity", "TOOL", 3, 4, "tech"),
        obs("ask", "ask_agent", "TOOL", 4, 12, "tech", metadata={"agent": "tech"}),
        obs(
            "peer",
            "a2a:tech->hr",
            "CHAIN",
            4.1,
            11,
            "ask",
            metadata={"hop_count": 1, "chain": ["tech"], "agent": "hr"},
        ),
        obs("tool2", "project_staffing", "TOOL", 5, 6, "peer", metadata={"agent": "hr"}),
        obs(
            "g2",
            "ChatGoogleGenerativeAI",
            "GENERATION",
            6,
            10,
            "peer",
            usage={"input": 100, "output": 50},
            cost=0.0005,
        ),
        obs("fin", "agent:finance", "AGENT", 2, 9, "root", level="ERROR", statusMessage="boom"),
        obs("synth", "synthesise", "CHAIN", 16, 19, "root"),
    ]


ROOT = {
    **obs("root", "stakeholder_request", "AGENT", 0, 20, "ghost", root=True),
    "input": json.dumps({"question": "Which projects are behind schedule?"}),
    "sessionId": "conv-1",
    "traceName": "stakeholder_request",
    "tags": [],
    "latency": 20.0,
}
RUN_OUTPUTS = {
    "agent:": [
        {"id": "tech", "output": json.dumps({"result": {"status": "ok"}})},
        {"id": "fin", "output": json.dumps({"result": {"status": "ok"}})},
    ],
    # io comes back as raw strings: the failed peer run must be recognised after decoding.
    "a2a:": [{"id": "peer", "output": json.dumps({"result": {"status": "failed"}})}],
}
SCORES = [
    {
        "id": "s1",
        "name": "eval_independent",
        "dataType": "BOOLEAN",
        "value": True,
        "metadata": {"agent": "tech"},
        "subject": {"kind": "trace", "id": "t1"},
    },
    {
        "id": "s2",
        "name": "eval_evidence",
        "dataType": "BOOLEAN",
        "value": False,
        "comment": "no evidence",
        "metadata": {"agent": "tech"},
        "subject": {"kind": "trace", "id": "t1"},
    },
]


def observations_handler(rows, root=ROOT):
    """Serve v2/observations like Langfuse: roots, name-prefix filters and two cursor pages."""

    def handle(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        assert "fields" in params
        if params.get("isRootObservation") == "true":
            return httpx.Response(200, json={"data": [root] if root else [], "meta": {}})
        if "filter" in params:
            prefix = json.loads(params["filter"])[0]["value"]
            return httpx.Response(200, json={"data": RUN_OUTPUTS[prefix], "meta": {}})
        half = len(rows) // 2
        if params.get("cursor") == "page-2":
            return httpx.Response(200, json={"data": rows[half:], "meta": {}})
        return httpx.Response(200, json={"data": rows[:half], "meta": {"cursor": "page-2"}})

    return handle


def mock_langfuse(router: respx.Router, rows=None, root=ROOT) -> None:
    router.get(OBSERVATIONS_URL).mock(
        side_effect=observations_handler(rows if rows is not None else observations(), root)
    )
    router.get(SCORES_URL).mock(return_value=httpx.Response(200, json={"data": SCORES, "meta": {}}))


async def log_peer(refused: bool, recipient: str = "hr") -> None:
    await platform.log_a2a_message(
        A2AMessage(
            id=f"msg-{recipient}-{refused}",
            request_id="r1",
            trace_id="t1",
            sender="tech",
            recipient=recipient,
            type="peer_request",
            content="Who is on this project?",
            payload={"refused": True, "reason": "cycle detected"} if refused else {},
            hop_count=1,
            chain=["tech"],
        ),
        "conv-1",
    )


# --- disabled path -----------------------------------------------------------------------------


async def test_endpoints_report_disabled_without_keys(client):
    for path in (
        "/api/observability/summary",
        "/api/observability/traces",
        "/api/observability/traces/abc123",
    ):
        response = await client.get(path)
        assert response.status_code == 200, path
        body = response.json()
        assert body["enabled"] is False
        assert "LANGFUSE_PUBLIC_KEY" in body["reason"]


async def test_summary_disabled_when_keys_rejected(client, langfuse_keys):
    with respx.mock(assert_all_mocked=True) as router:
        router.get(url__startswith=HOST).mock(return_value=httpx.Response(401, json={}))
        body = (await client.get("/api/observability/summary")).json()
    assert body["enabled"] is False
    assert "rejected" in body["reason"]


async def test_summary_disabled_when_langfuse_unreachable(client, langfuse_keys):
    with respx.mock(assert_all_mocked=True) as router:
        router.get(url__startswith=HOST).mock(side_effect=httpx.ConnectError("down"))
        body = (await client.get("/api/observability/summary")).json()
    assert body["enabled"] is False
    assert "reach Langfuse" in body["reason"]


async def test_summary_disabled_when_endpoint_gone(client, langfuse_keys):
    with respx.mock(assert_all_mocked=True) as router:
        router.get(url__startswith=HOST).mock(return_value=httpx.Response(410, json={}))
        body = (await client.get("/api/observability/summary")).json()
    assert body["enabled"] is False
    assert "410" in body["reason"]


# --- enabled path ------------------------------------------------------------------------------


async def test_summary_aggregates_observations_and_scores(client, langfuse_keys):
    await log_peer(refused=False)
    await log_peer(refused=True, recipient="finance")
    with respx.mock(assert_all_mocked=True) as router:
        mock_langfuse(router)
        response = await client.get("/api/observability/summary?days=7")
        calls = router.calls.call_count
        # A second call within the TTL is served from the cache.
        await client.get("/api/observability/summary?days=7")
        assert router.calls.call_count == calls
    assert response.status_code == 200
    # roots, two cursor pages of observations, two run-output queries, scores
    assert calls == 6
    body = response.json()
    assert body["enabled"] is True
    assert body["traces"] == 1
    assert body["avg_latency_ms"] == 20000.0
    assert body["p95_latency_ms"] == 20000.0
    assert body["total_tokens"] == 450
    assert body["total_cost"] == pytest.approx(0.0012)
    assert body["llm_calls"] == 2
    assert body["tool_calls"] == 3
    assert body["peer_calls"] == 1
    assert body["refusals"] == 1
    # An inner LLM error that was retried does not make the request an error.
    assert body["error_rate"] == 0.0
    assert body["success_rate"] == 0.0

    agents = {a["agent"]: a for a in body["per_agent"]}
    assert agents["ceo"]["role"] == "supervisor" and agents["ceo"]["runs"] == 1
    assert agents["tech"]["runs"] == 1 and agents["tech"]["tool_calls"] == 2
    assert agents["hr"]["runs"] == 1 and agents["hr"]["tool_calls"] == 1
    assert agents["hr"]["failures"] == 1  # from the decoded run output
    assert agents["finance"]["failures"] == 1  # from level=ERROR
    assert agents["tech"]["avg_latency_ms"] == 13000.0

    scores = {s["name"]: s for s in body["scores"]}
    assert scores["eval_independent"]["pass_rate"] == 1.0
    assert scores["eval_evidence"]["pass_rate"] == 0.0

    edges = {(e["source"], e["target"], e["kind"]): e for e in body["edges"]}
    assert edges[("tech", "hr", "peer")]["count"] == 1
    assert edges[("tech", "finance", "peer")]["refusals"] == 1
    assert edges[("ceo", "tech", "task")]["count"] == 1
    assert edges[("tech", "hr", "peer")]["last_at"].endswith(("Z", "+00:00"))

    assert body["window"]["bucket"] == "day"
    assert sum(b["traces"] for b in body["timeseries"]) == 1
    assert sum(b["tokens"] for b in body["timeseries"]) == 450


async def test_root_error_marks_the_request_as_error(client, langfuse_keys):
    with respx.mock(assert_all_mocked=True) as router:
        mock_langfuse(router, rows=observations(root_level="ERROR"))
        body = (await client.get("/api/observability/summary")).json()
    assert body["error_rate"] == 1.0


async def test_trace_list(client, langfuse_keys):
    with respx.mock(assert_all_mocked=True) as router:
        mock_langfuse(router)
        body = (await client.get("/api/observability/traces?limit=10")).json()
    assert body["enabled"] is True
    [trace] = body["traces"]
    assert trace["id"] == "t1"
    assert trace["question"] == "Which projects are behind schedule?"
    assert trace["latency_ms"] == 20000.0
    assert trace["tokens"] == 450
    assert trace["cost"] == pytest.approx(0.0012)
    assert trace["status"] == "partial"
    assert trace["session_id"] == "conv-1"
    assert trace["agents"] == ["finance", "hr", "tech"]
    assert trace["peer_calls"] == 1
    assert trace["url"] == f"{HOST}/project/p1/traces/t1"
    assert {s["name"]: s["passed"] for s in trace["scores"]} == {
        "eval_evidence": 0,
        "eval_independent": 1,
    }


async def test_trace_detail_builds_indented_tree(client, langfuse_keys):
    await log_peer(refused=True, recipient="finance")
    with respx.mock(assert_all_mocked=True) as router:
        mock_langfuse(router)
        body = (await client.get("/api/observability/traces/t1")).json()
        trace_params = [c.request.url.params.get("traceId") for c in router.calls]
    assert set(trace_params) == {"t1"}
    assert body["enabled"] is True
    assert body["trace"]["id"] == "t1"
    assert body["trace"]["question"] == "Which projects are behind schedule?"
    rows = body["observations"]
    order = [r["id"] for r in rows]
    assert order[0] == "root"
    assert order.index("ask") < order.index("peer") < order.index("tool2")
    peer = next(r for r in rows if r["id"] == "peer")
    assert peer["kind"] == "a2a"
    assert peer["depth"] == 3
    assert peer["metadata"]["hop_count"] == 1
    assert peer["metadata"]["chain"] == ["tech"]
    assert peer["failed"] is True
    finance = next(r for r in rows if r["id"] == "fin")
    assert finance["failed"] is True and finance["status_message"] == "boom"
    scores = {s["name"]: s for s in body["scores"]}
    assert scores["eval_evidence"]["passed"] is False and scores["eval_evidence"]["agent"] == "tech"
    assert scores["eval_independent"]["passed"] is True
    assert body["a2a"][0]["refused"] is True


async def test_trace_detail_not_found(client, langfuse_keys):
    with respx.mock(assert_all_mocked=True) as router:
        mock_langfuse(router, rows=[], root=None)
        response = await client.get("/api/observability/traces/missing")
    assert response.status_code == 404


async def test_trace_id_is_validated(client):
    response = await client.get("/api/observability/traces/bad id!")
    assert response.status_code == 422
