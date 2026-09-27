"""Seed a fictional organisation around the developer's own GitHub repositories.

Run with:  uv run python -m app.data.seed.seed [--reset]

Planted ground-truth scenarios are written to scenarios.json for later benchmarks.
"""

import argparse
import asyncio
import json
import logging
import random
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from faker import Faker
from sqlalchemy import func, select

from app.core.config import get_settings
from app.data.db import dispose_engine, init_db, session_scope
from app.data.models import (
    Allocation,
    Budget,
    Department,
    Employee,
    Expense,
    Leave,
    OpenPosition,
    Payroll,
    Project,
)
from app.data.periods import last_periods, month_starts, period_bounds, previous_period, today
from app.integrations.github_client import GitHubClient, Repo, load_fixtures

logger = logging.getLogger("seed")

SCENARIOS_PATH = Path(__file__).with_name("scenarios.json")
DEPARTMENTS = [("Engineering", "ENG"), ("Product", "PRD"), ("Data", "DAT"), ("Operations", "OPS")]
TITLES = {
    "ENG": [
        "Engineering Manager",
        "Senior Engineer",
        "Software Engineer",
        "QA Engineer",
        "DevOps Engineer",
    ],
    "PRD": ["Product Director", "Product Manager", "UX Designer", "Business Analyst"],
    "DAT": ["Head of Data", "Data Engineer", "Data Scientist", "Analytics Engineer"],
    "OPS": ["Operations Lead", "SRE", "IT Administrator", "Programme Manager"],
}
MONTHLY_COST = {
    "Manager": 420_000,
    "Director": 480_000,
    "Head": 460_000,
    "Lead": 380_000,
    "Senior": 320_000,
}
EXPENSE_CATEGORIES = {
    "cloud": ["AWS", "Google Cloud", "Azure"],
    "software_licences": ["Atlassian", "JetBrains", "Datadog", "Figma"],
    "contractors": ["Infosys Contracting", "Freelance Partners LLP", "Nimbus Consulting"],
    "hardware": ["Dell India", "Lenovo India"],
    "travel": ["MakeMyTrip Corporate", "IndiGo"],
    "training": ["Coursera for Business", "Pluralsight"],
}


@dataclass
class SeedState:
    rng: random.Random
    fake: Faker
    today: date
    currency: str
    departments: dict[str, int] = field(default_factory=dict)
    employees: list[Employee] = field(default_factory=list)
    projects: list[Project] = field(default_factory=list)
    load: dict[int, int] = field(default_factory=dict)  # employee_id -> allocated pct
    scenarios: list[dict[str, Any]] = field(default_factory=list)


# --- repositories from GitHub (or fixtures) ---


async def fetch_repos(max_repos: int) -> tuple[list[Repo], str, str | None]:
    """Return (repos, source, owner_login)."""
    settings = get_settings()
    if settings.github_token and settings.github_owner:
        client = GitHubClient(use_cache=False)
        try:
            result = await client.list_owner_repos(settings.github_owner)
            repos = [r for r in result.items if not r.private][:max_repos]
            if repos:
                return repos, "github", settings.github_owner
            logger.warning("No public repos found for %s; using fixtures", settings.github_owner)
        except Exception as exc:
            logger.warning("GitHub fetch failed (%s); using fixtures", exc)
        finally:
            await client.aclose()
    fixtures = load_fixtures()
    client = GitHubClient(token="", use_cache=False)
    try:
        result = await client.list_owner_repos(fixtures["owner"])
    finally:
        await client.aclose()
    login = fixtures["repos"][0]["contributors"][0]["login"]
    return result.items[:max_repos], "fixtures", login


def _title_case(repo_name: str) -> str:
    return " ".join(part.capitalize() for part in repo_name.replace("_", "-").split("-") if part)


def _days_since_push(repo: Repo, now: date) -> int:
    return (now - repo.pushed_at.date()).days if repo.pushed_at else 10_000


def _monthly_cost(title: str, rng: random.Random) -> float:
    base = next((cost for key, cost in MONTHLY_COST.items() if key in title), 220_000)
    return float(round(base * rng.uniform(0.85, 1.15), -3))


