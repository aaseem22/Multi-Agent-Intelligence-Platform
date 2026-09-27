"""Request/response models for the HTTP API. Mirrors frontend/src/types/api.ts."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    conversation_id: str | None = None
    message: str = Field(min_length=1, max_length=4000)


class ConversationSummary(BaseModel):
    id: str
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationTurn(BaseModel):
    request_id: str
    question: str
    kind: Literal["final", "clarification", "error", "pending"]
    answer: str | None = None
    payload: dict[str, Any] = {}
    trace_url: str | None = None
    created_at: datetime


class ConversationDetail(ConversationSummary):
    turns: list[ConversationTurn]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    database: bool
    github_token: bool
    langfuse: bool
    agents: list[str]


# --- Observability dashboard (mirrors frontend/src/types/observability.ts) ---


class ObsWindow(BaseModel):
    days: int
    start: datetime
    end: datetime
    bucket: Literal["hour", "day"]


class ObsAgentStat(BaseModel):
    agent: str
    role: Literal["supervisor", "department"]
    runs: int
    avg_latency_ms: float | None = None
    tool_calls: int
    failures: int


class ObsScoreStat(BaseModel):
    name: str
    pass_rate: float
    count: int


class ObsEdge(BaseModel):
    source: str
    target: str
    kind: Literal["task", "peer"]
    count: int
    refusals: int
    last_at: datetime | None = None


class ObsBucket(BaseModel):
    bucket: datetime
    traces: int
    avg_latency_ms: float | None = None
    tokens: int


class ObservabilityStatus(BaseModel):
    enabled: bool
    reason: str | None = None
    host: str | None = None


class ObservabilitySummary(ObservabilityStatus):
    window: ObsWindow | None = None
    supervisor: str | None = None
    latency_target_ms: float | None = None
    traces: int = 0
    avg_latency_ms: float | None = None
    p95_latency_ms: float | None = None
    total_tokens: int = 0
    total_cost: float = 0.0
    llm_calls: int = 0
    tool_calls: int = 0
    peer_calls: int = 0
    refusals: int = 0
    error_rate: float = 0.0
    success_rate: float | None = None
    per_agent: list[ObsAgentStat] = []
    scores: list[ObsScoreStat] = []
    edges: list[ObsEdge] = []
    timeseries: list[ObsBucket] = []


class ObsScoreMark(BaseModel):
    name: str
    passed: int
    total: int


class ObsTraceMeta(BaseModel):
    id: str
    name: str | None = None
    question: str
    timestamp: datetime | None = None
    latency_ms: float | None = None
    tokens: int
    cost: float | None = None
    agents: list[str]
    tags: list[str]
    session_id: str | None = None
    status: Literal["ok", "partial", "error"]
    url: str


class ObsTraceItem(ObsTraceMeta):
    peer_calls: int
    refusals: int
    scores: list[ObsScoreMark]


class ObservabilityTraces(ObservabilityStatus):
    traces: list[ObsTraceItem] = []


class ObsObservation(BaseModel):
    id: str
    parent_id: str | None = None
    name: str
    type: str
    kind: Literal["a2a", "agent", "llm", "tool", "event", "span"]
    depth: int
    start: datetime | None = None
    end: datetime | None = None
    latency_ms: float | None = None
    model: str | None = None
    tokens: int
    level: str | None = None
    status_message: str | None = None
    failed: bool = False
    metadata: dict[str, Any] = {}


class ObsTraceScore(BaseModel):
    name: str | None = None
    value: float | str | None = None
    passed: bool
    comment: str | None = None
    agent: str | None = None
    timestamp: datetime | None = None


class ObsA2AMessage(BaseModel):
    id: str
    sender: str
    recipient: str
    type: str
    hop_count: int
    chain: list[str]
    refused: bool
    reason: str | None = None
    content: str
    created_at: datetime


class ObservabilityTraceDetail(ObservabilityStatus):
    trace: ObsTraceMeta | None = None
    observations: list[ObsObservation] = []
    scores: list[ObsTraceScore] = []
    a2a: list[ObsA2AMessage] = []
