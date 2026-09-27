"""AgentCard for the Tech department. The CEO planner routes subtasks on this card."""

from app.core.contracts import AgentCard, Skill

TECH_CARD = AgentCard(
    name="tech",
    department="Technology",
    description=(
        "Owns project delivery data (status, priority, planned start/end, expected end, "
        "schedule slippage) and read-only GitHub repository activity (commits, last push, "
        "open issues, open pull requests, contributors) for every project repo. Answers which "
        "projects are behind schedule or stalled and how active their repos are. Does not own "
        "staffing, allocations, leave, budgets, spend or payroll."
    ),
    skills=[
        Skill(
            name="project_delivery",
            description=(
                "Lists projects with status and priority, and compares planned end with "
                "expected end to report schedule status (on_track, behind, overdue, "
                "completed, not_started) and days late."
            ),
            example_questions=[
                "Which technology projects are behind schedule?",
                "What is the delivery status of the Data Pipeline project?",
                "Which projects are at risk or overdue, and by how many days?",
            ],
        ),
        Skill(
            name="repository_activity",
            description=(
                "Reads GitHub for a project's repo: commits in a recent window, last commit "
                "and last push dates, and which repos have had no push for N days."
            ),
            example_questions=[
                "Which repositories have had no push in the last 60 days?",
                "How many commits did the payments-gateway repo get in the last 30 days?",
                "Is the Legacy Billing repo still active?",
            ],
        ),
        Skill(
            name="issues_and_pull_requests",
            description=(
                "Counts and lists open GitHub issues and open pull requests per repo, and "
                "ranks project repos by open issues."
            ),
            example_questions=[
                "Which repo has the most open issues?",
                "What pull requests are open on the customer-portal repo?",
            ],
        ),
        Skill(
            name="repo_contributors",
            description=(
                "Lists GitHub contributor accounts and commit counts for a repo. This is code "
                "activity only, not who is staffed on the project (ask HR for staffing)."
            ),
            example_questions=["Who has committed to the data-pipeline repository?"],
        ),
    ],
    owned_data=["projects", "github"],
    accepts_peer_requests=True,
)
