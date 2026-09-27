"""Top-level graph, built from the registry and the supervisor (CEO). Department-agnostic.

    START -> intake -> plan -> clarify -> respond -> END
                           \\-> dispatch --Send--> run_agent --Send--> eval_gate -> collect
                                   ^                                                  |
                                   \\------------ dependent subtasks remain ----------/
                                                               otherwise -> synthesise -> respond

The graph is checkpointed per conversation (thread_id = conversation_id). `Orchestrator.stream`
runs one stakeholder request and yields the SSE events emitted along the way.
"""

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Literal

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, Send

from app.core import eval_hooks, observability
from app.core.a2a import new_message_id, publish
from app.core.config import BACKEND_DIR, get_settings
from app.core.context import RequestContext, current_request, emit, request_scope
from app.core.contracts import (
    A2AMessage,
    AgentCard,
    AgentResult,
    EvalResult,
    FinalAnswer,
    Plan,
    Subtask,
)
from app.core.events import (
    AgentResultEvent,
    BaseEvent,
    ClarificationEvent,
    ErrorEvent,
    FinalEvent,
    PlanEvent,
)
from app.core.llm import get_agent_semaphore
from app.core.registry import registry
from app.core.state import (
    RESET,
    AgentTaskState,
    EvalTaskState,
    OrchestratorState,
)

logger = logging.getLogger(__name__)

SUPERVISOR_FALLBACK_NAME = "ceo"
HISTORY_TURNS_FOR_PLANNER = 10
FALLBACK_CLARIFICATION = (
    "I could not work out which departments should handle that. Could you say more about "
    "what you want to know?"
)
_DONE = object()


# --- helpers ---


def _supervisor_name() -> str:
    supervisor = registry.supervisor
    return supervisor.card.name if supervisor else SUPERVISOR_FALLBACK_NAME


def _request_ids() -> tuple[str, str | None]:
    ctx = current_request()
    return (ctx.request_id, ctx.trace_id) if ctx else ("local", None)


async def _publish_ceo_message(
    type_: Literal["task", "result", "error", "clarification"],
    sender: str,
    recipient: str,
    content: str,
    payload: dict[str, Any],
) -> None:
    request_id, trace_id = _request_ids()
    ceo = _supervisor_name()
    await publish(
        A2AMessage(
            id=new_message_id(),
            request_id=request_id,
            trace_id=trace_id,
            sender=sender,
            recipient=recipient,
            type=type_,
            content=content,
            payload=payload,
            hop_count=0,
            chain=[ceo] if sender == ceo else [ceo, sender],
        )
    )


def _failed_result(subtask: Subtask, error: str) -> AgentResult:
    return AgentResult(
        agent=subtask.assigned_to,
        subtask_id=subtask.id,
        status="failed",
        answer="",
        evidence=[],
        peer_messages=[],
        error=error,
    )


def _normalise_plan(plan: Plan) -> Plan:
    """Give every subtask a unique id and drop self/unknown dependency ids."""
    seen: set[str] = set()
    subtasks: list[Subtask] = []
    for index, subtask in enumerate(plan.subtasks, start=1):
        subtask_id = subtask.id.strip() or f"t{index}"
        if subtask_id in seen:
            subtask_id = f"{subtask_id}_{index}"
        seen.add(subtask_id)
        subtasks.append(subtask.model_copy(update={"id": subtask_id}))
    ids = {s.id for s in subtasks}
    for subtask in subtasks:
        dropped = [d for d in subtask.depends_on if d not in ids or d == subtask.id]
        if dropped:
            logger.warning("Subtask %s: dropping invalid depends_on %s", subtask.id, dropped)
            subtask.depends_on = [d for d in subtask.depends_on if d not in dropped]
    clarification = plan.clarification if not subtasks else None
    if not subtasks and not clarification:
        clarification = FALLBACK_CLARIFICATION
    return Plan(subtasks=subtasks, clarification=clarification, rationale=plan.rationale)


