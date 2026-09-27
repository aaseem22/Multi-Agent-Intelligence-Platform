"""Core contracts shared by every agent. Frozen after Phase 0."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(UTC)


class Skill(BaseModel):
    name: str
    description: str
    example_questions: list[str] = []


class AgentCard(BaseModel):
    name: str
    department: str
    description: str
    skills: list[Skill]
    owned_data: list[str]
    accepts_peer_requests: bool = True


class Evidence(BaseModel):
    source_type: Literal["db", "github", "peer"]
    source_ref: str
    summary: str
    data: dict | None = None


class Subtask(BaseModel):
    id: str
    assigned_to: str
    instruction: str
    depends_on: list[str] = []


A2AMessageType = Literal[
    "task", "peer_request", "peer_response", "result", "error", "clarification"
]


class A2AMessage(BaseModel):
    id: str
    request_id: str
    trace_id: str | None = None
    sender: str
    recipient: str
    type: A2AMessageType
    content: str
    payload: dict = {}
    hop_count: int = 0
    chain: list[str] = []
    created_at: datetime = Field(default_factory=utcnow)


AgentStatus = Literal["ok", "partial", "failed", "needs_clarification"]


class AgentResult(BaseModel):
    agent: str
    subtask_id: str
    status: AgentStatus
    answer: str
    evidence: list[Evidence]
    peer_messages: list[str]
    error: str | None = None


class EvalResult(BaseModel):
    passed: bool
    stage: Literal["self", "independent", "evidence"]
    reasons: list[str] = []
    score: float | None = None


# --- Structured outputs exchanged between the orchestrator and the supervisor (CEO) ---


class Plan(BaseModel):
    """CEO planner output: either subtasks to dispatch or one clarification question."""

    subtasks: list[Subtask] = []
    clarification: str | None = None
    rationale: str = ""


class Claim(BaseModel):
    text: str
    evidence_refs: list[str] = Field(
        default=[], description="source_ref values of the Evidence supporting this claim"
    )
    agents: list[str] = []


class FinalAnswer(BaseModel):
    """CEO synthesis output."""

    answer: str
    claims: list[Claim] = []
    unanswered: list[str] = Field(
        default=[], description="Parts of the question that could not be answered, and why"
    )


class AgentAnswer(BaseModel):
    """Structured output a department agent's LLM produces. The base agent turns it into an
    AgentResult, attaching only evidence that its own tools or peers actually returned."""

    status: AgentStatus = Field(
        description="ok when fully answered, partial when some part is missing, "
        "needs_clarification when the instruction is ambiguous or outside every agent's scope"
    )
    answer: str = Field(description="Concise answer to the instruction, with figures and names")
    evidence_refs: list[str] = Field(
        default=[],
        description="source_ref values, copied exactly from tool or ask_agent outputs, "
        "that support the answer",
    )
