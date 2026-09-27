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