def fallback_answer(subtasks: list[Subtask], results: list[AgentResult]) -> FinalAnswer:
    """Deterministic synthesis used when the supervisor's synthesis fails."""
    by_id = {r.subtask_id: r for r in results}
    parts: list[str] = []
    unanswered: list[str] = []
    for subtask in subtasks:
        result = by_id.get(subtask.id)
        if result is None or result.status == "failed":
            error = result.error if result else "no result"
            unanswered.append(
                f"{subtask.assigned_to} could not answer '{subtask.instruction}': {error}"
            )
        else:
            parts.append(f"{result.agent}: {result.answer}")
    return FinalAnswer(
        answer="\n\n".join(parts) or "No department agent could answer this request.",
        unanswered=unanswered,
    )


def _plan_of(state: OrchestratorState) -> Plan:
    return Plan.model_validate(state.get("plan") or {})


def _results_of(state: OrchestratorState) -> dict[str, AgentResult]:
    return {k: AgentResult.model_validate(v) for k, v in (state.get("results") or {}).items()}


# --- nodes ---


async def intake(state: OrchestratorState) -> dict[str, Any]:
    """Normalise the question and reset per-turn fields (history persists via checkpointer)."""
    return {
        "question": " ".join((state.get("question") or "").split()),
        "plan": None,
        "results": RESET,
        "dispatched": RESET,
        "ready": [],
        "final": None,
        "clarification": None,
        "error": None,
    }


async def plan_node(state: OrchestratorState) -> dict[str, Any]:
    supervisor = registry.supervisor
    if supervisor is None:
        return {"error": "No supervisor agent is registered"}
    cards: list[AgentCard] = registry.department_cards()
    history = (state.get("history") or [])[-2 * HISTORY_TURNS_FOR_PLANNER :]
    try:
        # The supervisor owns its LLM calls, including transport retries.
        raw_plan = await supervisor.plan(state["question"], history, cards)
        plan = _normalise_plan(raw_plan)
    except Exception as exc:
        logger.exception("Planning failed")
        return {"error": f"Planning failed: {type(exc).__name__}: {exc}"}
    if plan.subtasks:
        emit(PlanEvent, subtasks=plan.subtasks, rationale=plan.rationale)
    return {"plan": plan.model_dump(mode="json"), "clarification": plan.clarification}


def route_after_plan(state: OrchestratorState) -> Literal["clarify", "dispatch", "respond"]:
    if state.get("error"):
        return "respond"
    if state.get("clarification"):
        return "clarify"
    return "dispatch"


async def clarify(state: OrchestratorState) -> dict[str, Any]:
    await _publish_ceo_message(
        "clarification", _supervisor_name(), "user", state["clarification"] or "", {}
    )
    return {}


async def dispatch(state: OrchestratorState) -> dict[str, Any]:
    """Pick subtasks whose dependencies are done; fail those that can never become ready."""
    plan = _plan_of(state)
    done = set((state.get("results") or {}).keys())
    dispatched = set(state.get("dispatched") or [])
    pending = [s for s in plan.subtasks if s.id not in dispatched]
    ready = [s for s in pending if all(d in done for d in s.depends_on)]
    in_flight = dispatched - done
    failed: dict[str, dict[str, Any]] = {}
    if not ready and pending and not in_flight:
        for subtask in pending:
            result = _failed_result(
                subtask, "unresolvable dependencies: " + ", ".join(subtask.depends_on)
            )
            emit(AgentResultEvent, mode="task", result=result)
            failed[subtask.id] = result.model_dump(mode="json")
    ceo = _supervisor_name()
    for subtask in ready:
        await _publish_ceo_message(
            "task",
            ceo,
            subtask.assigned_to,
            subtask.instruction,
            {"subtask_id": subtask.id, "depends_on": subtask.depends_on},
        )
    return {
        "ready": [s.model_dump(mode="json") for s in ready],
        "dispatched": [s.id for s in ready] + list(failed),
        "results": failed,
    }


