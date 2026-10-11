"""A request outlives its client: closing the stream does not lose the answer; cancel() stops it."""

import asyncio

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.core.contracts import Plan
from app.core.orchestrator import CANCELLED_MESSAGE, Orchestrator
from app.data.repositories import platform
from app.main import create_app
from tests.core.echo import EchoSupervisor, register_echo_world

pytestmark = pytest.mark.usefixtures("clean_registry")


class GatedSupervisor(EchoSupervisor):
    """Planning waits until the test opens the gate, so a request can be caught mid-run."""

    def __init__(self, plans: list[Plan]) -> None:
        super().__init__(plans=plans)
        self.gate = asyncio.Event()

    async def plan(self, question, history, cards):  # type: ignore[override]
        await self.gate.wait()
        return await super().plan(question, history, cards)


@pytest.fixture
async def orchestrator():
    orch = Orchestrator(checkpointer=InMemorySaver())
    await orch.start()
    yield orch
    await orch.aclose()


async def settle(orchestrator: Orchestrator) -> None:
    """Wait for every running request to finish."""
    async with asyncio.timeout(2.0):
        await asyncio.gather(*list(orchestrator._running.values()), return_exceptions=True)


async def test_disconnected_client_still_gets_its_answer_saved(seeded_db, orchestrator):
    supervisor = GatedSupervisor(plans=[Plan(clarification="Which area?")])
    register_echo_world("alpha", supervisor=supervisor)

    stream = orchestrator.stream("How are we doing?", "conv-disconnect")
    # The browser goes away before any event arrives.
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(anext(stream), timeout=0.05)
    await stream.aclose()
    assert len(orchestrator._running) == 1, "the request keeps running without its client"

    supervisor.gate.set()
    await settle(orchestrator)

    detail = await platform.get_conversation("conv-disconnect")
    assert detail["turns"][-1]["kind"] == "clarification"
    assert detail["turns"][-1]["answer"] == "Which area?"


async def test_cancel_stops_the_request_and_records_it(seeded_db, orchestrator):
    supervisor = GatedSupervisor(plans=[Plan(clarification="never sent")])
    register_echo_world("alpha", supervisor=supervisor)

    consumer = asyncio.create_task(
        anext(orchestrator.stream("How are we doing?", "conv-cancel"), None)
    )
    await asyncio.sleep(0.05)  # let the stream start its request
    assert len(orchestrator._running) == 1
    request_id = next(iter(orchestrator._running))

    assert orchestrator.cancel(request_id) is True
    await settle(orchestrator)
    assert orchestrator.cancel(request_id) is False, "a finished request cannot be cancelled again"
    consumer.cancel()

    detail = await platform.get_conversation("conv-cancel")
    assert detail["turns"][-1]["kind"] == "error"
    assert detail["turns"][-1]["answer"] == CANCELLED_MESSAGE


async def test_cancel_endpoint_reports_unknown_requests(seeded_db):
    orch = Orchestrator(checkpointer=InMemorySaver())
    app = create_app(orch)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as http:
        response = await http.post("/api/chat/does-not-exist/cancel")
    await orch.aclose()
    assert response.status_code == 404
