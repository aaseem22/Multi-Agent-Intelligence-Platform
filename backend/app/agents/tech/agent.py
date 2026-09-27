"""Tech department agent. Importing this module registers it with the core registry."""

from typing import ClassVar

from langchain_core.tools import BaseTool

from app.agents.tech.card import TECH_CARD
from app.agents.tech.prompts import TECH_SYSTEM_PROMPT
from app.agents.tech.tools import TECH_TOOLS
from app.core.base_agent import DepartmentAgent
from app.core.contracts import AgentCard
from app.core.registry import registry


class TechAgent(DepartmentAgent):
    card: ClassVar[AgentCard] = TECH_CARD

    def get_tools(self) -> list[BaseTool]:
        return list(TECH_TOOLS)

    def system_prompt(self) -> str:
        return TECH_SYSTEM_PROMPT


tech_agent = registry.register(TechAgent())
