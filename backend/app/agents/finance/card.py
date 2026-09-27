"""Finance AgentCard. The CEO planner routes subtasks using this description and these skills."""

from app.core.contracts import AgentCard, Skill

FINANCE_CARD = AgentCard(
    name="finance",
    department="Finance",
    description=(
        "Owns money: project budgets per quarter, project expenses (spend by category and vendor) "
        "and payroll (monthly people cost per employee and per cost-centre department). Answers "
        "budget vs actual, overspend / overrun, spend breakdown and people-cost questions. Does "
        "not know who is allocated to which project (HR) or delivery status (Tech)."
    ),
    skills=[
        Skill(
            name="budget_vs_actual",
            description="Compare quarterly project budgets with actual spend; find overruns.",
            example_questions=[
                "What is our spend versus budget on Customer Portal this quarter?",
                "Which projects are over budget in 2026-Q3?",
                "Is the Engineering department within budget this quarter?",
            ],
        ),
        Skill(
            name="project_spend",
            description="Total project spend over a date range and its split by expense category.",
            example_questions=[
                "How much has Payments Gateway spent since July?",
                "What are our biggest expense categories this quarter?",
            ],
        ),
        Skill(
            name="people_cost",
            description=(
                "Payroll cost of given employees, or of a project's team (asks HR who is "
                "allocated), and people cost per department with quarter-on-quarter growth."
            ),
            example_questions=[
                "What does the team on Ml Forecasting cost us per quarter?",
                "Which department's people cost grew most last quarter?",
            ],
        ),
    ],
    owned_data=["budgets", "expenses", "payroll"],
)
