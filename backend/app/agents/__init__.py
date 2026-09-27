"""Importing this package registers every agent. A new department is a new folder plus one
import line here; app/core never changes."""

from app.agents.ceo import agent as ceo_agent  # noqa: F401
from app.agents.finance import agent as finance_agent  # noqa: F401
from app.agents.hr import agent as hr_agent  # noqa: F401
from app.agents.tech import agent as tech_agent  # noqa: F401
