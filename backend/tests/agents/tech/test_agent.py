"""TechAgent runs with a scripted LLM (never Gemini) and recorded GitHub responses."""

import re
from typing import Any, ClassVar

import pytest
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.tools import BaseTool

from app.agents.tech.agent import TechAgent
from app.agents.tech.card import TECH_CARD
from app.core.base_agent import DepartmentAgent
from app.core.contracts import AgentCard, AgentResult, Evidence, Skill
from app.core.llm import override_llm
from app.core.registry import registry
from tests.support.fake_llm import ScriptedChatModel, tool_call
from tests.support.markers import requires_runtime

from .helpers import scenario

pytestmark = pytest.mark.usefixtures("seeded_db", "recorded_github", "isolated_registry")

REF = re.compile(r"((?:projects|github|peer):[^\s\"',)\]]+)")


class CitingScriptedModel(ScriptedChatModel):
    """Plays the scripted tool calls, then answers citing every ref the tools and peers returned."""

    final_status: str = "ok"
    final_answer: str = ""

    def _generate(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> Any:
        if self._cursor < len(self.responses):
            return super()._generate(messages, *args, **kwargs)
        cited: list[str] = []
        for message in messages:
            if isinstance(message, ToolMessage):
                for ref in REF.findall(str(message.content)):
                    if ref not in cited:
                        cited.append(ref)
        self.responses.append(
            tool_call(
                "AgentAnswer",
                {"status": self.final_status, "answer": self.final_answer, "evidence_refs": cited},
            )
        )
        return super()._generate(messages, *args, **kwargs)


class FakeStaffingAgent(DepartmentAgent):
    """Stands in for the staffing peer; answers without an LLM."""

    card: ClassVar[AgentCard] = AgentCard(
        name="hr",
        department="Human Resources",
        description="Owns employees, allocations, leave and open positions.",
        skills=[Skill(name="staffing", description="Who is allocated to a project")],
        owned_data=["employees", "allocations", "leave"],
    )
    questions: ClassVar[list[str]] = []

    def get_tools(self) -> list[BaseTool]:
        return []

    def system_prompt(self) -> str:
        return "fake staffing agent"

    async def run(self, instruction: str, *, subtask_id: str, **kwargs: Any) -> AgentResult:
        self.questions.append(instruction)
        return AgentResult(
            agent="hr",
            subtask_id=subtask_id,
            status="ok",
            answer="Lead employee id=6 is allocated at 90% and has leave overlapping the window.",
            evidence=[Evidence(source_type="db", source_ref="allocations:id=1", summary="lead")],
            peer_messages=[],
        )


def test_tech_agent_is_registered_with_its_card():
    agent = registry.get("tech")
    assert isinstance(agent, TechAgent)
    assert agent.card == TECH_CARD
    assert agent.system_prompt()
    assert "ask_agent" not in {t.name for t in agent.get_tools()}


def test_prompt_forbids_inferring_staffing_from_contributors():
    prompt = TechAgent().system_prompt()
    assert "Never infer who works on a project from GitHub contributors" in prompt
    assert "ask_agent" in prompt


@requires_runtime
async def test_run_returns_agent_result_with_evidence(scenarios):
    stale = scenario(scenarios, "stale_repo")
    llm = CitingScriptedModel(
        responses=[tool_call("stale_repos", {"days": 60})],
        final_answer=f"{stale['repo_full_name']} has had no push in over 60 days.",
    )
    with override_llm(lambda role: llm):
        result = await TechAgent().run("Which repos have had no push in 60 days?", subtask_id="t1")

    assert isinstance(result, AgentResult)
    assert result.agent == "tech"
    assert result.subtask_id == "t1"
    assert result.status == "ok", result.error
    refs = {e.source_ref for e in result.evidence}
    assert f"projects:id={stale['project_id']}" in refs
    assert f"github:repos/{stale['repo_full_name']}" in refs
    assert {e.source_type for e in result.evidence} == {"db", "github"}


@requires_runtime
async def test_run_asks_staffing_peer_for_stalled_project(scenarios):
    stale = scenario(scenarios, "stale_repo")
    registry.register(FakeStaffingAgent())
    FakeStaffingAgent.questions.clear()
    question = (
        f"Who is allocated to project {stale['project_name']} (id={stale['project_id']}) "
        "and does anyone have overlapping leave?"
    )
    llm = CitingScriptedModel(
        responses=[
            tool_call("stale_repos", {"days": 60}),
            tool_call("ask_agent", {"target": "hr", "question": question}),
        ],
        final_answer="Legacy Billing is stalled; HR reports its lead is on overlapping leave.",
    )
    with override_llm(lambda role: llm):
        result = await TechAgent().run(
            "Which repos are stalled and who is working on them?", subtask_id="t2"
        )

    assert result.status in ("ok", "partial"), result.error
    assert (
        FakeStaffingAgent.questions and str(stale["project_id"]) in FakeStaffingAgent.questions[0]
    )
    assert result.peer_messages
    types = {e.source_type for e in result.evidence}
    assert "github" in types
    assert "peer" in types
    called = [
        call["name"]
        for messages in llm.calls
        for m in messages
        if isinstance(m, AIMessage)
        for call in m.tool_calls
    ]
    assert "contributors" not in called