# --- builders ---


async def build(state: SeedState, repos: list[Repo], owner_login: str | None) -> None:
    async with session_scope() as session:
        for name, code in DEPARTMENTS:
            dept = Department(name=name, code=code)
            session.add(dept)
            await session.flush()
            state.departments[code] = dept.id

        await _add_employees(session, state)
        roles = _assign_scenarios(state, repos)
        await _add_projects(session, state, repos, roles)
        await _add_allocations(session, state, roles, owner_login)
        await _add_leave(session, state, roles)
        await _add_open_positions(session, state, roles)
        await _add_payroll(session, state)
        await _add_budgets_and_expenses(session, state, roles)


async def _add_employees(session: Any, state: SeedState) -> None:
    rng, fake = state.rng, state.fake
    prev_start, _ = period_bounds(previous_period(last_periods(1, state.today)[0]))
    for code, dept_id in state.departments.items():
        titles = TITLES[code]
        for i in range(10):
            title = titles[0] if i == 0 else titles[1 + (i - 1) % (len(titles) - 1)]
            hire = state.today - timedelta(days=rng.randint(420, 2400))
            # Planted: Data hires three people at the start of the previous quarter.
            if code == "DAT" and i >= 7:
                hire = prev_start + timedelta(days=rng.randint(0, 10))
            first, last = fake.first_name(), fake.last_name()
            employee = Employee(
                full_name=f"{first} {last}",
                email=f"{first}.{last}.{len(state.employees) + 1}@example-org.test".lower(),
                title=title,
                department_id=dept_id,
                manager_id=None,
                github_username=None,
                hire_date=hire,
                termination_date=None,
            )
            session.add(employee)
            state.employees.append(employee)
    await session.flush()
    managers = {
        e.department_id: e.id for e in state.employees if e.title in {v[0] for v in TITLES.values()}
    }
    for employee in state.employees:
        if employee.id != managers[employee.department_id]:
            employee.manager_id = managers[employee.department_id]
        state.load[employee.id] = 0


def _assign_scenarios(state: SeedState, repos: list[Repo]) -> dict[str, int]:
    """Choose which repo index plays which planted role."""
    if len(repos) < 5:
        raise SystemExit(f"Need at least 5 repositories to plant scenarios, found {len(repos)}")
    now = state.today
    indices = list(range(len(repos)))
    stale = max(indices, key=lambda i: _days_since_push(repos[i], now))
    rest = [i for i in indices if i != stale]
    most_issues = max(rest, key=lambda i: repos[i].open_issues_count)
    rest = [i for i in rest if i != most_issues]
    active = sorted(rest, key=lambda i: _days_since_push(repos[i], now))
    roles = {"stale_repo": stale, "most_open_issues": most_issues}
    for role, idx in zip(
        ("healthy", "over_budget", "understaffed", "both_problems"), active, strict=False
    ):
        roles[role] = idx
    return roles


async def _add_projects(
    session: Any, state: SeedState, repos: list[Repo], roles: dict[str, int]
) -> None:
    rng, now = state.rng, state.today
    dept_for_role = {
        "stale_repo": "ENG",
        "understaffed": "ENG",
        "both_problems": "ENG",
        "most_open_issues": "ENG",
        "over_budget": "PRD",
        "healthy": "DAT",
    }
    role_of = {idx: role for role, idx in roles.items()}
    rotation = ["PRD", "DAT", "OPS", "ENG"]
    for i, repo in enumerate(repos):
        role = role_of.get(i)
        dept_code = dept_for_role.get(role or "", rotation[i % len(rotation)])
        start = now - timedelta(days=rng.randint(150, 330))
        planned_end = now + timedelta(days=rng.randint(45, 160))
        expected_end: date | None = planned_end
        status, priority = "active", rng.choice(["high", "medium", "low"])
        if role in ("understaffed", "both_problems"):
            expected_end = planned_end + timedelta(days=rng.randint(35, 60))
            status, priority = "at_risk", "high"
        elif role == "stale_repo":
            planned_end = now - timedelta(days=20)
            expected_end = None
            status, priority = "active", "medium"
        elif role in ("healthy", "over_budget", "most_open_issues"):
            priority = "high"
        elif i % 5 == 4:
            planned_end = now - timedelta(days=rng.randint(10, 60))
            expected_end, status = planned_end, "completed"
        project = Project(
            name=_title_case(repo.name),
            repo_full_name=repo.full_name,
            department_id=state.departments[dept_code],
            lead_employee_id=None,
            status=status,
            priority=priority,
            planned_start=start,
            planned_end=planned_end,
            expected_end=expected_end,
        )
        session.add(project)
        state.projects.append(project)
    await session.flush()