def route_dispatch(state: OrchestratorState) -> list[Send] | Literal["synthesise"]:
    ready = state.get("ready") or []
    if not ready:
        return "synthesise"
    results = state.get("results") or {}
    return [
        Send(
            "run_agent",
            AgentTaskState(
                subtask=subtask,
                context=[results[d] for d in subtask.get("depends_on", []) if d in results],
            ),
        )
        for subtask in ready
    ]


async def run_agent(state: AgentTaskState) -> Command[Literal["eval_gate"]]:
    subtask = Subtask.model_validate(state["subtask"])
    context = [AgentResult.model_validate(r) for r in state.get("context", [])]
    agent = registry.get(subtask.assigned_to)
    if agent is None:
        result = _failed_result(subtask, f"unknown agent '{subtask.assigned_to}'")
        emit(AgentResultEvent, mode="task", result=result)
    else:
        async with get_agent_semaphore():
            result = await agent.run(
                subtask.instruction, subtask_id=subtask.id, mode="task", context=context
            )
    return Command(
        goto=Send(
            "eval_gate",
            EvalTaskState(
                subtask=subtask.model_dump(mode="json"), result=result.model_dump(mode="json")
            ),
        )
    )


def _record(evaluation: EvalResult, result: AgentResult) -> None:
    observability.record_eval(evaluation, result.agent, result.subtask_id)
    action = eval_hooks.recovery_router(evaluation)
    if action != "pass":
        logger.info(
            "Recovery action %r requested for %s; not implemented yet", action, result.subtask_id
        )


async def eval_gate(state: EvalTaskState) -> dict[str, Any]:
    subtask = Subtask.model_validate(state["subtask"])
    result = AgentResult.model_validate(state["result"])
    for evaluation in (
        await eval_hooks.independent_eval(result, subtask),
        await eval_hooks.evidence_check(result),
    ):
        _record(evaluation, result)
    await _publish_ceo_message(
        "error" if result.status == "failed" else "result",
        result.agent,
        _supervisor_name(),
        result.answer or result.error or "",
        {
            "subtask_id": result.subtask_id,
            "status": result.status,
            "evidence_refs": [e.source_ref for e in result.evidence],
        },
    )
    return {"results": {result.subtask_id: result.model_dump(mode="json")}}


async def collect(state: OrchestratorState) -> dict[str, Any]:
    return {}


def route_after_collect(state: OrchestratorState) -> Literal["dispatch", "synthesise"]:
    plan = _plan_of(state)
    done = set((state.get("results") or {}).keys())
    return "dispatch" if any(s.id not in done for s in plan.subtasks) else "synthesise"


async def synthesise(state: OrchestratorState) -> dict[str, Any]:
    subtasks = _plan_of(state).subtasks
    results_by_id = _results_of(state)
    results = [results_by_id[s.id] for s in subtasks if s.id in results_by_id]
    supervisor = registry.supervisor
    try:
        if supervisor is None:
            raise RuntimeError("No supervisor agent is registered")
        final = await supervisor.synthesise(state["question"], subtasks, results)
    except Exception as exc:
        logger.exception("Synthesis failed; using fallback answer")
        emit(
            ErrorEvent,
            message=f"Synthesis failed ({exc}); showing agent answers directly",
            agent=_supervisor_name(),
        )
        final = fallback_answer(subtasks, results)
    return {"final": final.model_dump(mode="json")}


async def respond(state: OrchestratorState) -> dict[str, Any]:
    ctx = current_request()
    trace_url = ctx.trace_url if ctx else None
    question = state.get("question", "")
    if state.get("error"):
        kind, text, payload = "error", state["error"], {"error": state["error"]}
        emit(ErrorEvent, message=state["error"])
    elif state.get("final") is not None:
        final = FinalAnswer.model_validate(state["final"])
        results = list(_results_of(state).values())
        kind, text = "final", final.answer
        payload = {
            "answer": final.model_dump(mode="json"),
            "results": [r.model_dump(mode="json") for r in results],
        }
        emit(FinalEvent, answer=final, results=results, trace_url=trace_url)
    else:
        kind, text = "clarification", state.get("clarification") or FALLBACK_CLARIFICATION
        payload = {"question": text}
        emit(ClarificationEvent, question=text)
    await _save_turn(state, kind, text, payload, trace_url)
    return {
        "history": [
            {"role": "user", "content": question},
            {"role": "assistant", "content": text},
        ]
    }


