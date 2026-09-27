"""HR tools. Read-only; every tool returns data plus the evidence refs of the records it used.

Only app.data.repositories.hr, app.data.repositories.reference and app.data.periods are read.
HR never reads payroll (owned by Finance).
"""

import logging
from collections.abc import Awaitable
from datetime import date, timedelta

from langchain_core.tools import BaseTool, tool

from app.core.base_agent import db_evidence, evidence_result, tool_error
from app.core.contracts import Evidence
from app.data.periods import parse_date, today
from app.data.repositories import hr as hr_repo
from app.data.repositories import reference

logger = logging.getLogger(__name__)

DEFAULT_LEAVE_WINDOW_DAYS = 30
MAX_EVIDENCE_ITEMS = 60


class ToolInputError(ValueError):
    """Bad or unresolvable tool input, reported back to the LLM as a tool error."""


async def _guard(work: Awaitable[str]) -> str:
    try:
        return await work
    except ToolInputError as exc:
        return tool_error(str(exc))
    except Exception as exc:
        logger.exception("HR tool failed")
        return tool_error(f"HR tool failed: {exc.__class__.__name__}: {exc}")


def _date(value: str | None, field: str) -> date | None:
    if value is None or not str(value).strip():
        return None
    try:
        return parse_date(str(value).strip())
    except ValueError as exc:
        raise ToolInputError(f"{field} must be an ISO date (YYYY-MM-DD), got {value!r}") from exc


async def _resolve_project(project: str) -> reference.ProjectRef:
    needle = str(project).strip()
    if not needle:
        raise ToolInputError("project is required (id, name or repository name)")
    if needle.isdigit():
        ref = await reference.get_project_ref(int(needle))
        if ref is None:
            raise ToolInputError(f"No project with id {needle}")
        return ref
    by_repo = await reference.get_project_by_repo(needle)
    if by_repo is not None:
        return by_repo
    matches = await reference.find_projects(needle)
    exact = [m for m in matches if m.name.lower() == needle.lower()]
    if len(exact) == 1:
        return exact[0]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ToolInputError(f"No project matches {needle!r}")
    candidates = ", ".join(f"{m.id}: {m.name}" for m in matches[:10])
    raise ToolInputError(f"{needle!r} matches several projects ({candidates}); pass the id")


async def _resolve_department(department: str) -> reference.DepartmentRef:
    needle = str(department).strip()
    ref = (
        await reference.get_department(int(needle))
        if needle.isdigit()
        else await reference.find_department(needle)
    )
    if ref is None:
        raise ToolInputError(f"No department matches {needle!r}")
    return ref


async def _project_names() -> dict[int, str]:
    return {p.id: p.name for p in await reference.list_project_refs()}


async def _department_names() -> dict[int, str]:
    return {d.id: d.name for d in await reference.list_departments()}


def _project_evidence(project: reference.ProjectRef) -> Evidence:
    return db_evidence(project.ref, f"Project {project.id}: {project.name}", project)


def _capped(evidence: list[Evidence]) -> list[Evidence]:
    return evidence[:MAX_EVIDENCE_ITEMS]


# --- get_employee -----------------------------------------------------------------------


async def _get_employee(
    employee_id: int | None, github_username: str | None, name: str | None
) -> str:
    if employee_id is not None:
        found = await hr_repo.get_employee(int(employee_id))
        employees = [found] if found else []
    elif github_username and github_username.strip():
        found = await hr_repo.get_employee_by_github(github_username.strip().lstrip("@"))
        employees = [found] if found else []
    elif name and name.strip():
        employees = await hr_repo.search_employees(name)
    else:
        raise ToolInputError("Pass one of employee_id, github_username or name")
    if not employees:
        return evidence_result({"employees": [], "message": "No matching employee"}, [])
    departments = await _department_names()
    rows = [
        {**e.model_dump(mode="json"), "department_name": departments.get(e.department_id)}
        for e in employees
    ]
    evidence = [
        db_evidence(e.ref, f"Employee {e.id}: {e.full_name}, {e.title}", row)
        for e, row in zip(employees, rows, strict=True)
    ]
    return evidence_result({"employees": rows}, _capped(evidence))


@tool(parse_docstring=True)
async def get_employee(
    employee_id: int | None = None,
    github_username: str | None = None,
    name: str | None = None,
) -> str:
    """Look up employees by id, GitHub username or (partial) name.

    Returns id, full name, title, department, manager, GitHub username and hire/termination
    dates. Pass exactly one argument.

    Args:
        employee_id: Numeric employee id.
        github_username: GitHub login, e.g. "octocat".
        name: Full or partial employee name; may match several people.
    """
    return await _guard(_get_employee(employee_id, github_username, name))


# --- project_staffing -------------------------------------------------------------------


