"""Agent registry. Department agents register themselves; the orchestrator reads it at runtime.
Nothing here names a specific department."""

from typing import TYPE_CHECKING, Protocol

from app.core.contracts import AgentCard, AgentResult, FinalAnswer, Plan, Subtask

if TYPE_CHECKING:
    from app.core.base_agent import DepartmentAgent


class Supervisor(Protocol):
    """The CEO. Implemented in app/agents/ceo; the orchestrator calls these two methods."""

    card: AgentCard

    async def plan(
        self, question: str, history: list[dict[str, str]], cards: list[AgentCard]
    ) -> Plan: ...

    async def synthesise(
        self, question: str, subtasks: list[Subtask], results: list[AgentResult]
    ) -> FinalAnswer: ...


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, DepartmentAgent] = {}
        self._supervisor: Supervisor | None = None

    def register(self, agent: "DepartmentAgent") -> "DepartmentAgent":
        self._agents[agent.name] = agent
        return agent

    def register_supervisor(self, supervisor: Supervisor) -> Supervisor:
        self._supervisor = supervisor
        return supervisor

    def unregister(self, name: str) -> None:
        self._agents.pop(name, None)
        if self._supervisor is not None and self._supervisor.card.name == name:
            self._supervisor = None

    def get(self, name: str) -> "DepartmentAgent | None":
        return self._agents.get(name)

    @property
    def supervisor(self) -> Supervisor | None:
        return self._supervisor

    def is_supervisor(self, name: str) -> bool:
        return self._supervisor is not None and self._supervisor.card.name == name

    def names(self) -> list[str]:
        return sorted(self._agents)

    def department_cards(self) -> list[AgentCard]:
        return [self._agents[name].card for name in self.names()]

    def peer_cards(self, exclude: str) -> list[AgentCard]:
        """Cards of agents that `exclude` may ask via ask_agent."""
        return [c for c in self.department_cards() if c.name != exclude and c.accepts_peer_requests]

    def list_cards(self) -> list[AgentCard]:
        cards = [self._supervisor.card] if self._supervisor else []
        return cards + self.department_cards()

    def snapshot(self) -> tuple[dict[str, "DepartmentAgent"], Supervisor | None]:
        return dict(self._agents), self._supervisor

    def restore(self, snapshot: tuple[dict[str, "DepartmentAgent"], Supervisor | None]) -> None:
        self._agents, self._supervisor = dict(snapshot[0]), snapshot[1]

    def clear(self) -> None:
        self._agents.clear()
        self._supervisor = None


registry = AgentRegistry()
