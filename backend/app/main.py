"""FastAPI app factory. Run with `uv run uvicorn app.main:app --reload`."""

import importlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import router
from app.core.config import get_settings
from app.core.context import configure_logging
from app.core.orchestrator import Orchestrator
from app.data.db import dispose_engine, init_db

logger = logging.getLogger(__name__)

FRONTEND_ORIGIN = "http://localhost:5173"


def load_agents() -> None:
    """Import app.agents so every agent registers itself. Tolerates a missing package."""
    try:
        importlib.import_module("app.agents")
    except ModuleNotFoundError as exc:
        if exc.name != "app.agents":
            logger.exception("An agent module failed to import")
        else:
            logger.warning("app.agents does not exist yet; no agents registered")
    except ImportError:
        logger.exception("An agent module failed to import")


def create_app(orchestrator: Orchestrator | None = None) -> FastAPI:
    orchestrator = orchestrator or Orchestrator()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(get_settings().log_level)
        await init_db()
        load_agents()
        await orchestrator.start()
        try:
            yield
        finally:
            await orchestrator.aclose()
            await dispose_engine()

    app = FastAPI(title="Enterprise Multi-Agent Orchestration", lifespan=lifespan)
    app.state.orchestrator = orchestrator
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[FRONTEND_ORIGIN],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    settings = get_settings()
    app.include_router(router)
    mount_frontend(app, settings.frontend_dist)
    return app


def mount_frontend(app: FastAPI, dist: str) -> None:
    """Serve the built SPA at / when deployed. Mounted after the API router so /api wins; the
    app uses hash routing, so index.html plus its assets is all that is needed."""
    if not dist:
        return
    path = Path(dist)
    if not (path / "index.html").exists():
        logger.warning("FRONTEND_DIST=%s has no index.html; serving the API only", dist)
        return
    app.mount("/", StaticFiles(directory=path, html=True), name="frontend")


app = create_app()
