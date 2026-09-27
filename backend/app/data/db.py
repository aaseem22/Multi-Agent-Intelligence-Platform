from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import BACKEND_DIR, get_settings
from app.data.models import Base

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None
_url_override: str | None = None


def _resolve_sqlite_path(url: str) -> str:
    """Resolve relative SQLite paths against backend/ so the CWD does not matter."""
    prefix = "sqlite+aiosqlite:///"
    if not url.startswith(prefix):
        return url
    path = Path(url.removeprefix(prefix))
    if not path.is_absolute():
        path = (BACKEND_DIR / path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"{prefix}{path}"


def database_url() -> str:
    if _url_override:
        return _url_override
    return _resolve_sqlite_path(get_settings().async_database_url)


def configure_database(url: str | None) -> None:
    """Point the data layer at another database (tests). Pass None to restore settings."""
    global _engine, _sessionmaker, _url_override
    _url_override = _resolve_sqlite_path(url) if url else None
    _engine = None
    _sessionmaker = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        url = database_url()
        # SQLite: no pooling, so connections never outlive the event loop that opened them.
        kwargs = {"poolclass": NullPool} if url.startswith("sqlite") else {}
        _engine = create_async_engine(url, **kwargs)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _sessionmaker


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db(*, reset: bool = False) -> None:
    async with get_engine().begin() as conn:
        if reset:
            await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


async def ping() -> bool:
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
