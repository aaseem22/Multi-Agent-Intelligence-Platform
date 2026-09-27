"""Live end-to-end questions against the seeded org (CLAUDE.md §16 Phase 2 step 4).

Calls the real Gemini API. Skipped unless GOOGLE_API_KEY is set, and excluded from the default
run; opt in with:  uv run pytest -m live -s
"""

from collections import Counter

import pytest
from langgraph.checkpoint.memory import InMemorySaver

import app.agents  # noqa: F401  (registers every agent)
from app.core.config import get_settings
from app.core.events import (
    AgentResultEvent,
    ClarificationEvent,
    FinalEvent,
    PeerMessageEvent,
    PlanEvent,
)
from app.core.orchestrator import Orchestrator

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not get_settings().google_api_key, reason="GOOGLE_API_KEY not set"),
]


def scenario(scenarios: dict, scenario_id: str) -> dict:
    return next(s for s in scenarios["scenarios"] if s["id"] == scenario_id)


async def ask(question: str) -> list:
    orchestrator = Orchestrator(checkpointer=InMemorySaver())
    await orchestrator.start()
    try:
        events = [event async for event in orchestrator.stream(question)]
    finally:
        await orchestrator.aclose()
    for event in events:
        print(f"  {event.type}: {event.model_dump_json(exclude={'timestamp'})[:220]}")
    return events


def of(events: list, cls: type) -> list:
    return [e for e in events if isinstance(e, cls)]


def planned_agents(events: list) -> set[str]:
    return {s.assigned_to for plan in of(events, PlanEvent) for s in plan.subtasks}


def peer_requests(events: list) -> list[PeerMessageEvent]:
    return [e for e in of(events, PeerMessageEvent) if e.message.type == "peer_request"]


def assert_final_with_evidence(events: list) -> FinalEvent:
    finals = of(events, FinalEvent)
    assert finals, "no final answer"
    final = finals[-1]
    assert final.answer.answer.strip()
    assert any(r.evidence for r in final.results), "no evidence attached to any agent result"
    return final


async def test_q1_behind_schedule_people_or_budget(seeded_db):
    events = await ask(
        "Which technology projects are behind schedule, and is the cause people or budget?"
    )
    assert_final_with_evidence(events)
    involved = planned_agents(events) | {e.message.recipient for e in peer_requests(events)}
    assert {"tech", "hr", "finance"} <= involved
    assert peer_requests(events), "expected at least one peer message"


async def test_q2_single_domain_spend_vs_budget(seeded_db, scenarios):
    project = scenario(scenarios, "over_budget")["project_name"]
    events = await ask(f"What is our spend versus budget on {project} this quarter?")
    assert_final_with_evidence(events)
    assert planned_agents(events) == {"finance"}


async def test_q3_most_open_issues_owner_allocation(seeded_db):
    events = await ask(
        "Who is working on the repo with the most open issues, and are they over-allocated?"
    )
    assert_final_with_evidence(events)
    tech_to_hr = [
        e
        for e in peer_requests(events)
        if e.message.sender == "tech" and e.message.recipient == "hr"
    ]
    assert tech_to_hr or {"tech", "hr"} <= planned_agents(events)


async def test_q4_people_cost_growth(seeded_db):
    events = await ask("Which department's people cost grew most last quarter?")
    assert_final_with_evidence(events)
    assert "finance" in planned_agents(events)


async def test_q5_vague_question_asks_for_clarification(seeded_db):
    events = await ask("How are we doing?")
    assert of(events, ClarificationEvent)
    assert not of(events, AgentResultEvent)
    assert Counter(e.type for e in events)["agent_started"] == 0
