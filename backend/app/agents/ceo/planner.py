"""CEO planner: structured-output call returning subtasks or a clarification, then a
deterministic repair pass so the orchestrator only ever sees a valid plan."""

import logging

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from app.agents.ceo.prompts import planner_system_prompt
from app.core.contracts import AgentCard, Plan, Subtask
from app.core.llm import get_llm, with_llm_retries

logger = logging.getLogger(__name__)

HISTORY_TURNS = 10
EMPTY_PLAN_CLARIFICATION = (
    "I could not match your request to any available agent. Could you say which projects, "
    "people, periods or metrics you are asking about?"
)
NO_AGENTS_CLARIFICATION = "No department agents are available to answer this request right now."


def build_messages(
    question: str, history: list[dict[str, str]], cards: list[AgentCard]
) -> list[BaseMessage]:
    messages: list[BaseMessage] = [SystemMessage(planner_system_prompt(cards))]
    for turn in history[-HISTORY_TURNS:]:
        content = turn.get("content", "")
        if not content:
            continue
        role = turn.get("role", "user")
        messages.append(
            AIMessage(content) if role in ("assistant", "ai") else HumanMessage(content)
        )
    messages.append(HumanMessage(question))
    return messages


async def plan(
    question: str, history: list[dict[str, str]], cards: list[AgentCard], *, exclude: str
) -> Plan:
    """Plan `question` across `cards`. `exclude` is the supervisor's own name, never an assignee.
    Transport failures propagate after retries so the orchestrator can report an error."""
    routable = [card for card in cards if card.name != exclude]
    if not routable:
        return Plan(clarification=NO_AGENTS_CLARIFICATION, rationale="no agents registered")
    llm = get_llm("ceo").with_structured_output(Plan)
    messages = build_messages(question, history, routable)
    raw = await with_llm_retries(lambda: llm.ainvoke(messages))
    return validate_plan(_as_plan(raw), routable)


def _as_plan(raw: object) -> Plan:
    if isinstance(raw, Plan):
        return raw
    if isinstance(raw, dict):
        return Plan.model_validate(raw)
    raise TypeError(f"Planner returned {type(raw).__name__}, expected Plan")


def validate_plan(raw: Plan, cards: list[AgentCard]) -> Plan:
    clarification = (raw.clarification or "").strip()
    if clarification:
        return Plan(clarification=clarification, rationale=raw.rationale)
    subtasks = _repair_dependencies(_assign_ids(_repair_assignees(raw.subtasks, cards)))
    if not subtasks:
        return Plan(clarification=EMPTY_PLAN_CLARIFICATION, rationale=raw.rationale)
    return Plan(subtasks=subtasks, rationale=raw.rationale)


def _resolve_assignee(assigned_to: str, cards: list[AgentCard]) -> str | None:
    wanted = assigned_to.strip().lower()
    for card in cards:
        if wanted in (card.name.lower(), card.department.lower()):
            return card.name
    return None


def _repair_assignees(subtasks: list[Subtask], cards: list[AgentCard]) -> list[Subtask]:
    kept = []
    for subtask in subtasks:
        name = _resolve_assignee(subtask.assigned_to, cards)
        if name is None or not subtask.instruction.strip():
            logger.warning(
                "Dropping subtask %s assigned to unknown agent %r", subtask.id, subtask.assigned_to
            )
            continue
        kept.append(subtask.model_copy(update={"assigned_to": name}))
    return kept


def _assign_ids(subtasks: list[Subtask]) -> list[Subtask]:
    """Give every subtask a unique id. Duplicates and blanks are renamed; dependencies on a
    duplicated id keep pointing at its first occurrence."""
    original = {s.id.strip() for s in subtasks}
    used: set[str] = set()
    counter = 0
    fixed = []
    for subtask in subtasks:
        sid = subtask.id.strip()
        if not sid or sid in used:
            counter += 1
            while f"t{counter}" in used or f"t{counter}" in original:
                counter += 1
            sid = f"t{counter}"
        used.add(sid)
        fixed.append(subtask.model_copy(update={"id": sid}))
    return fixed


def _repair_dependencies(subtasks: list[Subtask]) -> list[Subtask]:
    """Keep only dependencies on existing ids, never on self, and drop any edge that would close
    a cycle (edges are accepted in plan order)."""
    ids = {s.id for s in subtasks}
    edges: dict[str, list[str]] = {s.id: [] for s in subtasks}
    for subtask in subtasks:
        for dep in dict.fromkeys(subtask.depends_on):
            if dep in ids and dep != subtask.id and not _reachable(edges, dep, subtask.id):
                edges[subtask.id].append(dep)
    return [s.model_copy(update={"depends_on": edges[s.id]}) for s in subtasks]


def _reachable(edges: dict[str, list[str]], start: str, target: str) -> bool:
    stack, seen = [start], set()
    while stack:
        node = stack.pop()
        if node == target:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(edges.get(node, []))
    return False