async def _save_turn(
    state: OrchestratorState, kind: str, text: str, payload: dict[str, Any], trace_url: str | None
) -> None:
    try:
        from app.data.repositories import platform

        await platform.save_turn(
            request_id=state["request_id"],
            conversation_id=state["conversation_id"],
            question=state.get("question", ""),
            kind=kind,
            answer=text,
            payload=payload,
            trace_url=trace_url,
        )
    except Exception as exc:
        logger.warning("Could not save chat turn: %s", exc)


def build_graph(checkpointer: BaseCheckpointSaver | None = None) -> CompiledStateGraph:
    builder = StateGraph(OrchestratorState)
    builder.add_node("intake", intake)
    builder.add_node("plan", plan_node)
    builder.add_node("clarify", clarify)
    builder.add_node("dispatch", dispatch)
    builder.add_node("run_agent", run_agent, destinations=("eval_gate",))
    builder.add_node("eval_gate", eval_gate)
    builder.add_node("collect", collect)
    builder.add_node("synthesise", synthesise)
    builder.add_node("respond", respond)
    builder.add_edge(START, "intake")
    builder.add_edge("intake", "plan")
    builder.add_conditional_edges("plan", route_after_plan, ["clarify", "dispatch", "respond"])
    builder.add_edge("clarify", "respond")
    builder.add_conditional_edges("dispatch", route_dispatch, ["run_agent", "synthesise"])
    builder.add_edge("eval_gate", "collect")
    builder.add_conditional_edges("collect", route_after_collect, ["dispatch", "synthesise"])
    builder.add_edge("synthesise", "respond")
    builder.add_edge("respond", END)
    return builder.compile(checkpointer=checkpointer, name="orchestrator")


# --- public entry point ---


def _new_id() -> str:
    return uuid.uuid4().hex


