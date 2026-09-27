"""Registers the CEO supervisor. Importing this module is the one registration call."""

from app.agents.ceo.supervisor import CEOAgent
from app.core.registry import registry

registry.register_supervisor(CEOAgent())

__all__ = ["CEOAgent"]