async def _project_staffing(project: str, as_of: str | None) -> str:
    ref = await _resolve_project(project)
    day = _date(as_of, "as_of") or today()
    allocations = await hr_repo.project_staffing(ref.id, as_of=day)
    data = {
        "project_id": ref.id,
        "project_name": ref.name,
        "repo_full_name": ref.repo_full_name,
        "as_of": day,
        "headcount": len({a.employee_id for a in allocations}),
        "total_allocation_pct": sum(a.allocation_pct for a in allocations),
        "allocations": [a.model_dump(mode="json") for a in allocations],
    }
    evidence = [_project_evidence(ref)] + [
        db_evidence(
            a.ref,
            f"{a.employee_name} (employee {a.employee_id}) is {a.role} on {ref.name} at "
            f"{a.allocation_pct}%",
            a,
        )
        for a in allocations
    ]
    return evidence_result(data, _capped(evidence))


@tool(parse_docstring=True)
async def project_staffing(project: str, as_of: str | None = None) -> str:
    """List the people allocated to a project on a date: name, employee id, role and percent.

    Args:
        project: Project id (e.g. "4"), project name or repository name ("owner/repo").
        as_of: ISO date (YYYY-MM-DD); defaults to today.
    """
    return await _guard(_project_staffing(project, as_of))


# --- employee_allocations ---------------------------------------------------------------


async def _employee_allocations(employee_id: int, as_of: str | None) -> str:
    day = _date(as_of, "as_of") or today()
    result = await hr_repo.employee_allocations(int(employee_id), as_of=day)
    if result is None:
        raise ToolInputError(f"No employee with id {employee_id}")
    projects = await _project_names()
    allocations = [
        {**a.model_dump(mode="json"), "project_name": projects.get(a.project_id)}
        for a in result.allocations
    ]
    data = {
        **result.model_dump(mode="json", exclude={"allocations"}),
        "over_allocated": result.total_pct > 100,
        "allocations": allocations,
    }
    evidence = [
        db_evidence(
            f"employees:id={result.employee_id}",
            f"Employee {result.employee_id}: {result.employee_name}",
        )
    ] + [
        db_evidence(
            row["ref"],
            f"{result.employee_name} is {row['role']} on {row['project_name']} at "
            f"{row['allocation_pct']}%",
            row,
        )
        for row in allocations
    ]
    return evidence_result(data, _capped(evidence))


@tool(parse_docstring=True)
async def employee_allocations(employee_id: int, as_of: str | None = None) -> str:
    """An employee's active project allocations and their total allocation percent.

    Args:
        employee_id: Numeric employee id (use get_employee to find it from a name or username).
        as_of: ISO date (YYYY-MM-DD); defaults to today.
    """
    return await _guard(_employee_allocations(employee_id, as_of))


# --- over_allocated ---------------------------------------------------------------------


async def _over_allocated(threshold_pct: int, as_of: str | None) -> str:
    day = _date(as_of, "as_of") or today()
    rows = await hr_repo.over_allocated(int(threshold_pct), as_of=day)
    projects = await _project_names()
    people = [
        {
            "employee_id": r.employee_id,
            "employee_name": r.employee_name,
            "total_pct": r.total_pct,
            "allocations": [
                {
                    "allocation_id": a.id,
                    "project_id": a.project_id,
                    "project_name": projects.get(a.project_id),
                    "role": a.role,
                    "allocation_pct": a.allocation_pct,
                    "ref": a.ref,
                }
                for a in r.allocations
            ],
        }
        for r in rows
    ]
    evidence: list[Evidence] = []
    for r in rows:
        evidence.append(
            db_evidence(
                f"employees:id={r.employee_id}",
                f"{r.employee_name} (employee {r.employee_id}) is allocated {r.total_pct}%",
            )
        )
        evidence.extend(
            db_evidence(
                a.ref,
                f"{r.employee_name}: {a.allocation_pct}% on {projects.get(a.project_id)}",
                a,
            )
            for a in r.allocations
        )
    data = {"threshold_pct": threshold_pct, "as_of": day, "count": len(people), "people": people}
    return evidence_result(data, _capped(evidence))


@tool(parse_docstring=True)
async def over_allocated(threshold_pct: int = 100, as_of: str | None = None) -> str:
    """Employees whose total active allocation exceeds threshold_pct, highest first.

    Args:
        threshold_pct: Allocation percent above which someone counts as over-allocated.
        as_of: ISO date (YYYY-MM-DD); defaults to today.
    """
    return await _guard(_over_allocated(threshold_pct, as_of))


# --- leave_overlap ----------------------------------------------------------------------


def _max_concurrent_away(leave: list[hr_repo.LeaveRecord], start: date, end: date) -> int:
    peak, day = 0, start
    while day <= end:
        away = {r.employee_id for r in leave if r.start_date <= day <= r.end_date}
        peak = max(peak, len(away))
        day += timedelta(days=1)
    return peak


