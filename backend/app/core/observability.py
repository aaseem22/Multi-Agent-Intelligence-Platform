"""Langfuse tracing helpers. Everything here is best effort: without keys, or if Langfuse fails,
the app keeps running and tracing is skipped.

- One trace per stakeholder request (`request_trace`), session_id = conversation id.
- The LangChain CallbackHandler is attached at the top-level graph invoke; nested agent runs
  inherit it, so peer calls appear as spans named by their run_name (`a2a:{sender}->{target}`).
- Every EvalResult becomes an `eval_result` SSE event and a Langfuse score (`record_eval`).
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import ExitStack, asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.core.config import get_settings
from app.core.context import current_request, emit
from app.core.contracts import EvalResult
from app.core.events import EvalResultEvent

if TYPE_CHECKING:
    from langfuse import Langfuse

logger = logging.getLogger(__name__)

TRACE_NAME = "stakeholder_request"

_client: "Langfuse | None" = None
_warned = False


def get_langfuse() -> "Langfuse | None":
    """The shared Langfuse client, or None (with one warning) when keys are missing."""
    global _client, _warned
    settings = get_settings()
    if not settings.langfuse_enabled:
        if not _warned:
            logger.warning("Langfuse keys are not set; tracing is disabled")
            _warned = True
        return None
    if _client is None:
        try:
            from langfuse import Langfuse

            _client = Langfuse(
                public_key=settings.langfuse_public_key,
                secret_key=settings.langfuse_secret_key,
                host=settings.langfuse_host,
            )
        except Exception as exc:
            if not _warned:
                logger.warning("Langfuse client could not be created (%s); tracing disabled", exc)
                _warned = True
            return None
    return _client


def reset_langfuse() -> None:
    """Forget the cached client (tests, settings changes)."""
    global _client, _warned
    _client, _warned = None, False


def shutdown() -> None:
    if _client is not None:
        try:
            _client.shutdown()
        except Exception as exc:
            logger.warning("Langfuse shutdown failed: %s", exc)


@dataclass
class TraceHandle:
    trace_id: str | None = None
    trace_url: str | None = None
    callbacks: list[Any] = field(default_factory=list)
    span: Any = None

    def set_output(self, output: Any) -> None:
        if self.span is None:
            return
        try:
            self.span.update(output=output)
        except Exception as exc:
            logger.debug("Could not set trace output: %s", exc)


def _open_trace(
    stack: ExitStack, client: "Langfuse", request_id: str, conversation_id: str, question: str
) -> TraceHandle:
    from langfuse import Langfuse, propagate_attributes
    from langfuse.langchain import CallbackHandler

    trace_id = Langfuse.create_trace_id(seed=request_id)
    span = stack.enter_context(
        client.start_as_current_observation(
            trace_context={"trace_id": trace_id},
            name=TRACE_NAME,
            as_type="agent",
            input={"question": question},
            metadata={"request_id": request_id},
        )
    )
    stack.enter_context(propagate_attributes(session_id=conversation_id, trace_name=TRACE_NAME))
    handler = CallbackHandler(public_key=get_settings().langfuse_public_key)
    return TraceHandle(trace_id=trace_id, callbacks=[handler], span=span)


async def _trace_url(client: "Langfuse", trace_id: str) -> str | None:
    """get_trace_url may call the Langfuse API (sync), so run it off the event loop."""
    try:
        return await asyncio.to_thread(client.get_trace_url, trace_id=trace_id)
    except Exception as exc:
        logger.warning("Could not resolve Langfuse trace URL: %s", exc)
        return None


@asynccontextmanager
async def request_trace(
    request_id: str, conversation_id: str, question: str
) -> AsyncIterator[TraceHandle]:
    """Open one Langfuse trace for a stakeholder request. Yields an empty handle if disabled."""
    client = get_langfuse()
    with ExitStack() as stack:
        handle = TraceHandle()
        if client is not None:
            try:
                handle = _open_trace(stack, client, request_id, conversation_id, question)
            except Exception as exc:
                logger.warning("Could not start Langfuse trace: %s", exc)
                stack.close()
                handle = TraceHandle()
        if client is not None and handle.trace_id is not None:
            handle.trace_url = await _trace_url(client, handle.trace_id)
        yield handle


@contextmanager
def agent_tags(*tags: str) -> Iterator[None]:
    """Tag the current trace with agent names (best effort, no-op without tracing)."""
    ctx = current_request()
    if get_langfuse() is None or ctx is None or ctx.trace_id is None:
        yield
        return
    with ExitStack() as stack:
        try:
            from langfuse import propagate_attributes

            stack.enter_context(propagate_attributes(tags=list(tags)))
        except Exception as exc:
            logger.debug("Could not tag trace: %s", exc)
        yield


def record_eval(result: EvalResult, agent: str, subtask_id: str) -> None:
    """Emit an eval_result event and record the result as a Langfuse score. Never raises."""
    emit(EvalResultEvent, agent=agent, subtask_id=subtask_id, result=result)
    client = get_langfuse()
    ctx = current_request()
    if client is None or ctx is None or ctx.trace_id is None:
        return
    try:
        client.create_score(
            name=f"eval_{result.stage}",
            value=1.0 if result.passed else 0.0,
            trace_id=ctx.trace_id,
            data_type="BOOLEAN",
            comment="; ".join(result.reasons) or None,
            metadata={"agent": agent, "subtask_id": subtask_id, "score": result.score},
        )
    except Exception as exc:
        logger.warning("Could not record eval score: %s", exc)
