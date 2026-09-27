"""FinanceAgent end to end with a scripted LLM. Never calls Gemini.

Tests that call FinanceAgent().run(...) need the core runtime and skip until it is merged.
"""

import re
from collections.abc import Callable
from typing import Any, ClassVar

import pytest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool

from app.agents.finance.agent import FinanceAgent
from app.agents.finance.card import FINANCE_CARD
from app.core.base_agent import DepartmentAgent
from app.core.context import RequestContext, request_scope
from app.core.contracts import AgentCard, AgentResult, Evidence, Skill
from app.core.events import AgentMode
from app.core.llm import override_llm
from app.core.registry import registry
from tests.support.fake_llm import ScriptedChatModel, tool_call
from tests.support.markers import requires_runtime

Step = AIMessage | Callable[[list[BaseMessage]], AIMessage]


class DynamicScriptedModel(ScriptedChatModel):
    """ScriptedChatModel whose steps may be callables that build the reply from the messages so
    far, so the final answer can cite refs (e.g. peer message ids) only known at run time."""

    steps: list[Any] = []

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.calls.append(list(messages))
        if self._cursor >= len(self.steps):
            raise AssertionError(f"DynamicScriptedModel ran out of steps after {self._cursor}")
        step = self.steps[self._cursor]
        self._cursor += 1
        message = step(messages) if callable(step) else step
        return ChatResult(generations=[ChatGeneration(message=message)])


def _tool_refs(messages: list[BaseMessage]) -> list[str]:
    refs: list[str] = []
    for message in messages:
        if isinstance(message, ToolMessage):
            refs += re.findall(r'"source_ref":\s*"([^"]+)"', str(message.content))
            refs += re.findall(r"(peer:[\w:\-]+)", str(message.content))
    return list(dict.fromkeys(refs))


def _answer_citing_everything(answer: str, status: str = "ok") -> Callable:
    def build(messages: list[BaseMessage]) -> AIMessage:
        return tool_call(
            "AgentAnswer",
            {"status": status, "answer": answer, "evidence_refs": _tool_refs(messages)},
        )

    return build


@pytest.fixture
def request_context():
    with request_scope(RequestContext(request_id="req-finance-test", conversation_id="conv-1")):
        yield


def test_card_is_routable():
    assert FINANCE_CARD.name == "finance"
    assert set(FINANCE_CARD.owned_data) == {"budgets", "expenses", "payroll"}
    assert all(skill.example_questions for skill in FINANCE_CARD.skills)


def test_agent_is_registered_with_tools_and_prompt():
    agent = registry.get("finance")
    assert isinstance(agent, FinanceAgent)
    assert {t.name for t in agent.get_tools()} >= {
        "get_project_budget",
        "get_project_spend",
        "budget_vs_actual",
        "expenses_by_category",
        "people_cost",
        "top_overruns",
    }
    prompt = agent.system_prompt()
    assert "ask_agent" in prompt and "HR" in prompt and "evidence_refs" in prompt


@requires_runtime
async def test_run_returns_agent_result_with_evidence(seeded_db, scenarios, request_context):
    over = next(s for s in scenarios["scenarios"] if s["id"] == "over_budget")
    llm = DynamicScriptedModel(
        steps=[
            tool_call(
                "budget_vs_actual", {"period": over["period"], "project": over["project_name"]}
            ),
            _answer_citing_everything(f"{over['project_name']} is over budget."),
        ]
    )
    with override_llm(lambda role: llm):
        result = await FinanceAgent().run(
            f"What is spend vs budget on {over['project_name']} in {over['period']}?",
            subtask_id="t1",
        )
    assert isinstance(result, AgentResult)
    assert result.agent == "finance" and result.subtask_id == "t1"
    assert result.status == "ok", result.error
    assert result.evidence
    assert all(isinstance(e, Evidence) for e in result.evidence)
    assert any(e.source_ref.startswith("budgets:id=") for e in result.evidence)
    assert all(e.source_type == "db" for e in result.evidence)


class FakeHRAgent(DepartmentAgent):
    """Peer that owns allocations. Returns a canned answer without an LLM."""

    card: ClassVar[AgentCard] = AgentCard(
        name="fake_hr",
        department="HR",
        description="Owns employees and project allocations (who works on which project).",
        skills=[Skill(name="project_staffing", description="Who is allocated to a project")],
        owned_data=["employees", "allocations"],
    )
    questions: ClassVar[list[str]] = []
    employee_ids: ClassVar[list[int]] = []

    def get_tools(self) -> list[BaseTool]:
        return []

    def system_prompt(self) -> str:
        return "Fake HR peer."

    async def run(
        self,
        instruction: str,
        *,
        subtask_id: str,
        mode: AgentMode = "task",
        hop_count: int = 0,
        chain: list[str] | None = None,
        context: list[AgentResult] | None = None,
        run_name: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AgentResult:
        FakeHRAgent.questions.append(instruction)
        ids = FakeHRAgent.employee_ids
        return AgentResult(
            agent=self.name,
            subtask_id=subtask_id,
            status="ok",
            answer=f"Employees allocated to the project: {ids}",
            evidence=[
                Evidence(
                    source_type="db",
                    source_ref=f"allocations:employee_id={i}",
                    summary=f"Employee {i} is allocated",
                )
                for i in ids
            ],
            peer_messages=[],
        )


@requires_runtime
async def test_uses_ask_agent_for_project_people_cost(
    seeded_db, scenarios, isolated_registry, request_context
):
    over = next(s for s in scenarios["scenarios"] if s["id"] == "over_budget")
    FakeHRAgent.questions = []
    FakeHRAgent.employee_ids = [over["lead_employee_id"]]
    registry.register(FakeHRAgent())
    registry.register(FinanceAgent())

    def cost_the_team(messages: list[BaseMessage]) -> AIMessage:
        peer_reply = next(
            m for m in reversed(messages) if isinstance(m, ToolMessage) and "peer" in str(m.content)
        )
        assert str(over["lead_employee_id"]) in str(peer_reply.content)
        return tool_call(
            "people_cost",
            {"employee_ids": FakeHRAgent.employee_ids, "period": over["period"]},
        )

    llm = DynamicScriptedModel(
        steps=[
            tool_call(
                "ask_agent",
                {
                    "target": "fake_hr",
                    "question": f"Which employee ids are allocated to project "
                    f"{over['project_id']} ({over['project_name']})?",
                },
            ),
            cost_the_team,
            _answer_citing_everything(f"People cost of the {over['project_name']} team."),
        ]
    )
    with override_llm(lambda role: llm):
        result = await FinanceAgent().run(
            f"What is the people cost of the team on {over['project_name']} in {over['period']}?",
            subtask_id="t2",
        )

    assert result.status in {"ok", "partial"}, result.error
    assert FakeHRAgent.questions, "Finance never asked the HR peer"
    assert result.peer_messages
    assert any(e.source_type == "peer" for e in result.evidence)
    assert any(e.source_ref.startswith("payroll:") for e in result.evidence)
    # Finance must not have fetched allocations itself: it has no such tool.
    assert not any("alloc" in t.name for t in FinanceAgent().get_tools())
