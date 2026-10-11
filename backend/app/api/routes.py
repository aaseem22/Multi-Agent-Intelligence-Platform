"""HTTP and SSE endpoints. No business logic: routes delegate to the Orchestrator, the
observability queries or the evals service."""

from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from sse_starlette import EventSourceResponse

from app.api.schemas import (
    ChatRequest,
    ConversationDetail,
    ConversationSummary,
    HealthResponse,
    HumanLabelRequest,
    ObservabilitySummary,
    ObservabilityTraceDetail,
    ObservabilityTraces,
)
from app.core import observability_queries
from app.core.contracts import A2AMessage, AgentCard
from app.core.orchestrator import Orchestrator
from app.evals import service as evals_service
from app.evals.contracts import (
    CalibrationStats,
    Dataset,
    HumanLabel,
    RunConfig,
    RunProgress,
    RunSummary,
    SelfEvalStats,
    TrialResult,
)

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


@router.post("/chat/{request_id}/cancel", status_code=204)
async def cancel_chat(
    request_id: Annotated[str, Path(min_length=1)], orchestrator: OrchestratorDep
) -> None:
    """Stop a running request. Closing the stream alone does not stop it, so answers are not lost."""
    if not orchestrator.cancel(request_id):
        raise HTTPException(status_code=404, detail="No running request with this id")


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


# --- Evals: thin wrappers over app.evals.service (contract in app/evals/API.md) ---


def _not_found(what: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"{what} not found")


@router.get("/evals/datasets", response_model=list[Dataset])
def evals_datasets() -> list[Dataset]:
    return evals_service.datasets()


@router.get("/evals/runs", response_model=list[RunSummary])
def evals_runs() -> list[RunSummary]:
    return evals_service.list_runs()


@router.post("/evals/runs", response_model=RunSummary)
def evals_start_run(config: RunConfig) -> RunSummary:
    try:
        return evals_service.start_run(config)
    except evals_service.RunConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except evals_service.InvalidConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/evals/runs/{run_id}", response_model=RunSummary)
def evals_run(run_id: str) -> RunSummary:
    try:
        return evals_service.get_run(run_id)
    except evals_service.NotFoundError as exc:
        raise _not_found("Run") from exc


@router.get("/evals/runs/{run_id}/progress", response_model=RunProgress)
def evals_progress(run_id: str) -> RunProgress:
    try:
        return evals_service.get_progress(run_id)
    except evals_service.NotFoundError as exc:
        raise _not_found("Run") from exc


@router.post("/evals/runs/{run_id}/cancel", status_code=204)
def evals_cancel(run_id: str) -> None:
    try:
        evals_service.cancel_run(run_id)
    except evals_service.NotFoundError as exc:
        raise _not_found("Run") from exc


@router.get("/evals/runs/{run_id}/trials", response_model=list[TrialResult])
def evals_trials(run_id: str) -> list[TrialResult]:
    try:
        return evals_service.list_trials(run_id)
    except evals_service.NotFoundError as exc:
        raise _not_found("Run") from exc


@router.get("/evals/runs/{run_id}/trials/{trial_id}", response_model=TrialResult)
def evals_trial(run_id: str, trial_id: str) -> TrialResult:
    try:
        return evals_service.get_trial(run_id, trial_id)
    except evals_service.NotFoundError as exc:
        raise _not_found("Run or trial") from exc


@router.get("/evals/runs/{run_id}/labels", response_model=list[HumanLabel])
def evals_labels(run_id: str) -> list[HumanLabel]:
    try:
        return evals_service.list_labels(run_id)
    except evals_service.NotFoundError as exc:
        raise _not_found("Run") from exc


@router.post("/evals/runs/{run_id}/labels", response_model=HumanLabel)
def evals_upsert_label(run_id: str, body: HumanLabelRequest) -> HumanLabel:
    try:
        return evals_service.upsert_label(
            run_id, body.trial_id, body.grader, body.human_passed, body.note
        )
    except evals_service.NotFoundError as exc:
        raise _not_found("Run or trial") from exc


@router.get("/evals/calibration", response_model=CalibrationStats)
def evals_calibration() -> CalibrationStats:
    return evals_service.calibration()


@router.get("/evals/self-eval", response_model=SelfEvalStats)
async def evals_self_eval(days: Annotated[int, Query(ge=1, le=90)] = 7) -> SelfEvalStats:
    return await evals_service.self_eval_stats(days)
