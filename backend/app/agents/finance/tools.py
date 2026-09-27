"""Finance tools. Read-only; every result lists the record refs the agent cites as evidence.

Only imports Finance's own repository, shared reference data and period helpers.
"""

from datetime import date

from langchain_core.tools import BaseTool, tool

import app.data.periods as periods
import app.data.repositories.finance as finance_repo
import app.data.repositories.reference as reference_repo
from app.core.base_agent import db_evidence, evidence_result, tool_error
from app.core.contracts import Evidence
from app.data.repositories.reference import ProjectRef


class ToolInputError(ValueError):
    """Bad tool input; reported back to the LLM via tool_error, never raised out of a tool."""


def _period(period: str | None) -> str:
    try:
        return periods.normalise_period(period) if period else periods.current_period()
    except ValueError as exc:
        raise ToolInputError(str(exc)) from exc


def _date_range(start: str | None, end: str | None, period: str | None = None) -> tuple[date, date]:
    """Explicit start/end win; otherwise use the bounds of `period` (default: current quarter)."""
    default_start, default_end = periods.period_bounds(_period(period))
    try:
        start_date = periods.parse_date(start) if start else default_start
        end_date = periods.parse_date(end) if end else default_end
    except ValueError as exc:
        raise ToolInputError(f"Invalid date: {exc}. Use YYYY-MM-DD.") from exc
    if start_date > end_date:
        raise ToolInputError(f"start {start_date} is after end {end_date}")
    return start_date, end_date


async def _resolve_project(project: str | int) -> ProjectRef:
    """Accept a numeric project id or a (partial) project / repository name."""
    text = str(project).strip()
    if text.isdigit():
        ref = await reference_repo.get_project_ref(int(text))
        if ref is None:
            raise ToolInputError(f"No project with id {text}")
        return ref
    matches = await reference_repo.find_projects(text)
    exact = [m for m in matches if m.name.lower() == text.lower()]
    if len(exact) == 1:
        return exact[0]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ToolInputError(f"No project matches {text!r}")
    raise ToolInputError(
        f"{text!r} matches several projects; pass a project id",
    )


async def _resolve_department(department: str | int | None) -> int | None:
    if department is None or str(department).strip() == "":
        return None
    text = str(department).strip()
    if text.isdigit():
        ref = await reference_repo.get_department(int(text))
    else:
        ref = await reference_repo.find_department(text)
    if ref is None:
        raise ToolInputError(f"No department matches {text!r}")
    return ref.id


def _project_evidence(project: ProjectRef) -> Evidence:
    return db_evidence(project.ref, f"Project {project.id} is {project.name}")


async def _department_names() -> dict[int, str]:
    return {d.id: d.name for d in await reference_repo.list_departments()}


def _bva_evidence(rows: list[finance_repo.BudgetVsActualRow]) -> list[Evidence]:
    evidence: list[Evidence] = []
    for row in rows:
        excerpt = {
            "project_id": row.project_id,
            "period": row.period,
            "budget": row.budget,
            "actual": row.actual,
            "variance": row.variance,
            "variance_pct": row.variance_pct,
        }
        for ref in row.refs:
            kind = "budget" if ref.startswith("budgets:") else "spend"
            evidence.append(
                db_evidence(
                    ref,
                    f"{row.project_name} {row.period} {kind}: budget {row.budget} vs actual "
                    f"{row.actual} {row.currency} (variance {row.variance})",
                    excerpt,
                )
            )
    return evidence


@tool(parse_docstring=True)
async def get_project_budget(project: str, period: str | None = None) -> str:
    """Get a project's budget for a quarter, or all quarters when period is omitted.

    Args:
        project: Project id (e.g. "3") or project / repository name.
        period: Quarter such as "2026-Q3". Omit to list every quarter's budget.
    """
    try:
        ref = await _resolve_project(project)
        norm = _period(period) if period else None
        budgets = await finance_repo.get_project_budget(ref.id, norm)
    except ToolInputError as exc:
        return tool_error(str(exc))
    if not budgets:
        return tool_error(f"No budget found for {ref.name}", project_id=ref.id, period=norm)
    evidence = [_project_evidence(ref)] + [
        db_evidence(
            b.ref,
            f"{ref.name} budget for {b.period}: {b.amount} {b.currency}",
            b.model_dump(mode="json"),
        )
        for b in budgets
    ]
    data = {
        "project": ref.model_dump(mode="json"),
        "budgets": [b.model_dump(mode="json") for b in budgets],
    }
    return evidence_result(data, evidence)


