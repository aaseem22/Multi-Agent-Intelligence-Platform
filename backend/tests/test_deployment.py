"""Deployment wiring: serving the built frontend from the API, open to everyone."""

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.core.config import get_settings
from app.core.orchestrator import Orchestrator
from app.main import create_app


@pytest.fixture
def frontend_dist(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><div id=root></div>")
    (dist / "assets" / "app.js").write_text("console.log('ok')")
    monkeypatch.setattr(get_settings(), "frontend_dist", str(dist))
    return dist


async def test_serves_frontend_and_api_without_credentials(frontend_dist):
    app = create_app(Orchestrator(checkpointer=InMemorySaver()))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        page = await client.get("/")
        assert page.status_code == 200 and "root" in page.text
        assert (await client.get("/assets/app.js")).status_code == 200
        api = await client.get("/api/agents")
        assert api.status_code == 200 and api.headers["content-type"].startswith("application/json")
        assert (await client.get("/api/health")).status_code == 200


async def test_no_frontend_by_default():
    app = create_app(Orchestrator(checkpointer=InMemorySaver()))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/api/agents")).status_code == 200
        assert (await client.get("/")).status_code == 404
