"""Templated ground truth. Task text may reference

- `{scenario.<scenario_id>.<field>}` or `{scenario.<top_level_field>}` from the run's scenarios.json;
- `{db.<fact_name>}` from deterministic queries computed once at run start (`compute_db_facts`).

Facts are recomputed for every run against that run's freshly seeded database, so they stay correct
as the calendar (and therefore the current quarter) moves. Money is rendered as "₹4,374,000" and
percentages as "35.0%"; the fact graders normalise both."""

import re
from collections.abc import Awaitable, Callable
from typing import Any

from app.evals.contracts import EvalTask, RequiredFact

TEMPLATE = re.compile(r"\{(scenario|db)\.([A-Za-z0-9_.]+)\}")


class TemplateError(KeyError):
    pass


class FactContext:
    def __init__(self, scenarios: dict[str, Any], db: dict[str, str]) -> None:
        self.scenarios = scenarios
        self.db = db
        self._by_id = {s["id"]: s for s in scenarios.get("scenarios", []) if "id" in s}

    def lookup(self, source: str, path: str) -> str:
        if source == "db":
            if path not in self.db:
                raise TemplateError(f"unknown db fact {path!r}")
            return self.db[path]
        head, _, rest = path.partition(".")
        if head in self._by_id and rest:
            value: Any = self._by_id[head]
            for part in rest.split("."):
                if not isinstance(value, dict) or part not in value:
                    raise TemplateError(f"unknown scenario field {path!r}")
                value = value[part]
        elif head in self.scenarios and not rest:
            value = self.scenarios[head]
        else:
            raise TemplateError(f"unknown scenario reference {path!r}")
        return _render(value)

    def resolve(self, text: str) -> str:
        return TEMPLATE.sub(lambda m: self.lookup(m.group(1), m.group(2)), text)

    def resolve_task(self, task: EvalTask) -> EvalTask:
        expected = task.expected

        def facts(items: list[RequiredFact]) -> list[RequiredFact]:
            return [
                RequiredFact(
                    description=self.resolve(f.description),
                    any_of=[self.resolve(a) for a in f.any_of],
                )
                for f in items
            ]

        resolved = expected.model_copy(
            update={
                "required_facts": facts(expected.required_facts),
                "forbidden_facts": facts(expected.forbidden_facts),
                "reference_answer": self.resolve(expected.reference_answer),
            }
        )
        return task.model_copy(
            update={"question": self.resolve(task.question), "expected": resolved}
        )


def _render(value: Any) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, list):
        return ", ".join(_render(v) for v in value)
    return str(value)


def money(value: float) -> str:
    return f"₹{value:,.0f}"


def pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}%"


def _scenario(scenarios: dict[str, Any], scenario_id: str) -> dict[str, Any]:
    return next(s for s in scenarios["scenarios"] if s["id"] == scenario_id)


# --- deterministic facts from the seeded database ---

FactFn = Callable[[dict[str, Any]], Awaitable[dict[str, str]]]


async def _periods(_: dict[str, Any]) -> dict[str, str]:
    from app.data.periods import current_period, previous_period

    current = current_period()
    previous = previous_period(current)
    return {
        "current_period": current,
        "previous_period": previous,
        "period_before_previous": previous_period(previous),
    }


async def _budgets(scenarios: dict[str, Any]) -> dict[str, str]:
    from app.data.periods import current_period, previous_period
    from app.data.repositories import finance

    current = current_period()
    facts: dict[str, str] = {}
    rows_now = {r.project_id: r for r in await finance.budget_vs_actual(current)}
    rows_prev = {r.project_id: r for r in await finance.budget_vs_actual(previous_period(current))}
    for role in ("over_budget", "both_problems", "understaffed", "healthy", "stale_repo"):
        project_id = _scenario(scenarios, role)["project_id"]
        for suffix, rows in (("", rows_now), ("_prev", rows_prev)):
            row = rows[project_id]
            facts[f"{role}_budget{suffix}"] = money(row.budget)
            facts[f"{role}_actual{suffix}"] = money(row.actual)
            facts[f"{role}_variance_pct{suffix}"] = pct(row.variance_pct)
            spend = row.actual / row.budget * 100 if row.budget else None
            facts[f"{role}_spend_pct{suffix}"] = pct(spend)
    overruns = await finance.top_overruns(current, n=10)
    facts["overrun_count"] = str(len(overruns))
    facts["top_overrun_name"] = overruns[0].project_name if overruns else "none"
    facts["second_overrun_name"] = overruns[1].project_name if len(overruns) > 1 else "none"
    return facts


async def _categories(scenarios: dict[str, Any]) -> dict[str, str]:
    from app.data.periods import current_period, period_bounds
    from app.data.repositories import finance

    start, end = period_bounds(current_period())
    project_id = _scenario(scenarios, "over_budget")["project_id"]
    categories = await finance.expenses_by_category(start, end, project_id=project_id)
    top = categories[0]
    return {
        "over_budget_top_category": top.category,
        "over_budget_top_category_label": top.category.replace("_", " "),
        "over_budget_top_category_total": money(top.total),
    }