@tool(parse_docstring=True)
async def get_project_spend(
    project: str,
    start: str | None = None,
    end: str | None = None,
    period: str | None = None,
) -> str:
    """Total spend (expenses) of a project between two dates, with a per-category split.

    Args:
        project: Project id (e.g. "3") or project / repository name.
        start: First day, YYYY-MM-DD. Defaults to the start of `period`.
        end: Last day, YYYY-MM-DD. Defaults to the end of `period`.
        period: Quarter such as "2026-Q3", used when start/end are omitted. Defaults to the current quarter.
    """
    try:
        ref = await _resolve_project(project)
        start_date, end_date = _date_range(start, end, period)
    except ToolInputError as exc:
        return tool_error(str(exc))
    spend = await finance_repo.get_project_spend(ref.id, start_date, end_date)
    evidence = [
        _project_evidence(ref),
        db_evidence(
            spend.ref,
            f"{ref.name} spent {spend.total} {spend.currency} across {spend.expense_count} "
            f"expenses from {start_date} to {end_date}",
            {"total": spend.total, "by_category": spend.by_category},
        ),
    ]
    data = {"project": ref.model_dump(mode="json"), "spend": spend.model_dump(mode="json")}
    return evidence_result(data, evidence)


@tool(parse_docstring=True)
async def budget_vs_actual(
    period: str | None = None, department: str | None = None, project: str | None = None
) -> str:
    """Budget vs actual spend per project for a quarter. Positive variance means overspend.

    Args:
        period: Quarter such as "2026-Q3". Defaults to the current quarter.
        department: Optional department id or name (e.g. "Engineering") to filter projects.
        project: Optional project id or name to return just that project.
    """
    try:
        norm = _period(period)
        department_id = await _resolve_department(department)
        project_ref = await _resolve_project(project) if project else None
    except ToolInputError as exc:
        return tool_error(str(exc))
    rows = await finance_repo.budget_vs_actual(norm, department_id)
    if project_ref is not None:
        rows = [r for r in rows if r.project_id == project_ref.id]
    if not rows:
        return tool_error("No projects found for that filter", period=norm)
    totals = {
        "budget": round(sum(r.budget for r in rows), 2),
        "actual": round(sum(r.actual for r in rows), 2),
    }
    totals["variance"] = round(totals["actual"] - totals["budget"], 2)
    data = {
        "period": norm,
        "department_id": department_id,
        "rows": [r.model_dump(mode="json") for r in rows],
        "totals": totals,
    }
    return evidence_result(data, _bva_evidence(rows))


@tool(parse_docstring=True)
async def expenses_by_category(
    project: str | None = None,
    start: str | None = None,
    end: str | None = None,
    period: str | None = None,
) -> str:
    """Expense totals grouped by category, largest first, for one project or all projects.

    Args:
        project: Optional project id or name. Omit for all projects.
        start: First day, YYYY-MM-DD. Defaults to the start of `period`.
        end: Last day, YYYY-MM-DD. Defaults to the end of `period`.
        period: Quarter such as "2026-Q3", used when start/end are omitted. Defaults to the current quarter.
    """
    try:
        ref = await _resolve_project(project) if project else None
        start_date, end_date = _date_range(start, end, period)
    except ToolInputError as exc:
        return tool_error(str(exc))
    categories = await finance_repo.expenses_by_category(
        start_date, end_date, project_id=ref.id if ref else None
    )
    scope = ref.name if ref else "All projects"
    evidence = [_project_evidence(ref)] if ref else []
    evidence += [
        db_evidence(
            c.ref,
            f"{scope} spent {c.total} {c.currency} on {c.category} "
            f"({c.expense_count} expenses, {start_date}..{end_date})",
            {"category": c.category, "total": c.total, "expense_count": c.expense_count},
        )
        for c in categories
    ]
    data = {
        "project": ref.model_dump(mode="json") if ref else None,
        "start": start_date,
        "end": end_date,
        "categories": [c.model_dump(mode="json") for c in categories],
    }
    return evidence_result(data, evidence)


