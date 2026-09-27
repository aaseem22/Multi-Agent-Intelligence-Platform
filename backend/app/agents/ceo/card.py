"""The CEO's AgentCard. The CEO owns no domain data and never accepts peer requests."""

from app.core.contracts import AgentCard, Skill

CEO_CARD = AgentCard(
    name="ceo",
    department="executive",
    description=(
        "Supervisor. Interprets stakeholder questions, splits them into subtasks for the "
        "registered department agents, asks clarifying questions when a request is too vague, "
        "and combines the agents' results into one evidence-backed answer."
    ),
    skills=[
        Skill(
            name="plan",
            description="Route a question to the fewest agents whose cards cover it.",
            example_questions=[
                "Which projects are behind schedule, and is the cause people or budget?"
            ],
        ),
        Skill(
            name="clarify",
            description="Ask one clarifying question when a request is too vague to plan.",
            example_questions=["How are we doing?"],
        ),
        Skill(
            name="synthesise",
            description="Combine agent results into one answer where every claim cites evidence.",
        ),
    ],
    owned_data=[],
    accepts_peer_requests=False,
)
