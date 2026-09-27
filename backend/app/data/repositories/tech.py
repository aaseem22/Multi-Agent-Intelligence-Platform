"""Tech-owned data: project delivery fields."""

from datetime import date
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select

from app.data.db import session_scope
from app.data.models import Project
from app.data.periods import today

ScheduleStatus = Literal["completed", "on_track", "behind", "overdue", "not_started"]


class ProjectDelivery(BaseModel):
    id: int
    name: str
    repo_full_name: str | None
    department_id: int
    lead_employee_id: int | None
    status: str
    priority: str
    planned_start: date
    planned_end: date
    expected_end: date | None
    schedule_status: ScheduleStatus
    days_late: int  # expected (or today, if overdue) minus planned end; 0 when on time
    ref: str


def _schedule(row: Project, day: date) -> tuple[ScheduleStatus, int]:
    if row.status == "completed":
        return "completed", 0
    if row.planned_start > day:
        return "not_started", 0
    if row.planned_end < day:
        return "overdue", (day - row.planned_end).days
    if row.expected_end and row.expected_end > row.planned_end:
        return "behind", (row.expected_end - row.planned_end).days
    return "on_track", 0


def _delivery(row: Project, day: date) -> ProjectDelivery:
    schedule_status, days_late = _schedule(row, day)
    return ProjectDelivery(
        id=row.id,
        name=row.name,
        repo_full_name=row.repo_full_name,
        department_id=row.department_id,
        lead_employee_id=row.lead_employee_id,
        status=row.status,
        priority=row.priority,
        planned_start=row.planned_start,
        planned_end=row.planned_end,
        expected_end=row.expected_end,
        schedule_status=schedule_status,
        days_late=days_late,
        ref=f"projects:id={row.id}",
    )


async def list_projects(
    status: str | None = None, department_id: int | None = None
) -> list[ProjectDelivery]:
    stmt = select(Project).order_by(Project.id)
    if status:
        stmt = stmt.where(Project.status == status)
    if department_id is not None:
        stmt = stmt.where(Project.department_id == department_id)
    day = today()
    async with session_scope() as session:
        return [_delivery(r, day) for r in await session.scalars(stmt)]


async def get_project_delivery(project_id: int) -> ProjectDelivery | None:
    async with session_scope() as session:
        row = await session.get(Project, project_id)
        return _delivery(row, today()) if row else None


async def behind_schedule(department_id: int | None = None) -> list[ProjectDelivery]:
    projects = await list_projects(department_id=department_id)
    late = [p for p in projects if p.schedule_status in ("behind", "overdue")]
    return sorted(late, key=lambda p: p.days_late, reverse=True)
