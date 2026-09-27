"""HR-owned data: employees, allocations, leave and open positions. Never payroll."""

from collections import defaultdict
from datetime import date

from pydantic import BaseModel
from sqlalchemy import func, or_, select

from app.data.db import session_scope
from app.data.models import Allocation, Employee, Leave, OpenPosition
from app.data.periods import overlaps, today


class EmployeeRecord(BaseModel):
    id: int
    full_name: str
    email: str
    title: str
    department_id: int
    manager_id: int | None
    github_username: str | None
    hire_date: date
    termination_date: date | None
    ref: str


class AllocationRecord(BaseModel):
    id: int
    employee_id: int
    employee_name: str
    project_id: int
    role: str
    allocation_pct: int
    start_date: date
    end_date: date | None
    ref: str


class EmployeeAllocations(BaseModel):
    employee_id: int
    employee_name: str
    as_of: date
    total_pct: int
    allocations: list[AllocationRecord]


class LeaveRecord(BaseModel):
    id: int
    employee_id: int
    employee_name: str
    leave_type: str
    start_date: date
    end_date: date
    status: str
    ref: str


class OpenPositionRecord(BaseModel):
    id: int
    department_id: int
    project_id: int | None
    title: str
    opened_on: date
    status: str
    days_open: int
    ref: str


class DepartmentHeadcount(BaseModel):
    department_id: int
    as_of: date
    headcount: int
    employee_ids: list[int]
    ref: str


def _employee(row: Employee) -> EmployeeRecord:
    return EmployeeRecord(
        id=row.id,
        full_name=row.full_name,
        email=row.email,
        title=row.title,
        department_id=row.department_id,
        manager_id=row.manager_id,
        github_username=row.github_username,
        hire_date=row.hire_date,
        termination_date=row.termination_date,
        ref=f"employees:id={row.id}",
    )


def _allocation(row: Allocation, employee_name: str) -> AllocationRecord:
    return AllocationRecord(
        id=row.id,
        employee_id=row.employee_id,
        employee_name=employee_name,
        project_id=row.project_id,
        role=row.role,
        allocation_pct=row.allocation_pct,
        start_date=row.start_date,
        end_date=row.end_date,
        ref=f"allocations:id={row.id}",
    )


def _active_on(day: date):
    return (Allocation.start_date <= day) & (
        or_(Allocation.end_date.is_(None), Allocation.end_date >= day)
    )


async def get_employee(employee_id: int) -> EmployeeRecord | None:
    async with session_scope() as session:
        row = await session.get(Employee, employee_id)
        return _employee(row) if row else None


async def get_employee_by_github(username: str) -> EmployeeRecord | None:
    async with session_scope() as session:
        row = await session.scalar(
            select(Employee).where(func.lower(Employee.github_username) == username.lower())
        )
        return _employee(row) if row else None


async def search_employees(name: str) -> list[EmployeeRecord]:
    async with session_scope() as session:
        rows = await session.scalars(
            select(Employee)
            .where(func.lower(Employee.full_name).like(f"%{name.strip().lower()}%"))
            .order_by(Employee.id)
        )
        return [_employee(r) for r in rows]


async def list_employees(department_id: int | None = None) -> list[EmployeeRecord]:
    stmt = select(Employee).order_by(Employee.id)
    if department_id is not None:
        stmt = stmt.where(Employee.department_id == department_id)
    async with session_scope() as session:
        return [_employee(r) for r in await session.scalars(stmt)]


async def project_staffing(project_id: int, as_of: date | None = None) -> list[AllocationRecord]:
    day = as_of or today()
    async with session_scope() as session:
        rows = (
            await session.execute(
                select(Allocation, Employee.full_name)
                .join(Employee, Employee.id == Allocation.employee_id)
                .where(Allocation.project_id == project_id, _active_on(day))
                .order_by(Allocation.allocation_pct.desc(), Allocation.id)
            )
        ).all()
    return [_allocation(a, name) for a, name in rows]


