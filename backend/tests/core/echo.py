"""Throwaway Echo agents and supervisor that register through the registry. They prove the
runtime, ask_agent guards, orchestrator and SSE work without any real department agent."""

import asyncio
import threading
from collections.abc import Callable, Sequence
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool, tool
from pydantic import PrivateAttr

from app.core.base_agent import DepartmentAgent, db_evidence, evidence_result
from app.core.contracts import (
    AgentCard,
    AgentResult,
    Claim,
    FinalAnswer,
    Plan,
    Skill,
    Subtask,
)
from app.core.registry import registry
from tests.support.fake_llm import tool_call


def agent_marker(name: str) -> str:
    return f"[agent:{name}]"


def answer(status: str, text: str, refs: list[str] | None = None) -> AIMessage:
    return tool_call("AgentAnswer", {"status": status, "answer": text, "evidence_refs": refs or []})


class Concurrency:
    """Tracks how many echo tool calls run at the same time."""

    def __init__(self) -> None:
        self.current = 0
        self.peak = 0


def make_echo_agent(
    name: str,
    *,
    accepts_peer_requests: bool = True,
    concurrency: Concurrency | None = None,
    description: str | None = None,
) -> DepartmentAgent:
    @tool(f"{name}_lookup")
    async def lookup(key: str) -> str:
        """Look up a key in this agent's store."""
        if concurrency is not None:
            concurrency.current += 1
            concurrency.peak = max(concurrency.peak, concurrency.current)
            await asyncio.sleep(0.05)
            concurrency.current -= 1
        if key == "boom":
            raise RuntimeError("store unavailable")
        return evidence_result(
            {"key": key, "value": key.upper()},
            [db_evidence(f"{name}_store:key={key}", f"{name} value for {key}")],
        )

    card = AgentCard(
        name=name,
        department=name.title(),
        description=description or f"Owns the {name} store and answers {name} questions.",
        skills=[Skill(name="lookup", description="Look up keys", example_questions=["key?"])],
        owned_data=[f"{name}_store"],
        accepts_peer_requests=accepts_peer_requests,
    )

    class EchoAgent(DepartmentAgent):
        def get_tools(self) -> list[BaseTool]:
            return [lookup]

        def system_prompt(self) -> str:
            return f"{agent_marker(name)} You are the {name} agent."

    EchoAgent.card = card
    EchoAgent.__name__ = f"EchoAgent_{name}"
    return EchoAgent()


class EchoSupervisor:
    """Supervisor whose plans are scripted; synthesis joins answers and cites all evidence."""

    card = AgentCard(
        name="ceo",
        department="Executive",
        description="Plans and synthesises.",
        skills=[],
        owned_data=[],
        accepts_peer_requests=False,
    )

    def __init__(
        self,
        plans: list[Plan] | None = None,
        synthesise_error: Exception | None = None,
    ) -> None:
        self.plans = list(plans or [])
        self.synthesise_error = synthesise_error
        self.plan_calls: list[tuple[str, list[dict[str, str]], list[str]]] = []
        self.synth_calls: list[tuple[list[Subtask], list[AgentResult]]] = []

    async def plan(
        self, question: str, history: list[dict[str, str]], cards: list[AgentCard]
    ) -> Plan:
        self.plan_calls.append((question, list(history), [c.name for c in cards]))
        if not self.plans:
            return Plan(clarification="What would you like to know?")
        return self.plans.pop(0)

    async def synthesise(
        self, question: str, subtasks: list[Subtask], results: list[AgentResult]
    ) -> FinalAnswer:
        self.synth_calls.append((subtasks, results))
        if self.synthesise_error is not None:
            raise self.synthesise_error
        return FinalAnswer(
            answer=" | ".join(f"{r.agent}: {r.answer}" for r in results),
            claims=[
                Claim(
                    text=r.answer,
                    evidence_refs=[e.source_ref for e in r.evidence],
                    agents=[r.agent],
                )
                for r in results
            ],
            unanswered=[f"{r.agent} failed" for r in results if r.status == "failed"],
        )


class RoutedChatModel(BaseChatModel):
    """Fake chat model that serves scripted responses per agent (found via the system prompt
    marker), so parallel agents get deterministic replies. Never calls Gemini."""

    scripts: dict[str, list[Any]] = {}
    _cursors: dict[str, int] = PrivateAttr(default_factory=dict)
    _lock: Any = PrivateAttr(default_factory=threading.Lock)
    seen: list[tuple[str, list[BaseMessage]]] = []

    @property
    def _llm_type(self) -> str:
        return "routed-scripted"

    def _agent_for(self, messages: list[BaseMessage]) -> str:
        system = next((m for m in messages if isinstance(m, SystemMessage)), None)
        text = system.text if system else ""
        for name in self.scripts:
            if agent_marker(name) in text:
                return name
        raise AssertionError(f"No script for system prompt: {text[:80]!r}")

    def _generate(
        self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> ChatResult:
        name = self._agent_for(messages)
        with self._lock:
            cursor = self._cursors.get(name, 0)
            self._cursors[name] = cursor + 1
            self.seen.append((name, list(messages)))
        script = self.scripts[name]
        if cursor >= len(script):
            raise AssertionError(f"{name} ran out of scripted responses")
        item = script[cursor]
        if isinstance(item, Exception):
            raise item
        if callable(item):
            item = item(messages)
        return ChatResult(generations=[ChatGeneration(message=item)])

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> Runnable:
        return self


def register_echo_world(
    *names: str, supervisor: EchoSupervisor | None = None, **agent_kwargs: Any
) -> dict[str, DepartmentAgent]:
    agents = {name: registry.register(make_echo_agent(name, **agent_kwargs)) for name in names}
    if supervisor is not None:
        registry.register_supervisor(supervisor)
    return agents


ScriptItem = AIMessage | Exception | Callable[[list[BaseMessage]], AIMessage]
