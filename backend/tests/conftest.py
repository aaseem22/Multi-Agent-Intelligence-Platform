"""Shared fixtures. `seeded_db` builds the fictional org once per session into a temp SQLite
file (GitHub fixtures, no network, no token). Use it in any test that reads repositories."""

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.core.registry import registry
from app.data import db


@pytest.fixture(autouse=True)
def offline_self_eval(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit tests never call the real judge (Groq) and never re-run agents for recovery,
    whatever the local .env says. Tests of those features opt back in explicitly."""
    if request.node.get_closest_marker("live"):
        return
    settings = get_settings()
    monkeypatch.setattr(settings, "eval_judge_enabled", False)
    monkeypatch.setattr(settings, "eval_recovery", "observe")
    monkeypatch.setattr(settings, "groq_api_key", "")


@pytest.fixture(scope="session")
def seeded_db(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    from app.data.seed import seed as seed_module

    path = tmp_path_factory.mktemp("db") / "test_org.db"
    settings = get_settings()
    original_token = settings.github_token
    settings.github_token = ""  # always seed from offline fixtures
    db.configure_database(f"sqlite+aiosqlite:///{path}")
    original_scenarios = seed_module.SCENARIOS_PATH
    seed_module.SCENARIOS_PATH = path.with_name("scenarios.json")
    try:
        asyncio.run(seed_module.seed(reset=True))
        asyncio.run(db.dispose_engine())
        yield path
    finally:
        seed_module.SCENARIOS_PATH = original_scenarios
        settings.github_token = original_token
        db.configure_database(None)


@pytest.fixture
def scenarios(seeded_db: Path) -> dict:
    import json

    return json.loads(seeded_db.with_name("scenarios.json").read_text())


@pytest.fixture
def isolated_registry() -> Iterator[None]:
    """Restore the global registry after a test that registers or removes agents."""
    snapshot = registry.snapshot()
    try:
        yield
    finally:
        registry.restore(snapshot)
