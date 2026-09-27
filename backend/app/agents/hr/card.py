"""HR AgentCard. The CEO planner routes subtasks on the description, skills and examples."""

from app.core.contracts import AgentCard, Skill

HR_CARD = AgentCard(
    name="hr",
    department="Human Resources",
    description=(
        "Owns people data: employees (names, titles, departments, GitHub usernames), "
        "project allocations and staffing, over-allocation, leave and absences, open positions "
        "(hiring) and headcount by department. Does not own salaries or payroll (Finance), "
        "budgets or spend (Finance), or project delivery and repository activity (Tech)."
    ),
    skills=[
        Skill(
            name="employee_lookup",
            description="Find an employee by id, GitHub username or name: title, department, "
            "manager, hire and termination dates.",
            example_questions=[
                "Who is the employee with GitHub username 'octocat'?",
                "What is Priya Sharma's title and department?",
            ],
        ),
        Skill(
            name="project_staffing",
            description="Who is allocated to a project, in which role and at what percentage.",
            example_questions=[
                "Who is working on the payments-service project?",
                "How many people are staffed on project 4, and who is the lead?",
            ],
        ),
        Skill(
            name="allocations_and_overload",
            description="An employee's current allocations across projects and which employees "
            "are allocated above a threshold (default 100%).",
            example_questions=[
                "Which employees are over-allocated?",
                "Is the lead of the data-pipeline project over-allocated?",
                "What projects is employee 12 allocated to?",
            ],
        ),
        Skill(
            name="leave_overlap",
            description="Leave taken by people allocated to a project in a date window, flagging "
            "who is away and how many are away at once.",
            example_questions=[
                "Does anyone on the mobile-app team have leave in the next month?",
                "Is project 3 short of people because of overlapping leave?",
            ],
        ),
        Skill(
            name="hiring_and_headcount",
            description="Open positions (optionally per department) with days open, and active "
            "headcount per department on a date.",
            example_questions=[
                "What positions are open in Engineering?",
                "What is the headcount by department?",
                "Which open roles have been unfilled the longest?",
            ],
        ),
    ],
    owned_data=["employees", "allocations", "leave", "open_positions"],
    accepts_peer_requests=True,
)
