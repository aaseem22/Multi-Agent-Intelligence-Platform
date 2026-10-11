"""Deployment wiring: optional Basic auth and serving the built frontend from the API."""

import base64

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver

from app.core.config import get_settings
from app.core.orchestrator import Orchestrator
from app.main import create_app


def _basic(user: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@pytest.fixture
def deploy_settings(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><div id=root></div>")
    (dist / "assets" / "app.js").write_text("console.log('ok')")
    settings = get_settings()
    monkeypatch.setattr(settings, "frontend_dist", str(dist))
    monkeypatch.setattr(settings, "basic_auth_username", "demo")
    monkeypatch.setattr(settings, "basic_auth_password", "s3cret")
    return settings


async def test_auth_and_static_frontend(deploy_settings):
    app = create_app(Orchestrator(checkpointer=InMemorySaver()))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/api/health")).status_code == 200  # health stays public
        assert (await client.get("/")).status_code == 401
        assert (await client.get("/api/agents")).status_code == 401
        assert (await client.get("/", headers=_basic("demo", "wrong"))).status_code == 401
        page = await client.get("/", headers=_basic("demo", "s3cret"))
        assert page.status_code == 200 and "root" in page.text
        asset = await client.get("/assets/app.js", headers=_basic("demo", "s3cret"))
        assert asset.status_code == 200
        api = await client.get("/api/agents", headers=_basic("demo", "s3cret"))
        assert api.status_code == 200 and api.headers["content-type"].startswith("application/json")


async def test_no_auth_and_no_frontend_by_default():
    app = create_app(Orchestrator(checkpointer=InMemorySaver()))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/api/agents")).status_code == 200
        assert (await client.get("/")).status_code == 404
