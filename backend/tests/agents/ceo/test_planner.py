import re

import pytest

from app.agents.ceo.card import CEO_CARD
from app.agents.ceo.planner import EMPTY_PLAN_CLARIFICATION, NO_AGENTS_CLARIFICATION
from app.agents.ceo.prompts import (
    PLANNER_SYSTEM_PROMPT,
    SYNTHESIS_SYSTEM_PROMPT,
    SYNTHESIS_USER_PROMPT,
    planner_system_prompt,
)
from app.agents.ceo.supervisor import CEOAgent
from app.core.contracts import Plan, Subtask
from tests.agents.ceo.fakes import make_card


def st(sid: str, to: str, deps: list[str] | None = None) -> Subtask:
    return Subtask(id=sid, assigned_to=to, instruction=f"do {sid}", depends_on=deps or [])


async def test_single_domain_question_gives_one_subtask(scripted_llm, fake_cards):
    scripted_llm(Plan(subtasks=[st("t1", "ledger")], rationale="budget only"))
    plan = await CEOAgent().plan("Spend vs budget on Apollo this quarter?", [], fake_cards)
    assert plan.clarification is None
    assert [s.assigned_to for s in plan.subtasks] == ["ledger"]


async def test_cross_domain_question_gives_several_subtasks(scripted_llm, fake_cards):
    scripted_llm(
        Plan(subtasks=[st("t1", "delivery"), st("t2", "people"), st("t3", "ledger", ["t1"])])
    )
    plan = await CEOAgent().plan(
        "Which projects are behind schedule, and is the cause people or budget?", [], fake_cards
    )
    assert plan.clarification is None
    assert {s.assigned_to for s in plan.subtasks} == {"delivery", "people", "ledger"}
    assert plan.subtasks[2].depends_on == ["t1"]


async def test_vague_question_gives_clarification(scripted_llm, fake_cards):
    scripted_llm(Plan(clarification="Which area and period do you mean?"))
    plan = await CEOAgent().plan("How are we doing?", [], fake_cards)
    assert plan.clarification == "Which area and period do you mean?"
    assert plan.subtasks == []


async def test_clarification_discards_any_subtasks(scripted_llm, fake_cards):
    scripted_llm(Plan(subtasks=[st("t1", "ledger")], clarification="Which project?"))
    plan = await CEOAgent().plan("Is it over?", [], fake_cards)
    assert plan.subtasks == [] and plan.clarification == "Which project?"


async def test_invalid_assignee_is_repaired_or_dropped(scripted_llm, fake_cards):
    scripted_llm(
        Plan(
            subtasks=[
                st("t1", "LEDGER"),  # case repaired
                st("t2", "dept-people"),  # department repaired to agent name
                st("t3", "marketing", []),  # unknown: dropped
                st("t4", "ceo"),  # supervisor is never an assignee: dropped
                st("t5", "delivery", ["t3", "t1"]),  # dependency on dropped id removed
            ]
        )
    )
    plan = await CEOAgent().plan("q", [], fake_cards + [CEO_CARD])
    assert [(s.id, s.assigned_to) for s in plan.subtasks] == [
        ("t1", "ledger"),
        ("t2", "people"),
        ("t5", "delivery"),
    ]
    assert plan.subtasks[2].depends_on == ["t1"]


async def test_all_subtasks_invalid_becomes_clarification(scripted_llm, fake_cards):
    scripted_llm(Plan(subtasks=[st("t1", "marketing")]))
    plan = await CEOAgent().plan("q", [], fake_cards)
    assert plan.subtasks == [] and plan.clarification == EMPTY_PLAN_CLARIFICATION


async def test_duplicate_ids_self_and_cyclic_dependencies_are_repaired(scripted_llm, fake_cards):
    scripted_llm(
        Plan(
            subtasks=[
                st("a", "ledger", ["b", "a", "ghost"]),
                st("b", "people", ["a"]),  # would close a cycle a -> b -> a
                st("a", "delivery"),  # duplicate id
                st("", "people"),  # blank id
            ]
        )
    )
    plan = await CEOAgent().plan("q", [], fake_cards)
    ids = [s.id for s in plan.subtasks]
    assert len(set(ids)) == 4 and ids[:2] == ["a", "b"]
    assert plan.subtasks[0].depends_on == ["b"]
    assert plan.subtasks[1].depends_on == []


async def test_no_registered_agents_asks_without_calling_llm(scripted_llm):
    scripted_llm()  # no responses: any LLM call would fail
    plan = await CEOAgent().plan("q", [], [CEO_CARD])
    assert plan.clarification == NO_AGENTS_CLARIFICATION


async def test_planner_llm_failure_propagates(scripted_llm, fake_cards):
    scripted_llm(ValueError("bad schema"))
    with pytest.raises(ValueError):
        await CEOAgent().plan("q", [], fake_cards)


def test_planner_prompt_is_built_from_cards(fake_cards):
    legal = make_card("legal", "Contracts and compliance obligations.", ["contracts"])
    prompt = planner_system_prompt(fake_cards + [legal])
    for card in fake_cards + [legal]:
        assert card.description in prompt and f'"{card.name}"' in prompt
    assert "contracts" in prompt


@pytest.mark.parametrize(
    "template", [PLANNER_SYSTEM_PROMPT, SYNTHESIS_SYSTEM_PROMPT, SYNTHESIS_USER_PROMPT]
)
def test_prompts_never_name_departments(template):
    assert not re.search(r"\b(finance|hr|tech|human resources)\b", template, re.IGNORECASE)


def test_ceo_card_refuses_peer_requests():
    assert CEO_CARD.name == "ceo" and CEO_CARD.accepts_peer_requests is False
    assert CEO_CARD.owned_data == []


def test_agent_module_registers_supervisor(isolated_registry):
    import importlib

    import app.agents.ceo.agent as agent_module
    from app.core.registry import registry

    importlib.reload(agent_module)
    assert registry.supervisor is not None
    assert registry.is_supervisor("ceo")
    assert registry.supervisor.card.accepts_peer_requests is False
