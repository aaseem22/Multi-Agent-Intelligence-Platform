"""Fake agent cards and a scripted CEO LLM. No real department agents, no Gemini calls."""

from collections.abc import Callable, Iterator
from typing import Any

import pytest

from app.core.contracts import AgentCard
from app.core.llm import override_llm
from tests.agents.ceo.fakes import make_card
from tests.support.fake_llm import ScriptedChatModel


@pytest.fixture
def fake_cards() -> list[AgentCard]:
    return [
        make_card("ledger", "Budgets, spend and people cost per project.", ["budgets"]),
        make_card("people", "Staffing, allocations and leave.", ["employees", "leave"]),
        make_card("delivery", "Project delivery status and repo activity.", ["projects"]),
    ]


@pytest.fixture
def scripted_llm() -> Iterator[Callable[..., ScriptedChatModel]]:
    """Call with the structured responses the CEO LLM should return, in order."""
    roles: list[str] = []
    holder: dict[str, ScriptedChatModel] = {}

    def factory(role: Any) -> ScriptedChatModel:
        roles.append(role)
        return holder["llm"]

    def script(*structured: Any) -> ScriptedChatModel:
        holder["llm"] = ScriptedChatModel(structured=list(structured))
        return holder["llm"]

    with override_llm(factory):
        yield script
    assert set(roles) <= {"ceo"}, f"CEO must only use the ceo model, used {roles}"
