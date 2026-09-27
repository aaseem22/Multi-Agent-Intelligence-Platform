"""In-process agent-to-agent (A2A) collaboration: the `ask_agent` tool and its guards.

A department agent asks a peer through `ask_agent(target, question)`. Guards (self-call,
supervisor target, unknown or closed target, cycle, hop limit, per-agent call limit) refuse the
request with a "REFUSED: ..." string instead of raising, so the caller can carry on. Accepted
requests run the target in peer mode; both messages are logged to `a2a_messages` and streamed as
`peer_message` events, and the answer is recorded as Evidence(source_type="peer") on the caller.
Nothing here names a specific department: peers come from the registry at runtime.
"""

import json
import logging
import uuid
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.context import current_invocation, current_request, emit
from app.core.contracts import A2AMessage, AgentCard, AgentResult, Evidence
from app.core.events import PeerMessageEvent
from app.core.prompts import ASK_AGENT_DESCRIPTION
from app.core.registry import registry

logger = logging.getLogger(__name__)

MAX_PEER_EVIDENCE = 10
MAX_ANSWER_CHARS = 1000


def new_message_id() -> str:
    return f"msg_{uuid.uuid4().hex[:16]}"


def check_guards(
    sender: str, target: str, hop_count: int, chain: list[str], calls_made: int
) -> str | None:
    """Return the refusal reason, or None if the peer request may proceed.

    `hop_count` and `chain` are the values the new request would carry.
    """
    settings = get_settings()
    if target == sender:
        return "self-call: an agent cannot ask itself"
    if registry.is_supervisor(target):
        return "the supervisor cannot be asked; report needs_clarification in your answer instead"
    agent = registry.get(target)
    if agent is None:
        valid = ", ".join(c.name for c in registry.peer_cards(exclude=sender)) or "none"
        return f"unknown agent '{target}' (valid peers: {valid})"
    if not agent.card.accepts_peer_requests:
        return f"agent '{target}' does not accept peer requests"
    if target in chain:
        return f"cycle detected: '{target}' is already in the chain {' -> '.join(chain)}"
    if hop_count > settings.max_peer_hops:
        return f"hop limit reached ({hop_count} > MAX_PEER_HOPS={settings.max_peer_hops})"
    if calls_made >= settings.max_peer_calls_per_agent:
        return (
            f"call limit reached: '{sender}' already made {calls_made} peer calls in this "
            f"request (MAX_PEER_CALLS_PER_AGENT={settings.max_peer_calls_per_agent})"
        )
    return None


async def log_message(message: A2AMessage) -> None:
    """Persist an A2A message. DB failures are logged and swallowed."""
    ctx = current_request()
    try:
        from app.data.repositories import platform

        await platform.log_a2a_message(message, ctx.conversation_id if ctx else None)
    except Exception as exc:
        logger.warning("Could not log A2A message %s: %s", message.id, exc)


async def publish(
    message: A2AMessage, *, refused: bool = False, refusal_reason: str | None = None
) -> None:
    """Log an A2A message and stream it as a peer_message event."""
    await log_message(message)
    emit(PeerMessageEvent, message=message, refused=refused, refusal_reason=refusal_reason)


def _truncate(text: str, limit: int = MAX_ANSWER_CHARS) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _peer_evidence_summary(result: AgentResult) -> list[dict[str, str]]:
    return [
        {"source_ref": e.source_ref, "source_type": e.source_type, "summary": e.summary}
        for e in result.evidence[:MAX_PEER_EVIDENCE]
    ]


def _response_message(request: A2AMessage, result: AgentResult) -> A2AMessage:
    return A2AMessage(
        id=new_message_id(),
        request_id=request.request_id,
        trace_id=request.trace_id,
        sender=request.recipient,
        recipient=request.sender,
        type="peer_response",
        content=result.answer,
        payload={
            "in_reply_to": request.id,
            "status": result.status,
            "evidence": _peer_evidence_summary(result),
            "error": result.error,
        },
        hop_count=request.hop_count,
        chain=[*request.chain, request.recipient],
    )


