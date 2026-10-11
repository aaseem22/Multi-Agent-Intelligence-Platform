"""Server-sent events streamed to the UI. Frozen after Phase 0.

Every event shares the envelope fields in `BaseEvent`. `peer_message` carries every A2A message,
including CEO `task`/`result` messages and refused peer requests, so the UI has one timeline.
"""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, TypeAdapter

from app.core.contracts import (
    A2AMessage,
    AgentResult,
    EvalResult,
    FinalAnswer,
    Subtask,
    utcnow,
)
from app.core.judge import JudgeVerdict

AgentMode = Literal["task", "peer"]


class BaseEvent(BaseModel):
    request_id: str
    conversation_id: str
    timestamp: datetime = Field(default_factory=utcnow)


class PlanEvent(BaseEvent):
    type: Literal["plan"] = "plan"
    subtasks: list[Subtask]
    rationale: str = ""


class AgentStartedEvent(BaseEvent):
    type: Literal["agent_started"] = "agent_started"
    agent: str
    subtask_id: str
    mode: AgentMode
    instruction: str


class ToolCallEvent(BaseEvent):
    type: Literal["tool_call"] = "tool_call"
    agent: str
    subtask_id: str
    tool: str
    args: dict[str, Any] = {}


class PeerMessageEvent(BaseEvent):
    type: Literal["peer_message"] = "peer_message"
    message: A2AMessage
    refused: bool = False
    refusal_reason: str | None = None


class AgentResultEvent(BaseEvent):
    type: Literal["agent_result"] = "agent_result"
    mode: AgentMode
    result: AgentResult


class EvalResultEvent(BaseEvent):
    type: Literal["eval_result"] = "eval_result"
    agent: str
    subtask_id: str
    result: EvalResult
    attempt: int = 1  # 2+ when the agent was re-run by the recovery router
    judge: JudgeVerdict | None = None  # per-dimension detail for stage="independent"


class RecoveryEvent(BaseEvent):
    """The recovery router acted on a failed evaluation (retry, replan or clarify)."""

    type: Literal["recovery"] = "recovery"
    agent: str
    subtask_id: str
    action: Literal["retry", "replan", "clarify", "give_up"]
    attempt: int  # the attempt about to start (retry) or the last attempt (give_up)
    reasons: list[str] = []
    feedback: str = ""  # judge feedback handed to the agent on retry


class FinalEvent(BaseEvent):
    type: Literal["final"] = "final"
    answer: FinalAnswer
    results: list[AgentResult]
    trace_url: str | None = None


class ClarificationEvent(BaseEvent):
    type: Literal["clarification"] = "clarification"
    question: str


class ErrorEvent(BaseEvent):
    type: Literal["error"] = "error"
    message: str
    agent: str | None = None


StreamEvent = Annotated[
    PlanEvent
    | AgentStartedEvent
    | ToolCallEvent
    | PeerMessageEvent
    | AgentResultEvent
    | EvalResultEvent
    | RecoveryEvent
    | FinalEvent
    | ClarificationEvent
    | ErrorEvent,
    Field(discriminator="type"),
]

stream_event_adapter: TypeAdapter[StreamEvent] = TypeAdapter(StreamEvent)
