import asyncio
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from app.core import llm, observability
from app.core.config import get_settings
from app.data import db


@pytest.fixture(autouse=True)
def no_langfuse(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    settings = get_settings()
    monkeypatch.setattr(settings, "langfuse_public_key", "")
    monkeypatch.setattr(settings, "langfuse_secret_key", "")
    observability.reset_langfuse()
    yield
    observability.reset_langfuse()


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    class _AsyncioProxy:
        def __getattr__(self, name: str) -> object:
            return getattr(asyncio, name)

        @staticmethod
        async def sleep(_: float) -> None:
            return None

    monkeypatch.setattr(llm, "asyncio", _AsyncioProxy())


@pytest.fixture(autouse=True)
def scratch_db(tmp_path: Path) -> Iterator[None]:
    """Never touch the developer's database; runs re-point the data layer themselves."""
    previous = db._url_override
    db.configure_database(f"sqlite+aiosqlite:///{tmp_path / 'scratch.db'}")
    yield
    db.configure_database(previous)


@pytest.fixture
def evals_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "evals"
    monkeypatch.setattr(get_settings(), "evals_dir", str(root))
    return root


def event(type_: str, **fields: Any) -> dict[str, Any]:
    return {"type": type_, "request_id": "r", "conversation_id": "c", **fields}


def plan_event(*agents: str) -> dict[str, Any]:
    return event(
        "plan",
        subtasks=[
            {"id": f"t{i}", "assigned_to": a, "instruction": "x", "depends_on": []}
            for i, a in enumerate(agents, start=1)
        ],
        rationale="",
    )


def peer_event(sender: str, recipient: str, *, refused: bool = False) -> dict[str, Any]:
    return event(
        "peer_message",
        message={
            "id": "m",
            "request_id": "r",
            "trace_id": None,
            "sender": sender,
            "recipient": recipient,
            "type": "peer_request",
            "content": "q",
            "payload": {},
            "hop_count": 1,
            "chain": [sender],
            "created_at": "2026-10-11T00:00:00Z",
        },
        refused=refused,
        refusal_reason="cycle" if refused else None,
    )


def result_event(
    agent: str, refs: list[str], *, status: str = "ok", error: str | None = None
) -> dict[str, Any]:
    return event(
        "agent_result",
        mode="task",
        result={
            "agent": agent,
            "subtask_id": "t1",
            "status": status,
            "answer": "a",
            "evidence": [
                {"source_type": "db", "source_ref": r, "summary": r, "data": None} for r in refs
            ],
            "peer_messages": [],
            "error": error,
        },
    )


def final_event(
    answer: str,
    *,
    claims: list[tuple[str, list[str]]] | None = None,
    unanswered: list[str] | None = None,
) -> dict[str, Any]:
    return event(
        "final",
        answer={
            "answer": answer,
            "claims": [
                {"text": text, "evidence_refs": refs, "agents": []} for text, refs in claims or []
            ],
            "unanswered": unanswered or [],
        },
        results=[],
        trace_url="https://langfuse.example/trace/1",
    )