async def employee_allocations(
    employee_id: int, as_of: date | None = None
) -> EmployeeAllocations | None:
    day = as_of or today()
    async with session_scope() as session:
        employee = await session.get(Employee, employee_id)
        if employee is None:
            return None
        rows = await session.scalars(
            select(Allocation)
            .where(Allocation.employee_id == employee_id, _active_on(day))
            .order_by(Allocation.id)
        )
        allocations = [_allocation(a, employee.full_name) for a in rows]
    return EmployeeAllocations(
        employee_id=employee_id,
        employee_name=employee.full_name,
        as_of=day,
        total_pct=sum(a.allocation_pct for a in allocations),
        allocations=allocations,
    )


async def over_allocated(
    threshold_pct: int = 100, as_of: date | None = None
) -> list[EmployeeAllocations]:
    day = as_of or today()
    async with session_scope() as session:
        rows = (
            await session.execute(
                select(Allocation, Employee.full_name)
                .join(Employee, Employee.id == Allocation.employee_id)
                .where(_active_on(day))
                .order_by(Allocation.employee_id, Allocation.id)
            )
        ).all()
    grouped: dict[int, list[AllocationRecord]] = defaultdict(list)
    for allocation, name in rows:
        grouped[allocation.employee_id].append(_allocation(allocation, name))
    result = [
        EmployeeAllocations(
            employee_id=employee_id,
            employee_name=items[0].employee_name,
            as_of=day,
            total_pct=sum(a.allocation_pct for a in items),
            allocations=items,
        )
        for employee_id, items in grouped.items()
    ]
    return sorted(
        (r for r in result if r.total_pct > threshold_pct), key=lambda r: r.total_pct, reverse=True
    )


async def list_leave(
    start: date, end: date, employee_ids: list[int] | None = None
) -> list[LeaveRecord]:
    stmt = (
        select(Leave, Employee.full_name)
        .join(Employee, Employee.id == Leave.employee_id)
        .where(Leave.start_date <= end, Leave.end_date >= start)
        .order_by(Leave.start_date, Leave.id)
    )
    if employee_ids is not None:
        stmt = stmt.where(Leave.employee_id.in_(employee_ids))
    async with session_scope() as session:
        rows = (await session.execute(stmt)).all()
    return [
        LeaveRecord(
            id=leave.id,
            employee_id=leave.employee_id,
            employee_name=name,
            leave_type=leave.leave_type,
            start_date=leave.start_date,
            end_date=leave.end_date,
            status=leave.status,
            ref=f"leave:id={leave.id}",
        )
        for leave, name in rows
    ]


async def leave_overlap(project_id: int, start: date, end: date) -> list[LeaveRecord]:
    """Leave taken by people allocated to the project during [start, end]."""
    async with session_scope() as session:
        allocations = await session.scalars(
            select(Allocation).where(Allocation.project_id == project_id)
        )
        employee_ids = sorted(
            {a.employee_id for a in allocations if overlaps(a.start_date, a.end_date, start, end)}
        )
    if not employee_ids:
        return []
    return await list_leave(start, end, employee_ids=employee_ids)


async def open_positions(department_id: int | None = None) -> list[OpenPositionRecord]:
    stmt = (
        select(OpenPosition).where(OpenPosition.status == "open").order_by(OpenPosition.opened_on)
    )
    if department_id is not None:
        stmt = stmt.where(OpenPosition.department_id == department_id)
    now = today()
    async with session_scope() as session:
        return [
            OpenPositionRecord(
                id=p.id,
                department_id=p.department_id,
                project_id=p.project_id,
                title=p.title,
                opened_on=p.opened_on,
                status=p.status,
                days_open=(now - p.opened_on).days,
                ref=f"open_positions:id={p.id}",
            )
            for p in await session.scalars(stmt)
        ]


async def headcount_by_department(as_of: date | None = None) -> list[DepartmentHeadcount]:
    day = as_of or today()
    async with session_scope() as session:
        rows = await session.scalars(
            select(Employee)
            .where(
                Employee.hire_date <= day,
                or_(Employee.termination_date.is_(None), Employee.termination_date > day),
            )
            .order_by(Employee.department_id, Employee.id)
        )
        grouped: dict[int, list[int]] = defaultdict(list)
        for employee in rows:
            grouped[employee.department_id].append(employee.id)
    return [
        DepartmentHeadcount(
            department_id=dept_id,
            as_of=day,
            headcount=len(ids),
            employee_ids=ids,
            ref=f"employees:department_id={dept_id},active_on={day}",
        )
        for dept_id, ids in grouped.items()
    ]
