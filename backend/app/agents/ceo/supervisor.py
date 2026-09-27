"""CEOAgent: the object that satisfies `app.core.registry.Supervisor`. The orchestrator's plan
and synthesise graph nodes call these two methods."""

from app.agents.ceo import planner, synthesiser
from app.agents.ceo.card import CEO_CARD
from app.core.contracts import AgentCard, AgentResult, FinalAnswer, Plan, Subtask


class CEOAgent:
    def __init__(self, card: AgentCard = CEO_CARD) -> None:
        self.card = card

    async def plan(
        self, question: str, history: list[dict[str, str]], cards: list[AgentCard]
    ) -> Plan:
        return await planner.plan(question, history, cards, exclude=self.card.name)

    async def synthesise(
        self, question: str, subtasks: list[Subtask], results: list[AgentResult]
    ) -> FinalAnswer:
        return await synthesiser.synthesise(question, subtasks, results)
