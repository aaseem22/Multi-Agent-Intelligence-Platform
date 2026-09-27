"""LangGraph state definitions.

The top-level graph is checkpointed per conversation (thread_id = conversation_id), so the
conversation `history` persists across turns while per-turn fields are reset in `intake`.
Pydantic objects are stored as `model_dump(mode="json")` dicts so checkpoints serialise cleanly.
"""

from typing import Annotated, Any, TypedDict

RESET = "__reset__"


def merge_results(
    left: dict[str, dict[str, Any]] | None, right: dict[str, dict[str, Any]] | str | None
) -> dict[str, dict[str, Any]]:
    """Merge AgentResults by subtask_id. Returning RESET clears them for a new turn."""
    if right == RESET:
        return {}
    merged = dict(left or {})
    if isinstance(right, dict):
        merged.update(right)
    return merged


def append_or_reset(left: list[Any] | None, right: list[Any] | str | None) -> list[Any]:
    """Append items. Returning RESET clears the list for a new turn."""
    if right == RESET:
        return []
    return list(left or []) + list(right or [])


class OrchestratorState(TypedDict, total=False):
    request_id: str
    conversation_id: str
    question: str
    history: Annotated[list[dict[str, str]], append_or_reset]
    plan: dict[str, Any] | None  # Plan
    results: Annotated[dict[str, dict[str, Any]], merge_results]  # subtask_id -> AgentResult
    dispatched: Annotated[list[str], append_or_reset]  # subtask ids already sent
    ready: list[dict[str, Any]]  # Subtasks dispatched in the current wave
    final: dict[str, Any] | None  # FinalAnswer
    clarification: str | None
    error: str | None


class AgentTaskState(TypedDict):
    """Payload of one Send("run_agent")."""

    subtask: dict[str, Any]  # Subtask
    context: list[dict[str, Any]]  # AgentResults of the subtasks it depends on


class EvalTaskState(TypedDict):
    """Payload of one Send("eval_gate")."""

    subtask: dict[str, Any]
    result: dict[str, Any]  # AgentResult


class AgentRunState(TypedDict, total=False):
    """State of one department agent subgraph: react -> finalize -> self_check."""

    instruction: str
    answer: dict[str, Any] | None  # AgentAnswer produced by the LLM
    last_text: str
    result: dict[str, Any] | None  # AgentResult
