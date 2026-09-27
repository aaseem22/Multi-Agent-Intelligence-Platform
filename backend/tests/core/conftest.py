import asyncio
from collections.abc import Iterator

import pytest

from app.core import llm, observability
from app.core.config import get_settings
from app.core.context import RequestContext, request_scope
from app.core.events import BaseEvent
from app.core.registry import registry
from app.data import db


@pytest.fixture(autouse=True)
def no_langfuse(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Core tests never talk to Langfuse, whatever the local .env says."""
    settings = get_settings()
    monkeypatch.setattr(settings, "langfuse_public_key", "")
    monkeypatch.setattr(settings, "langfuse_secret_key", "")
    observability.reset_langfuse()
    yield
    observability.reset_langfuse()


@pytest.fixture(autouse=True)
def scratch_db(request: pytest.FixtureRequest, tmp_path) -> Iterator[None]:
    """Keep tests that do not use `seeded_db` away from the developer's real database."""
    if "seeded_db" in request.fixturenames:
        yield
        return
    previous = db._url_override
    db.configure_database(f"sqlite+aiosqlite:///{tmp_path / 'scratch.db'}")
    yield
    db.configure_database(previous)


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip LLM retry backoff delays without patching asyncio.sleep globally."""

    class _AsyncioProxy:
        def __getattr__(self, name: str) -> object:
            return getattr(asyncio, name)

        @staticmethod
        async def sleep(_: float) -> None:
            return None

    monkeypatch.setattr(llm, "asyncio", _AsyncioProxy())


@pytest.fixture
def clean_registry(isolated_registry: None) -> Iterator[None]:
    """An empty registry for the test, restored afterwards."""
    registry.clear()
    yield


class EventSink:
    def __init__(self, ctx: RequestContext) -> None:
        self.ctx = ctx

    def drain(self) -> list[BaseEvent]:
        events: list[BaseEvent] = []
        assert self.ctx.queue is not None
        while not self.ctx.queue.empty():
            events.append(self.ctx.queue.get_nowait())
        return events


@pytest.fixture
def request_ctx() -> Iterator[EventSink]:
    ctx = RequestContext(request_id="req-test", conversation_id="conv-test", queue=asyncio.Queue())
    with request_scope(ctx):
        yield EventSink(ctx)