async def _people_cost(scenarios: dict[str, Any]) -> dict[str, str]:
    from app.data.periods import current_period, period_bounds, previous_period
    from app.data.repositories import finance, hr

    previous = previous_period(current_period())
    before = previous_period(previous)
    growth = _scenario(scenarios, "people_cost_growth")
    dept_id = growth["department_id"]
    now = {r.department_id: r for r in await finance.people_cost_by_department(previous)}
    then = {r.department_id: r for r in await finance.people_cost_by_department(before)}
    increase = now[dept_id].total - then[dept_id].total
    growth_pct = increase / then[dept_id].total * 100
    team = await hr.project_staffing(_scenario(scenarios, "understaffed")["project_id"])
    start, end = period_bounds(previous)
    team_cost = await finance.people_cost([a.employee_id for a in team], start, end)
    lead_id = _scenario(scenarios, "most_open_issues")["lead_employee_id"]
    lead_cost = await finance.people_cost([lead_id], start, end)
    return {
        "growth_dept_cost_prev": money(now[dept_id].total),
        "growth_dept_cost_before": money(then[dept_id].total),
        "growth_dept_increase": money(increase),
        "growth_dept_growth_pct": pct(growth_pct),
        "growth_dept_paid_headcount_prev": str(now[dept_id].headcount_paid),
        "growth_dept_paid_headcount_before": str(then[dept_id].headcount_paid),
        "understaffed_team_cost_prev": money(team_cost.total),
        "most_open_issues_lead_cost_prev": money(lead_cost.total),
    }


async def _people(scenarios: dict[str, Any]) -> dict[str, str]:
    from app.data.repositories import hr, reference

    facts: dict[str, str] = {}
    for role in ("most_open_issues", "understaffed", "both_problems", "stale_repo", "over_budget"):
        scenario = _scenario(scenarios, role)
        lead = await hr.get_employee(scenario["lead_employee_id"])
        allocations = await hr.employee_allocations(scenario["lead_employee_id"])
        assert lead is not None and allocations is not None
        facts[f"{role}_lead_name"] = lead.full_name
        facts[f"{role}_lead_pct"] = f"{allocations.total_pct}%"
        staff = await hr.project_staffing(scenario["project_id"])
        others = [a.employee_name for a in staff if a.employee_id != lead.id]
        facts[f"{role}_team_size"] = str(len({a.employee_id for a in staff}))
        facts[f"{role}_member_name"] = others[0] if others else "none"
    over = await hr.over_allocated(100)
    facts["over_allocated_count"] = str(len(over))
    for index, item in enumerate(over[:3], start=1):
        facts[f"over_allocated_{index}_name"] = item.employee_name
        facts[f"over_allocated_{index}_pct"] = f"{item.total_pct}%"
    departments = {d.id: d for d in await reference.list_departments()}
    headcount = await hr.headcount_by_department()
    facts["headcount_total"] = str(sum(h.headcount for h in headcount))
    for h in headcount:
        facts[f"headcount_{departments[h.department_id].code.lower()}"] = str(h.headcount)
    positions = await hr.open_positions()
    facts["open_positions_total"] = str(len(positions))
    for code, dept in ((d.code.lower(), d) for d in departments.values()):
        facts[f"open_positions_{code}"] = str(sum(p.department_id == dept.id for p in positions))
    return facts


async def _delivery(scenarios: dict[str, Any]) -> dict[str, str]:
    from app.data.repositories import tech

    late = await tech.behind_schedule()
    facts = {"behind_schedule_count": str(len(late))}
    facts["behind_schedule_names"] = ", ".join(p.name for p in late)
    for role in ("understaffed", "both_problems", "stale_repo"):
        delivery = await tech.get_project_delivery(_scenario(scenarios, role)["project_id"])
        assert delivery is not None
        facts[f"{role}_days_late"] = str(delivery.days_late)
        facts[f"{role}_schedule_status"] = delivery.schedule_status
    at_risk = await tech.list_projects(status="at_risk")
    facts["at_risk_count"] = str(len(at_risk))
    for scenario in scenarios["scenarios"]:
        if scenario.get("repo_full_name"):
            facts[f"{scenario['id']}_repo"] = scenario["repo_full_name"].split("/")[-1]
    return facts


async def _github(scenarios: dict[str, Any]) -> dict[str, str]:
    """Open issue count as the agents' GitHub client reports it (issues only, no pull requests;
    scenarios.json's repo_open_issues_count is GitHub's figure, which includes pull requests)."""
    from app.integrations.github_client import GitHubClient

    repo = _scenario(scenarios, "most_open_issues")["repo_full_name"]
    client = GitHubClient(use_cache=False)
    try:
        issues = await client.list_open_issues(repo)
    finally:
        await client.aclose()
    return {"most_open_issues_count": str(len(issues.items))}


DB_FACTS: list[FactFn] = [
    _periods,
    _budgets,
    _categories,
    _people_cost,
    _people,
    _delivery,
    _github,
]


async def compute_db_facts(scenarios: dict[str, Any]) -> dict[str, str]:
    """Run every fact query against the currently configured database."""
    facts: dict[str, str] = {}
    for fn in DB_FACTS:
        facts.update(await fn(scenarios))
    return facts


async def build_context(scenarios: dict[str, Any]) -> FactContext:
    return FactContext(scenarios, await compute_db_facts(scenarios))
