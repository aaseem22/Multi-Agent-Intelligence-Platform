"""Langfuse read client resilience: retries, single-flight loads, and serving the last good result."""

import asyncio

import httpx
import pytest
import respx

from app.core import observability_queries as oq
from app.core.config import get_settings

HOST = "https://langfuse.test"
URL = f"{HOST}/api/public/v2/observations"


@pytest.fixture(autouse=True)
def fast_and_fresh(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(oq, "RETRY_BASE_SECONDS", 0.0)
    monkeypatch.setattr(oq, "_request_slots", None)
    settings = get_settings()
    monkeypatch.setattr(settings, "langfuse_host", HOST)
    monkeypatch.setattr(settings, "langfuse_public_key", "pk-test")
    monkeypatch.setattr(settings, "langfuse_secret_key", "sk-test")
    oq.reset_cache()
    yield
    oq.reset_cache()


@respx.mock
async def test_retries_rate_limit_then_succeeds():
    route = respx.get(URL).mock(
        side_effect=[
            httpx.Response(429, headers={"retry-after": "0"}),
            httpx.Response(200, json={"data": []}),
        ]
    )
    async with oq._client() as client:
        assert await oq._get(client, "/api/public/v2/observations", {}) == {"data": []}
    assert route.call_count == 2


@respx.mock
async def test_network_errors_become_transient_after_retries():
    route = respx.get(URL).mock(side_effect=httpx.ConnectError("offline"))
    async with oq._client() as client:
        with pytest.raises(oq.LangfuseUnavailable) as caught:
            await oq._get(client, "/api/public/v2/observations", {})
    assert caught.value.transient is True
    assert route.call_count == oq.MAX_ATTEMPTS


@respx.mock
async def test_bad_keys_are_not_transient_and_not_retried():
    route = respx.get(URL).mock(return_value=httpx.Response(401))
    async with oq._client() as client:
        with pytest.raises(oq.LangfuseUnavailable) as caught:
            await oq._get(client, "/api/public/v2/observations", {})
    assert caught.value.transient is False
    assert route.call_count == 1


async def test_concurrent_callers_share_one_load():
    calls = 0

    async def loader():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return "window"

    results = await asyncio.gather(*(oq._cached(("window", 7), loader) for _ in range(5)))
    assert results == ["window"] * 5
    assert calls == 1


async def test_transient_failure_serves_last_good_value():
    async def good():
        return "fresh"

    async def down():
        raise oq.LangfuseUnavailable("Could not reach Langfuse: ConnectError", transient=True)

    assert await oq._cached(("window", 30), good) == "fresh"
    oq._cache[("window", 30)] = (0.0, "fresh")  # expire the entry
    assert await oq._cached(("window", 30), down) == "fresh"


async def test_transient_failure_without_cache_is_reported_as_transient(
    monkeypatch: pytest.MonkeyPatch,
):
    async def down(_days: int):
        raise oq.LangfuseUnavailable("Langfuse is busy (HTTP 429)", transient=True)

    monkeypatch.setattr(oq, "_load_window", down)
    summary = await oq.observability_summary(30)
    assert summary["enabled"] is False
    assert summary["transient"] is True
    assert "429" in summary["reason"]