@tool(parse_docstring=True)
async def people_cost(
    employee_ids: list[int],
    period: str | None = None,
    start: str | None = None,
    end: str | None = None,
) -> str:
    """Payroll cost of specific employees over a period. Finance does not know who works on a
    project: get the employee ids from HR with ask_agent first.

    Args:
        employee_ids: Employee ids to cost, e.g. [4, 15].
        period: Quarter such as "2026-Q3", used when start/end are omitted. Defaults to the current quarter.
        start: First day, YYYY-MM-DD. Overrides the period start.
        end: Last day, YYYY-MM-DD. Overrides the period end.
    """
    if not employee_ids:
        return tool_error(
            "employee_ids is empty. Ask HR (ask_agent) who is allocated to the project first."
        )
    try:
        start_date, end_date = _date_range(start, end, period)
    except ToolInputError as exc:
        return tool_error(str(exc))
    summary = await finance_repo.people_cost(employee_ids, start_date, end_date)
    missing = sorted(set(employee_ids) - set(summary.by_employee))
    evidence = [
        db_evidence(
            summary.ref,
            f"Payroll cost of employees {sorted(employee_ids)} from {start_date} to {end_date}: "
            f"{summary.total} {summary.currency}",
            {"total": summary.total, "by_employee": summary.by_employee},
        )
    ]
    data = {**summary.model_dump(mode="json"), "employees_without_payroll": missing}
    return evidence_result(data, evidence)


@tool(parse_docstring=True)
async def people_cost_by_department(
    period: str | None = None, compare_to: str | None = None
) -> str:
    """Payroll cost per department (cost centre) for a quarter, compared with an earlier quarter.
    Use it for "which department's people cost grew most" questions.

    Args:
        period: Quarter such as "2026-Q2". Defaults to the current quarter.
        compare_to: Quarter to compare against. Defaults to the quarter before `period`.
    """
    try:
        norm = _period(period)
        baseline = _period(compare_to) if compare_to else periods.previous_period(norm)
    except ToolInputError as exc:
        return tool_error(str(exc))
    current = {r.department_id: r for r in await finance_repo.people_cost_by_department(norm)}
    previous = {r.department_id: r for r in await finance_repo.people_cost_by_department(baseline)}
    if not current and not previous:
        return tool_error("No payroll found for those periods", period=norm, compare_to=baseline)
    names = await _department_names()
    rows, evidence = [], []
    for dept_id in sorted(set(current) | set(previous)):
        now, before = current.get(dept_id), previous.get(dept_id)
        total, prior = (now.total if now else 0.0), (before.total if before else 0.0)
        growth = round(total - prior, 2)
        name = names.get(dept_id, f"department {dept_id}")
        rows.append(
            {
                "department_id": dept_id,
                "department_name": name,
                "period": norm,
                "total": total,
                "headcount_paid": now.headcount_paid if now else 0,
                "compare_to": baseline,
                "previous_total": prior,
                "previous_headcount_paid": before.headcount_paid if before else 0,
                "growth": growth,
                "growth_pct": round(growth / prior * 100, 1) if prior else None,
                "currency": (now or before).currency,
                "refs": [r.ref for r in (now, before) if r],
            }
        )
        for record in (now, before):
            if record:
                evidence.append(
                    db_evidence(
                        record.ref,
                        f"{name} payroll {record.period}: {record.total} {record.currency} "
                        f"for {record.headcount_paid} paid employees",
                        record.model_dump(mode="json"),
                    )
                )
    rows.sort(key=lambda r: r["growth"], reverse=True)
    data = {"period": norm, "compare_to": baseline, "departments": rows}
    return evidence_result(data, evidence)


@tool(parse_docstring=True)
async def top_overruns(period: str | None = None, n: int = 5) -> str:
    """Projects that overspent their budget the most in a quarter, ranked by variance %.

    Args:
        period: Quarter such as "2026-Q3". Defaults to the current quarter.
        n: How many projects to return (1-50).
    """
    try:
        norm = _period(period)
    except ToolInputError as exc:
        return tool_error(str(exc))
    n = max(1, min(int(n), 50))
    rows = await finance_repo.top_overruns(norm, n)
    data = {"period": norm, "overruns": [r.model_dump(mode="json") for r in rows]}
    if not rows:
        data["note"] = "No project spent more than its budget in this period."
    return evidence_result(data, _bva_evidence(rows))


FINANCE_TOOLS: list[BaseTool] = [
    get_project_budget,
    get_project_spend,
    budget_vs_actual,
    expenses_by_category,
    people_cost,
    people_cost_by_department,
    top_overruns,
]
