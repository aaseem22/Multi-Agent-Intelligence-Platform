"""HR agent: card, prompt, registration, and mocked-LLM runs. Never calls Gemini."""

import ast
import json
import re
from pathlib import Path
from typing import Any, ClassVar

from langchain_core.messages import BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool

import app.agents.hr.tools as hr_tools_module
from app.agents.hr.agent import HRAgent
from app.agents.hr.card import HR_CARD
from app.agents.hr.prompts import HR_SYSTEM_PROMPT
from app.core.base_agent import DepartmentAgent
from app.core.context import RequestContext, request_scope
from app.core.contracts import AgentCard, AgentResult, Evidence, Skill
from app.core.llm import override_llm
from app.core.registry import registry
from tests.support.fake_llm import ScriptedChatModel, tool_call
from tests.support.markers import requires_runtime

PEER_REF = re.compile(r"peer:[^\"'\s,\]]+")


# --- static checks ----------------------------------------------------------------------


def test_card_describes_hr_domain():
    assert HR_CARD.name == "hr"
    assert set(HR_CARD.owned_data) == {"employees", "allocations", "leave", "open_positions"}
    assert "payroll" not in HR_CARD.owned_data
    assert HR_CARD.accepts_peer_requests
    assert all(skill.example_questions for skill in HR_CARD.skills)


def test_agent_is_registered():
    agent = registry.get("hr")
    assert isinstance(agent, HRAgent)
    assert [t.name for t in agent.get_tools()] == [t.name for t in hr_tools_module.HR_TOOLS]
    assert agent.system_prompt() == HR_SYSTEM_PROMPT


def test_prompt_covers_evidence_payroll_and_peers():
    prompt = HR_SYSTEM_PROMPT.lower()
    assert "source_ref" in prompt and "evidence_refs" in prompt
    assert "payroll" in prompt and "finance" in prompt
    assert "ask_agent" in prompt and "peer:" in prompt


def test_tools_import_only_owned_data():
    tree = ast.parse(Path(hr_tools_module.__file__).read_text())
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
            imported.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    data_imports = {m for m in imported if m.startswith("app.data")}
    allowed = {
        "app.data.periods",
        "app.data.repositories",
        "app.data.repositories.hr",
        "app.data.repositories.reference",
    }
    assert {m for m in data_imports if not m.startswith("app.data.periods.")} <= allowed
    assert not any("payroll" in m or "finance" in m or "tech" in m for m in imported)


# --- mocked-LLM runs --------------------------------------------------------------------


class PeerCitingModel(ScriptedChatModel):
    """Scripted model whose final answer cites whatever peer: refs ask_agent returned."""

    answer: str = ""
    hr_refs: list[str] = []

    def _generate(
        self, messages: list[BaseMessage], stop: list[str] | None = None, **kwargs: Any
    ) -> ChatResult:
        last = messages[-1]
        if isinstance(last, ToolMessage) and last.name == "ask_agent":
            self.calls.append(list(messages))
            peer_refs = PEER_REF.findall(str(last.content))
            final = tool_call(
                "AgentAnswer",
                {
                    "status": "ok",
                    "answer": self.answer,
                    "evidence_refs": self.hr_refs + peer_refs,
                },
            )
            return ChatResult(generations=[ChatGeneration(message=final)])
        return super()._generate(messages, stop=stop, **kwargs)


class FakeFinancePeer(DepartmentAgent):
    card: ClassVar[AgentCard] = AgentCard(
        name="finance",
        department="Finance",
        description="Owns budgets, expenses and payroll (people cost).",
        skills=[Skill(name="people_cost", description="Payroll cost of employees")],
        owned_data=["budgets", "expenses", "payroll"],
    )
    questions: ClassVar[list[str]] = []

    def get_tools(self) -> list[BaseTool]:
        return []

    def system_prompt(self) -> str:
        return "fake finance peer"

    async def run(self, instruction: str, *, subtask_id: str, **kwargs: Any) -> AgentResult:
        self.questions.append(instruction)
        return AgentResult(
            agent="finance",
            subtask_id=subtask_id,
            status="ok",
            answer="Payroll cost for employee 4 in 2026-Q3 was INR 540000.",
            evidence=[
                Evidence(
                    source_type="db",
                    source_ref="payroll:employee_id=4,period=2026-Q3",
                    summary="Payroll for employee 4 in 2026-Q3",
                )
            ],
            peer_messages=[],
        )


def request_context() -> RequestContext:
    return RequestContext(request_id="req-hr-test", conversation_id="conv-hr-test")


@requires_runtime
async def test_run_returns_agent_result_with_evidence(seeded_db, scenarios):
    s = next(x for x in scenarios["scenarios"] if x["id"] == "understaffed")
    start, end = s["overlapping_leave_window"]
    expected = json.loads(
        await hr_tools_module.leave_overlap.ainvoke(
            {"project": str(s["project_id"]), "start": start, "end": end}
        )
    )
    cited = [e["source_ref"] for e in expected["evidence"]]
    llm = ScriptedChatModel(
        responses=[
            tool_call(
                "leave_overlap", {"project": str(s["project_id"]), "start": start, "end": end}
            ),
            tool_call(
                "AgentAnswer",
                {
                    "status": "ok",
                    "answer": f"Everyone on {s['project_name']} has leave in the window.",
                    "evidence_refs": cited,
                },
            ),
        ]
    )
    with request_scope(request_context()), override_llm(lambda role: llm):
        result = await HRAgent().run(
            f"Is {s['project_name']} short of people because of leave?", subtask_id="t1"
        )

    assert isinstance(result, AgentResult)
    assert result.agent == "hr"
    assert result.subtask_id == "t1"
    assert result.status == "ok", result.error
    assert result.evidence
    assert {e.source_ref for e in result.evidence} <= set(cited)
    assert f"leave:id={expected['data']['leave'][0]['id']}" in {
        e.source_ref for e in result.evidence
    }
    assert all(e.source_type == "db" for e in result.evidence)


@requires_runtime
async def test_run_asks_finance_peer_for_payroll(seeded_db, scenarios, isolated_registry):
    s = next(x for x in scenarios["scenarios"] if x["id"] == "understaffed")
    registry.register(HRAgent())
    peer = registry.register(FakeFinancePeer())
    FakeFinancePeer.questions.clear()
    employee = json.loads(
        await hr_tools_module.get_employee.ainvoke({"employee_id": s["lead_employee_id"]})
    )
    hr_refs = [e["source_ref"] for e in employee["evidence"]]
    llm = PeerCitingModel(
        responses=[
            tool_call("get_employee", {"employee_id": s["lead_employee_id"]}),
            tool_call(
                "ask_agent",
                {
                    "target": "finance",
                    "question": f"What was the payroll cost of employee "
                    f"{s['lead_employee_id']} in 2026-Q3?",
                },
            ),
        ],
        answer="Finance reports payroll cost of INR 540000 for this employee.",
        hr_refs=hr_refs,
    )
    with request_scope(request_context()), override_llm(lambda role: llm):
        result = await HRAgent().run(
            f"What does employee {s['lead_employee_id']} cost us in payroll?", subtask_id="t2"
        )

    assert isinstance(result, AgentResult)
    assert result.status in ("ok", "partial"), result.error
    assert FakeFinancePeer.questions, "HR should delegate the payroll question to Finance"
    assert str(s["lead_employee_id"]) in FakeFinancePeer.questions[0]
    assert result.peer_messages
    sources = {e.source_type for e in result.evidence}
    assert "peer" in sources
    assert f"employees:id={s['lead_employee_id']}" in {e.source_ref for e in result.evidence}
    assert registry.get("finance") is peer
