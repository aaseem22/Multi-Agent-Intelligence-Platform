"""Core-owned platform tables: A2A message log, conversations, chat turns and GitHub cache.
Department agents never import this module."""

from datetime import datetime
from typing import Any

from sqlalchemy import select

from app.core.contracts import A2AMessage, utcnow
from app.data.db import session_scope
from app.data.models import (
    A2AMessageRecord,
    ChatTurn,
    Conversation,
    EvalRecord,
    GitHubCacheEntry,
)

# --- A2A log ---


async def log_a2a_message(message: A2AMessage, conversation_id: str | None) -> None:
    async with session_scope() as session:
        session.add(
            A2AMessageRecord(
                id=message.id,
                request_id=message.request_id,
                conversation_id=conversation_id,
                trace_id=message.trace_id,
                sender=message.sender,
                recipient=message.recipient,
                type=message.type,
                content=message.content,
                payload=message.payload,
                hop_count=message.hop_count,
                chain=message.chain,
                created_at=message.created_at,
            )
        )


def _a2a(row: A2AMessageRecord) -> A2AMessage:
    return A2AMessage(
        id=row.id,
        request_id=row.request_id,
        trace_id=row.trace_id,
        sender=row.sender,
        recipient=row.recipient,
        type=row.type,  # type: ignore[arg-type]
        content=row.content,
        payload=row.payload or {},
        hop_count=row.hop_count,
        chain=list(row.chain or []),
        created_at=row.created_at,
    )


async def list_a2a_messages(
    *, conversation_id: str | None = None, request_id: str | None = None
) -> list[A2AMessage]:
    stmt = select(A2AMessageRecord).order_by(A2AMessageRecord.created_at)
    if conversation_id:
        stmt = stmt.where(A2AMessageRecord.conversation_id == conversation_id)
    if request_id:
        stmt = stmt.where(A2AMessageRecord.request_id == request_id)
    async with session_scope() as session:
        return [_a2a(r) for r in await session.scalars(stmt)]


# --- Conversations ---


async def ensure_conversation(conversation_id: str, title: str) -> None:
    now = utcnow()
    async with session_scope() as session:
        row = await session.get(Conversation, conversation_id)
        if row is None:
            session.add(
                Conversation(id=conversation_id, title=title[:200], created_at=now, updated_at=now)
            )
        else:
            row.updated_at = now


async def list_conversations() -> list[dict[str, Any]]:
    async with session_scope() as session:
        rows = await session.scalars(select(Conversation).order_by(Conversation.updated_at.desc()))
        return [
            {"id": r.id, "title": r.title, "created_at": r.created_at, "updated_at": r.updated_at}
            for r in rows
        ]


async def get_conversation(conversation_id: str) -> dict[str, Any] | None:
    async with session_scope() as session:
        row = await session.get(Conversation, conversation_id)
        if row is None:
            return None
        turns = await session.scalars(
            select(ChatTurn)
            .where(ChatTurn.conversation_id == conversation_id)
            .order_by(ChatTurn.created_at)
        )
        return {
            "id": row.id,
            "title": row.title,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "turns": [
                {
                    "request_id": t.id,
                    "question": t.question,
                    "kind": t.kind,
                    "answer": t.answer,
                    "payload": t.payload or {},
                    "trace_url": t.trace_url,
                    "created_at": t.created_at,
                }
                for t in turns
            ],
        }


async def save_turn(
    *,
    request_id: str,
    conversation_id: str,
    question: str,
    kind: str,
    answer: str | None = None,
    payload: dict[str, Any] | None = None,
    trace_url: str | None = None,
) -> None:
    async with session_scope() as session:
        row = await session.get(ChatTurn, request_id)
        if row is None:
            session.add(
                ChatTurn(
                    id=request_id,
                    conversation_id=conversation_id,
                    question=question,
                    kind=kind,
                    answer=answer,
                    payload=payload or {},
                    trace_url=trace_url,
                    created_at=utcnow(),
                )
            )
        else:
            row.kind, row.answer, row.payload, row.trace_url = (
                kind,
                answer,
                payload or {},
                trace_url,
            )


# --- GitHub cache ---


async def get_github_cache(key: str) -> GitHubCacheEntry | None:
    async with session_scope() as session:
        return await session.get(GitHubCacheEntry, key)


async def put_github_cache(key: str, status_code: int, body: Any, fetched_at: datetime) -> None:
    async with session_scope() as session:
        row = await session.get(GitHubCacheEntry, key)
        if row is None:
            session.add(
                GitHubCacheEntry(key=key, status_code=status_code, body=body, fetched_at=fetched_at)
            )
        else:
            row.status_code, row.body, row.fetched_at = status_code, body, fetched_at


# --- Live self-evaluation records ---


async def log_eval_record(
    *,
    request_id: str,
    conversation_id: str | None,
    kind: str,
    agent: str,
    subtask_id: str,
    stage: str | None = None,
    action: str | None = None,
    passed: bool | None = None,
    score: float | None = None,
    attempt: int = 1,
    payload: dict[str, Any] | None = None,
) -> None:
    async with session_scope() as session:
        session.add(
            EvalRecord(
                request_id=request_id,
                conversation_id=conversation_id,
                kind=kind,
                agent=agent,
                subtask_id=subtask_id,
                stage=stage,
                action=action,
                passed=passed,
                score=score,
                attempt=attempt,
                payload=payload or {},
                created_at=utcnow(),
            )
        )


async def list_eval_records(*, since: datetime, limit: int = 2000) -> list[dict[str, Any]]:
    async with session_scope() as session:
        rows = await session.scalars(
            select(EvalRecord)
            .where(EvalRecord.created_at >= since)
            .order_by(EvalRecord.created_at.desc())
            .limit(limit)
        )
        return [
            {
                "request_id": r.request_id,
                "conversation_id": r.conversation_id,
                "kind": r.kind,
                "agent": r.agent,
                "subtask_id": r.subtask_id,
                "stage": r.stage,
                "action": r.action,
                "passed": r.passed,
                "score": r.score,
                "attempt": r.attempt,
                "payload": r.payload or {},
                "created_at": r.created_at,
            }
            for r in rows
        ]
