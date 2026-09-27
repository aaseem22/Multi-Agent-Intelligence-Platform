"""Fake agent cards for CEO tests."""

from app.core.contracts import AgentCard, Skill


def make_card(name: str, description: str, owned: list[str]) -> AgentCard:
    return AgentCard(
        name=name,
        department=f"dept-{name}",
        description=description,
        skills=[Skill(name=f"{name}_lookup", description=f"Look up {name} data")],
        owned_data=owned,
    )
