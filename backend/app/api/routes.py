"""HTTP and SSE endpoints. No business logic: every route delegates to the Orchestrator."""

from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from sse_starlette import EventSourceResponse

from app.api.schemas import (
    ChatRequest,
    ConversationDetail,
    ConversationSummary,
    HealthResponse,
    ObservabilitySummary,
    ObservabilityTraceDetail,
    ObservabilityTraces,
)
from app.core import observability_queries
from app.core.contracts import A2AMessage, AgentCard
from app.core.orchestrator import Orchestrator

router = APIRouter(prefix="/api")


def get_orchestrator(request: Request) -> Orchestrator:
    return request.app.state.orchestrator


OrchestratorDep = Annotated[Orchestrator, Depends(get_orchestrator)]


@router.post("/chat")
async def chat(body: ChatRequest, orchestrator: OrchestratorDep) -> EventSourceResponse:
    async def events() -> AsyncIterator[dict[str, str]]:
        async for event in orchestrator.stream(body.message, body.conversation_id):
            yield {"event": getattr(event, "type", "message"), "data": event.model_dump_json()}

    return EventSourceResponse(events())


@router.get("/agents", response_model=list[AgentCard])
async def agents(orchestrator: OrchestratorDep) -> list[AgentCard]:
    return orchestrator.agent_cards()


@router.get("/conversations", response_model=list[ConversationSummary])
async def conversations(orchestrator: OrchestratorDep) -> list[dict[str, Any]]:
    return await orchestrator.list_conversations()


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def conversation(conversation_id: str, orchestrator: OrchestratorDep) -> dict[str, Any]:
    detail = await orchestrator.get_conversation(conversation_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return detail


@router.get("/conversations/{conversation_id}/a2a", response_model=list[A2AMessage])
async def conversation_a2a(conversation_id: str, orchestrator: OrchestratorDep) -> list[A2AMessage]:
    return await orchestrator.a2a_log(conversation_id)


@router.get("/health", response_model=HealthResponse)
async def health(orchestrator: OrchestratorDep) -> dict[str, Any]:
    return await orchestrator.health()


# --- Observability dashboard: Langfuse reads stay server-side, keys never reach the browser ---


@router.get("/observability/summary", response_model=ObservabilitySummary)
async def observability_summary(days: Annotated[int, Query(ge=1, le=30)] = 7) -> dict[str, Any]:
    return await observability_queries.observability_summary(days)


@router.get("/observability/traces", response_model=ObservabilityTraces)
async def observability_traces(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    days: Annotated[int, Query(ge=1, le=30)] = 7,
) -> dict[str, Any]:
    return await observability_queries.observability_traces(limit, days)


@router.get("/observability/traces/{trace_id}", response_model=ObservabilityTraceDetail)
async def observability_trace(
    trace_id: Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{1,128}$")],
) -> dict[str, Any]:
    detail = await observability_queries.observability_trace(trace_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Trace not found in Langfuse")
    return detail