class Orchestrator:
    """Runs stakeholder requests through the top-level graph and streams their events."""

    def __init__(
        self,
        *,
        checkpointer: BaseCheckpointSaver | None = None,
        checkpoint_path: str | None = None,
    ) -> None:
        self._checkpointer = checkpointer
        self._checkpoint_path = checkpoint_path
        self._owns_checkpointer = checkpointer is None
        self._connection: Any = None
        self._graph: CompiledStateGraph | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        async with self._lock:
            if self._graph is not None:
                return
            if self._checkpointer is None:
                self._checkpointer = await self._open_sqlite_checkpointer()
            self._graph = build_graph(self._checkpointer)

    async def _open_sqlite_checkpointer(self) -> BaseCheckpointSaver:
        import aiosqlite
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        path = Path(self._checkpoint_path or get_settings().checkpoint_db_path)
        if not path.is_absolute():
            path = (BACKEND_DIR / path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = await aiosqlite.connect(str(path))
        saver = AsyncSqliteSaver(self._connection)
        await saver.setup()
        return saver

    async def aclose(self) -> None:
        async with self._lock:
            if self._connection is not None:
                await self._connection.close()
                self._connection = None
            if self._owns_checkpointer:
                self._checkpointer = None
            self._graph = None
        observability.shutdown()

    @property
    def graph(self) -> CompiledStateGraph:
        if self._graph is None:
            raise RuntimeError("Orchestrator.start() has not been called")
        return self._graph

    async def stream(
        self, message: str, conversation_id: str | None = None
    ) -> AsyncIterator[BaseEvent]:
        """Run one stakeholder request, yielding events until it finishes.

        The graph runs in a producer task; if the consumer stops early (client disconnect),
        the producer is cancelled.
        """
        await self.start()
        ctx = RequestContext(
            request_id=_new_id(),
            conversation_id=conversation_id or _new_id(),
            queue=asyncio.Queue(),
        )
        producer = asyncio.create_task(self._produce(ctx, message))
        producer.add_done_callback(lambda _: ctx.queue.put_nowait(_DONE))  # type: ignore[union-attr,arg-type]
        try:
            while True:
                event = await ctx.queue.get()  # type: ignore[union-attr]
                if event is _DONE:
                    break
                yield event
        finally:
            if not producer.done():
                producer.cancel()
                try:
                    await producer
                except (asyncio.CancelledError, Exception):
                    pass

    async def _produce(self, ctx: RequestContext, message: str) -> None:
        with request_scope(ctx):
            try:
                await self._prepare_conversation(ctx, message)
                async with observability.request_trace(
                    ctx.request_id, ctx.conversation_id, message
                ) as trace:
                    ctx.trace_id, ctx.trace_url = trace.trace_id, trace.trace_url
                    ctx.langfuse_callbacks = trace.callbacks
                    state = await self.graph.ainvoke(
                        {
                            "request_id": ctx.request_id,
                            "conversation_id": ctx.conversation_id,
                            "question": message,
                        },
                        config=self._config(ctx),
                    )
                    trace.set_output(
                        (state or {}).get("final") or (state or {}).get("clarification")
                    )
            except asyncio.CancelledError:
                logger.info("Request cancelled")
                raise
            except Exception as exc:
                logger.exception("Request failed")
                emit(ErrorEvent, message=f"Request failed: {type(exc).__name__}: {exc}")
                await self._save_failed_turn(ctx, message, str(exc))

    def _config(self, ctx: RequestContext) -> dict[str, Any]:
        return {
            "configurable": {"thread_id": ctx.conversation_id},
            "callbacks": ctx.langfuse_callbacks,
            "recursion_limit": get_settings().graph_recursion_limit,
            "run_name": "orchestrator",
            "metadata": {
                "request_id": ctx.request_id,
                "langfuse_session_id": ctx.conversation_id,
            },
        }

    @staticmethod
    async def _prepare_conversation(ctx: RequestContext, message: str) -> None:
        try:
            from app.data.repositories import platform

            await platform.ensure_conversation(ctx.conversation_id, message[:80] or "Conversation")
            await platform.save_turn(
                request_id=ctx.request_id,
                conversation_id=ctx.conversation_id,
                question=message,
                kind="pending",
            )
        except Exception as exc:
            logger.warning("Could not persist conversation: %s", exc)

    @staticmethod
    async def _save_failed_turn(ctx: RequestContext, message: str, error: str) -> None:
        try:
            from app.data.repositories import platform

            await platform.save_turn(
                request_id=ctx.request_id,
                conversation_id=ctx.conversation_id,
                question=message,
                kind="error",
                answer=error,
                payload={"error": error},
                trace_url=ctx.trace_url,
            )
        except Exception as exc:
            logger.warning("Could not save failed turn: %s", exc)

    # --- read models used by the API ---

    @staticmethod
    def agent_cards() -> list[AgentCard]:
        return registry.list_cards()

    @staticmethod
    async def list_conversations() -> list[dict[str, Any]]:
        from app.data.repositories import platform

        return await platform.list_conversations()

    @staticmethod
    async def get_conversation(conversation_id: str) -> dict[str, Any] | None:
        from app.data.repositories import platform

        return await platform.get_conversation(conversation_id)

    @staticmethod
    async def a2a_log(conversation_id: str) -> list[A2AMessage]:
        from app.data.repositories import platform

        return await platform.list_a2a_messages(conversation_id=conversation_id)

    @staticmethod
    async def health() -> dict[str, Any]:
        from app.data.db import ping

        settings = get_settings()
        database = await ping()
        return {
            "status": "ok" if database else "degraded",
            "database": database,
            "github_token": bool(settings.github_token),
            "langfuse": settings.langfuse_enabled,
            "agents": [c.name for c in registry.list_cards()],
        }