def _staff(
    state: SeedState, dept_id: int, exclude: set[int], need: int, pct: int
) -> list[Employee]:
    pool = [e for e in state.employees if e.id not in exclude and state.load[e.id] + pct <= 100]
    same = [e for e in pool if e.department_id == dept_id]
    other = [e for e in pool if e.department_id != dept_id]
    state.rng.shuffle(same)
    state.rng.shuffle(other)
    return (same + other)[:need]


async def _add_allocations(
    session: Any, state: SeedState, roles: dict[str, int], owner_login: str | None
) -> None:
    rng = state.rng
    role_of = {state.projects[idx].id: role for role, idx in roles.items()}

    def allocate(employee: Employee, project: Project, role: str, pct: int) -> None:
        end = project.planned_end if project.status == "completed" else None
        session.add(
            Allocation(
                employee_id=employee.id,
                project_id=project.id,
                role=role,
                allocation_pct=pct,
                start_date=project.planned_start,
                end_date=end,
            )
        )
        state.load[employee.id] += pct

    ordered = sorted(state.projects, key=lambda p: 0 if p.id in role_of else 1)
    leads: set[int] = set()
    for project in ordered:
        role = role_of.get(project.id)
        if project.status == "completed":
            continue
        lead = _staff(state, project.department_id, leads, 1, 50)[0]
        leads.add(lead.id)
        project.lead_employee_id = lead.id
        allocate(lead, project, "Project Lead", 50)
        team_size = 1 if role in ("understaffed", "both_problems") else rng.randint(3, 4)
        for member in _staff(state, project.department_id, {lead.id}, team_size, 40):
            allocate(
                member,
                project,
                "Engineer" if project.department_id == state.departments["ENG"] else "Contributor",
                40,
            )

    # Planted over-allocation: leads of these projects carry extra side projects.
    for role_name, extra in (("understaffed", 90), ("both_problems", 80), ("most_open_issues", 80)):
        project = state.projects[roles[role_name]]
        lead = next(e for e in state.employees if e.id == project.lead_employee_id)
        side = next(p for p in state.projects if p.id not in role_of and p.status != "completed")
        allocate(lead, side, "Advisor", extra)

    if owner_login:
        owner_lead = next(
            e
            for e in state.employees
            if e.id == state.projects[roles["most_open_issues"]].lead_employee_id
        )
        owner_lead.github_username = owner_login
    await session.flush()

    for role_name, idx in roles.items():
        project = state.projects[idx]
        state.scenarios.append(
            {
                "id": role_name,
                "project_id": project.id,
                "project_name": project.name,
                "repo_full_name": project.repo_full_name,
                "department_id": project.department_id,
                "lead_employee_id": project.lead_employee_id,
                "lead_total_allocation_pct": state.load[project.lead_employee_id]
                if project.lead_employee_id
                else None,
            }
        )


