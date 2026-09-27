"""Per-request and per-agent-invocation context carried through asyncio contextvars.

LangGraph runs nodes and tools in tasks that copy the caller's context, so values set here are
visible to tools such as `ask_agent` without threading them through every signature.
"""

import asyncio
import logging
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from app.core.contracts import Evidence
from app.core.events import AgentMode, BaseEvent

logger = logging.getLogger(__name__)


@dataclass
class RequestContext:
    request_id: str
    conversation_id: str
    trace_id: str | None = None
    trace_url: str | None = None
    queue: asyncio.Queue[BaseEvent] | None = None
    peer_calls: Counter[str] = field(default_factory=Counter)
    langfuse_callbacks: list[Any] = field(default_factory=list)

    def emit(self, event: BaseEvent) -> None:
        if self.queue is not None:
            self.queue.put_nowait(event)


@dataclass
class AgentInvocation:
    agent: str
    subtask_id: str
    mode: AgentMode
    hop_count: int = 0
    chain: list[str] = field(default_factory=list)
    evidence: dict[str, Evidence] = field(default_factory=dict)
    peer_messages: list[str] = field(default_factory=list)

    def record_evidence(self, *items: Evidence) -> None:
        for item in items:
            self.evidence[item.source_ref] = item


_request: ContextVar[RequestContext | None] = ContextVar("request_context", default=None)
_invocation: ContextVar[AgentInvocation | None] = ContextVar("agent_invocation", default=None)


def current_request() -> RequestContext | None:
    return _request.get()


def require_request() -> RequestContext:
    ctx = _request.get()
    if ctx is None:
        raise RuntimeError("No active request context")
    return ctx


def current_invocation() -> AgentInvocation | None:
    return _invocation.get()


@contextmanager
def request_scope(ctx: RequestContext) -> Iterator[RequestContext]:
    token = _request.set(ctx)
    try:
        yield ctx
    finally:
        _request.reset(token)


@contextmanager
def invocation_scope(invocation: AgentInvocation) -> Iterator[AgentInvocation]:
    token = _invocation.set(invocation)
    try:
        yield invocation
    finally:
        _invocation.reset(token)


def emit(event_cls: type[BaseEvent], **fields: Any) -> None:
    """Emit an event for the active request. A no-op outside a request (e.g. unit tests)."""
    ctx = _request.get()
    if ctx is None:
        return
    ctx.emit(event_cls(request_id=ctx.request_id, conversation_id=ctx.conversation_id, **fields))


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        ctx = _request.get()
        record.request_id = ctx.request_id if ctx else "-"
        return True


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.addFilter(RequestIdFilter())
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
