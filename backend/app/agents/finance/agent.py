"""Finance department agent. Importing this module registers it with the agent registry."""

from typing import ClassVar

from langchain_core.tools import BaseTool

from app.agents.finance.card import FINANCE_CARD
from app.agents.finance.prompts import FINANCE_SYSTEM_PROMPT
from app.agents.finance.tools import FINANCE_TOOLS
from app.core.base_agent import DepartmentAgent
from app.core.contracts import AgentCard
from app.core.registry import registry


class FinanceAgent(DepartmentAgent):
    card: ClassVar[AgentCard] = FINANCE_CARD

    def get_tools(self) -> list[BaseTool]:
        return list(FINANCE_TOOLS)

    def system_prompt(self) -> str:
        return FINANCE_SYSTEM_PROMPT


finance_agent = registry.register(FinanceAgent())