async def _add_leave(session: Any, state: SeedState, roles: dict[str, int]) -> None:
    rng, now = state.rng, state.today
    for employee in state.employees:
        for _ in range(rng.randint(1, 3)):
            start = now - timedelta(days=rng.randint(20, 360))
            session.add(
                Leave(
                    employee_id=employee.id,
                    leave_type=rng.choice(["annual", "sick", "personal"]),
                    start_date=start,
                    end_date=start + timedelta(days=rng.randint(1, 6)),
                    status="approved",
                )
            )
    # Planted: overlapping leave for the understaffed teams, starting within the next weeks.
    for role_name in ("understaffed", "both_problems"):
        project = state.projects[roles[role_name]]
        team = await session.scalars(
            select(Allocation.employee_id).where(Allocation.project_id == project.id)
        )
        for offset, employee_id in enumerate(sorted(set(team))):
            start = now + timedelta(days=5 + offset * 3)
            session.add(
                Leave(
                    employee_id=employee_id,
                    leave_type="annual",
                    start_date=start,
                    end_date=start + timedelta(days=14),
                    status="approved",
                )
            )
        _scenario(state, role_name)["overlapping_leave_window"] = [
            str(now + timedelta(days=5)),
            str(now + timedelta(days=22)),
        ]
    await session.flush()


async def _add_open_positions(session: Any, state: SeedState, roles: dict[str, int]) -> None:
    rng, now = state.rng, state.today
    for role_name in ("understaffed", "both_problems"):
        project = state.projects[roles[role_name]]
        session.add(
            OpenPosition(
                department_id=project.department_id,
                project_id=project.id,
                title="Senior Engineer",
                opened_on=now - timedelta(days=rng.randint(60, 90)),
                status="open",
            )
        )
    for code, title in (
        ("DAT", "Data Engineer"),
        ("PRD", "Product Manager"),
        ("OPS", "SRE"),
        ("ENG", "QA Engineer"),
    ):
        session.add(
            OpenPosition(
                department_id=state.departments[code],
                project_id=None,
                title=title,
                opened_on=now - timedelta(days=rng.randint(10, 120)),
                status="open",
            )
        )
    await session.flush()


async def _add_payroll(session: Any, state: SeedState) -> None:
    rng, now = state.rng, state.today
    periods = last_periods(4, now)
    start, _ = period_bounds(periods[0])
    prev = previous_period(periods[-1])
    prev_start, _ = period_bounds(prev)
    for employee in state.employees:
        cost = _monthly_cost(employee.title, rng)
        for month in month_starts(start, now):
            if month < date(employee.hire_date.year, employee.hire_date.month, 1):
                continue
            monthly = cost
            # Planted: Data department raises effective in the previous quarter.
            if employee.department_id == state.departments["DAT"] and month >= prev_start:
                monthly = round(cost * 1.12, -3)
            session.add(
                Payroll(
                    employee_id=employee.id,
                    department_id=employee.department_id,
                    month=month,
                    gross_cost=monthly,
                    currency=state.currency,
                )
            )
    state.scenarios.append(
        {
            "id": "people_cost_growth",
            "department_id": state.departments["DAT"],
            "department_name": "Data",
            "period": prev,
            "compared_to": previous_period(prev),
            "cause": "three hires at the start of the quarter plus 12% raises",
        }
    )
    await session.flush()


async def _add_budgets_and_expenses(session: Any, state: SeedState, roles: dict[str, int]) -> None:
    rng, now = state.rng, state.today
    periods = last_periods(4, now)
    current = periods[-1]
    ratio_current = {
        "over_budget": 1.35,
        "both_problems": 1.25,
        "understaffed": 0.70,
        "healthy": 0.85,
    }
    ratio_previous = {"over_budget": 1.15, "both_problems": 1.10}
    role_of = {state.projects[idx].id: role for role, idx in roles.items()}
    for project in state.projects:
        role = role_of.get(project.id)
        base = float(round(rng.uniform(1_500_000, 6_000_000), -4))
        for period in periods:
            p_start, p_end = period_bounds(period)
            if p_end < project.planned_start - timedelta(days=90):
                continue
            session.add(
                Budget(project_id=project.id, period=period, amount=base, currency=state.currency)
            )
            last_day = min(p_end, now)
            elapsed = (last_day - p_start).days + 1
            quarter_days = (p_end - p_start).days + 1
            if period == current:
                ratio = ratio_current.get(
                    role or "", rng.uniform(0.7, 0.95) * elapsed / quarter_days
                )
            elif period == previous_period(current):
                ratio = ratio_previous.get(role or "", rng.uniform(0.8, 0.98))
            else:
                ratio = rng.uniform(0.8, 0.98)
            _add_expenses(session, state, project, p_start, last_day, base * ratio)
        if role in ratio_current:
            scenario = _scenario(state, role)
            scenario["period"] = current
            scenario["budget"] = base
            scenario["spend_ratio"] = ratio_current[role]
    await session.flush()