async def _leave_overlap(project: str, start: str | None, end: str | None) -> str:
    ref = await _resolve_project(project)
    window_start = _date(start, "start") or today()
    window_end = _date(end, "end") or window_start + timedelta(days=DEFAULT_LEAVE_WINDOW_DAYS)
    if window_end < window_start:
        raise ToolInputError("end must be on or after start")
    staffing = await hr_repo.project_staffing(ref.id, as_of=window_start)
    leave = await hr_repo.leave_overlap(ref.id, window_start, window_end)

    leave_by_person: dict[int, list[hr_repo.LeaveRecord]] = {}
    for record in leave:
        leave_by_person.setdefault(record.employee_id, []).append(record)
    team = [
        {
            "employee_id": a.employee_id,
            "employee_name": a.employee_name,
            "role": a.role,
            "allocation_pct": a.allocation_pct,
            "allocation_ref": a.ref,
            "away": a.employee_id in leave_by_person,
            "leave_ids": [r.id for r in leave_by_person.get(a.employee_id, [])],
        }
        for a in staffing
    ]
    staffed_ids = {a.employee_id for a in staffing}
    away_ids = sorted(leave_by_person)
    data = {
        "project_id": ref.id,
        "project_name": ref.name,
        "window": {"start": window_start, "end": window_end},
        "team_size": len(staffed_ids),
        "people_away": len(away_ids),
        "away_employee_ids": away_ids,
        "max_concurrent_away": _max_concurrent_away(leave, window_start, window_end),
        "team": team,
        "leave": [r.model_dump(mode="json") for r in leave],
    }
    evidence = (
        [_project_evidence(ref)]
        + [
            db_evidence(
                r.ref,
                f"{r.employee_name} (employee {r.employee_id}) on {r.leave_type} leave "
                f"{r.start_date} to {r.end_date} ({r.status})",
                r,
            )
            for r in leave
        ]
        + [
            db_evidence(a.ref, f"{a.employee_name} allocated {a.allocation_pct}% to {ref.name}", a)
            for a in staffing
        ]
    )
    return evidence_result(data, _capped(evidence))


@tool(parse_docstring=True)
async def leave_overlap(project: str, start: str | None = None, end: str | None = None) -> str:
    """Leave taken by people allocated to a project within a date window, flagging who is away.

    Returns the team with an `away` flag per person, each leave record, the number of people
    away and the peak number away on the same day.

    Args:
        project: Project id (e.g. "4"), project name or repository name ("owner/repo").
        start: Window start, ISO date (YYYY-MM-DD); defaults to today.
        end: Window end, ISO date; defaults to 30 days after start.
    """
    return await _guard(_leave_overlap(project, start, end))


# --- open_positions ---------------------------------------------------------------------


async def _open_positions(department: str | None) -> str:
    dept = await _resolve_department(department) if department and department.strip() else None
    positions = await hr_repo.open_positions(dept.id if dept else None)
    departments = await _department_names()
    projects = await _project_names()
    rows = [
        {
            **p.model_dump(mode="json"),
            "department_name": departments.get(p.department_id),
            "project_name": projects.get(p.project_id) if p.project_id else None,
        }
        for p in positions
    ]
    evidence = [
        db_evidence(
            row["ref"],
            f"Open position {row['id']}: {row['title']} in {row['department_name']}"
            + (f" for {row['project_name']}" if row["project_name"] else "")
            + f", open {row['days_open']} days",
            row,
        )
        for row in rows
    ]
    data = {
        "department_id": dept.id if dept else None,
        "department_name": dept.name if dept else None,
        "count": len(rows),
        "positions": rows,
    }
    return evidence_result(data, _capped(evidence))


@tool(parse_docstring=True)
async def open_positions(department: str | None = None) -> str:
    """Open (unfilled) positions with department, linked project and days open.

    Args:
        department: Optional department id, name or code (e.g. "Engineering" or "ENG").
    """
    return await _guard(_open_positions(department))


# --- headcount_by_department ------------------------------------------------------------


async def _headcount_by_department(as_of: str | None) -> str:
    day = _date(as_of, "as_of") or today()
    rows = await hr_repo.headcount_by_department(as_of=day)
    departments = await _department_names()
    data = {
        "as_of": day,
        "total": sum(r.headcount for r in rows),
        "departments": [
            {**r.model_dump(mode="json"), "department_name": departments.get(r.department_id)}
            for r in rows
        ],
    }
    evidence = [
        db_evidence(
            r.ref,
            f"{departments.get(r.department_id)} headcount {r.headcount} on {day}",
            {"department_id": r.department_id, "headcount": r.headcount},
        )
        for r in rows
    ]
    return evidence_result(data, evidence)


@tool(parse_docstring=True)
async def headcount_by_department(as_of: str | None = None) -> str:
    """Active employee headcount per department on a date, with the employee ids counted.

    Args:
        as_of: ISO date (YYYY-MM-DD); defaults to today.
    """
    return await _guard(_headcount_by_department(as_of))


HR_TOOLS: list[BaseTool] = [
    get_employee,
    project_staffing,
    employee_allocations,
    over_allocated,
    leave_overlap,
    open_positions,
    headcount_by_department,
]