def _peer_evidence(request: A2AMessage, response: A2AMessage, result: AgentResult) -> Evidence:
    return Evidence(
        source_type="peer",
        source_ref=f"peer:{request.recipient}:{response.id}",
        summary=_truncate(f"{request.recipient} answered ({result.status}): {result.answer}", 200),
        data={
            "question": _truncate(request.content, 300),
            "status": result.status,
            "answer": _truncate(result.answer),
            "peer_evidence": _peer_evidence_summary(result),
        },
    )


async def ask_agent(sender: str, target: str, question: str) -> str:
    """Ask `target` a question on behalf of `sender`. Returns JSON, or a REFUSED string."""
    ctx = current_request()
    invocation = current_invocation()
    hop_count = (invocation.hop_count if invocation else 0) + 1
    chain = [*(invocation.chain if invocation else []), sender]
    calls_made = ctx.peer_calls[sender] if ctx else 0

    request = A2AMessage(
        id=new_message_id(),
        request_id=ctx.request_id if ctx else "local",
        trace_id=ctx.trace_id if ctx else None,
        sender=sender,
        recipient=target,
        type="peer_request",
        content=question,
        hop_count=hop_count,
        chain=chain,
    )
    if invocation is not None:
        invocation.peer_messages.append(request.id)

    reason = check_guards(sender, target, hop_count, chain, calls_made)
    if reason is not None:
        request.payload = {"refused": True, "reason": reason}
        logger.info("Peer request %s -> %s refused: %s", sender, target, reason)
        await publish(request, refused=True, refusal_reason=reason)
        return f"REFUSED: {reason}. Continue with the information you already have."

    if ctx is not None:
        ctx.peer_calls[sender] += 1
    await publish(request)

    result = await _run_peer(request, invocation.subtask_id if invocation else request.id)
    response = _response_message(request, result)
    await publish(response)

    evidence = _peer_evidence(request, response, result)
    if invocation is not None:
        invocation.record_evidence(evidence)
        invocation.peer_messages.append(response.id)
    return json.dumps(
        {
            "from": target,
            "status": result.status,
            "answer": result.answer,
            "source_ref": evidence.source_ref,
            "peer_evidence": _peer_evidence_summary(result),
        },
        default=str,
    )


async def _run_peer(request: A2AMessage, parent_subtask_id: str) -> AgentResult:
    """Run the target in peer mode inside the caller's concurrency slot. Never raises."""
    agent = registry.get(request.recipient)
    assert agent is not None  # checked by the guards
    metadata: dict[str, Any] = {
        "hop_count": request.hop_count,
        "chain": request.chain,
        "a2a_message_id": request.id,
    }
    try:
        return await agent.run(
            request.content,
            subtask_id=f"{parent_subtask_id}/{request.recipient}",
            mode="peer",
            hop_count=request.hop_count,
            chain=request.chain,
            run_name=f"a2a:{request.sender}->{request.recipient}",
            metadata=metadata,
        )
    except Exception as exc:  # DepartmentAgent.run never raises; guard against overrides
        logger.exception("Peer run %s failed", request.recipient)
        return AgentResult(
            agent=request.recipient,
            subtask_id=f"{parent_subtask_id}/{request.recipient}",
            status="failed",
            answer="",
            evidence=[],
            peer_messages=[],
            error=str(exc),
        )


class AskAgentInput(BaseModel):
    target: str = Field(description="Name of the agent to ask (see the list of agents)")
    question: str = Field(description="A specific, self-contained question for that agent")


def describe_peers(cards: list[AgentCard]) -> str:
    return "\n".join(
        f"- {c.name} ({c.department}): {c.description} Owns: {', '.join(c.owned_data) or 'n/a'}."
        for c in cards
    )


def build_ask_agent_tool(sender: str) -> BaseTool | None:
    """The ask_agent tool for `sender`, describing every peer from the registry, or None."""
    peers = registry.peer_cards(exclude=sender)
    if not peers:
        return None

    async def _ask(target: str, question: str) -> str:
        return await ask_agent(sender, target, question)

    return StructuredTool.from_function(
        coroutine=_ask,
        name="ask_agent",
        description=ASK_AGENT_DESCRIPTION.format(
            peers=describe_peers(peers), max_calls=get_settings().max_peer_calls_per_agent
        ),
        args_schema=AskAgentInput,
    )