def _add_expenses(
    session: Any, state: SeedState, project: Project, start: date, end: date, total: float
) -> None:
    rng = state.rng
    count = rng.randint(8, 14)
    weights = [rng.uniform(0.5, 1.5) for _ in range(count)]
    scale = total / sum(weights)
    span = max((end - start).days, 0)
    for weight in weights:
        category = rng.choice(list(EXPENSE_CATEGORIES))
        session.add(
            Expense(
                project_id=project.id,
                category=category,
                vendor=rng.choice(EXPENSE_CATEGORIES[category]),
                amount=round(weight * scale, 2),
                currency=state.currency,
                spent_on=start + timedelta(days=rng.randint(0, span)),
                description=f"{category.replace('_', ' ').title()} for {project.name}",
            )
        )


def _scenario(state: SeedState, scenario_id: str) -> dict[str, Any]:
    return next(s for s in state.scenarios if s["id"] == scenario_id)


def describe_scenarios(
    state: SeedState, repos: list[Repo], roles: dict[str, int], source: str
) -> dict[str, Any]:
    expectations = {
        "over_budget": "Spend exceeds budget this quarter (~135%) while staffing is adequate.",
        "understaffed": "Within budget (~70%) but one-person team, lead over-allocated, overlapping leave, expected_end later than planned_end.",
        "both_problems": "Over budget (~125%) and understaffed with an over-allocated lead and overlapping leave; delayed.",
        "healthy": "Within budget (~85%), adequately staffed, on schedule, recently active repo.",
        "stale_repo": "Repository has had no push for a long time; project is past its planned_end.",
        "most_open_issues": "Repository with the most open issues; its lead is over-allocated and mapped to the account owner's GitHub username.",
        "people_cost_growth": "Department whose people cost grew most in the previous quarter.",
    }
    for scenario in state.scenarios:
        scenario["expected"] = expectations[scenario["id"]]
        if scenario["id"] in roles:
            repo = repos[roles[scenario["id"]]]
            scenario["repo_days_since_push"] = _days_since_push(repo, state.today)
            scenario["repo_open_issues_count"] = repo.open_issues_count
    stale = _scenario(state, "stale_repo")
    stale["verified"] = stale["repo_days_since_push"] > 60
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "as_of": str(state.today),
        "repo_source": source,
        "currency": state.currency,
        "scenarios": state.scenarios,
    }


async def seed(reset: bool = False) -> dict[str, Any] | None:
    settings = get_settings()
    await init_db(reset=reset)
    async with session_scope() as session:
        existing = await session.scalar(select(func.count()).select_from(Department))
    if existing and not reset:
        logger.info("Database already seeded; run with --reset to rebuild")
        return None

    repos, source, owner_login = await fetch_repos(settings.seed_max_repos)
    state = SeedState(
        rng=random.Random(settings.seed),
        fake=Faker("en_IN"),
        today=today(),
        currency=settings.currency,
    )
    state.fake.seed_instance(settings.seed)
    await build(state, repos, owner_login)
    roles = {
        s["id"]: next(i for i, p in enumerate(state.projects) if p.id == s["project_id"])
        for s in state.scenarios
        if "project_id" in s
    }
    scenarios = describe_scenarios(state, repos, roles, source)
    SCENARIOS_PATH.write_text(json.dumps(scenarios, indent=2, default=str))
    logger.info(
        "Seeded %d projects, %d employees from %s; scenarios -> %s",
        len(state.projects),
        len(state.employees),
        source,
        SCENARIOS_PATH,
    )
    return scenarios


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the fictional organisation")
    parser.add_argument("--reset", action="store_true", help="drop and recreate all tables first")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    async def run() -> None:
        try:
            await seed(reset=args.reset)
        finally:
            await dispose_engine()

    asyncio.run(run())


if __name__ == "__main__":
    main()
