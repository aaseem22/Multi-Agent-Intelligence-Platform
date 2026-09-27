"""HR department agent. Importing this module registers it with the agent registry."""

from langchain_core.tools import BaseTool

from app.agents.hr.card import HR_CARD
from app.agents.hr.prompts import HR_SYSTEM_PROMPT
from app.agents.hr.tools import HR_TOOLS
from app.core.base_agent import DepartmentAgent
from app.core.registry import registry


class HRAgent(DepartmentAgent):
    card = HR_CARD

    def get_tools(self) -> list[BaseTool]:
        return list(HR_TOOLS)

    def system_prompt(self) -> str:
        return HR_SYSTEM_PROMPT


hr_agent = registry.register(HRAgent())
