"""Shared reference data readable by every agent: departments and project identity columns."""

from pydantic import BaseModel
from sqlalchemy import func, or_, select

from app.data.db import session_scope
from app.data.models import Department, Project


class DepartmentRef(BaseModel):
    id: int
    name: str
    code: str
    ref: str


class ProjectRef(BaseModel):
    id: int
    name: str
    repo_full_name: str | None
    department_id: int
    ref: str


def _department(row: Department) -> DepartmentRef:
    return DepartmentRef(id=row.id, name=row.name, code=row.code, ref=f"departments:id={row.id}")


def _project(row: Project) -> ProjectRef:
    return ProjectRef(
        id=row.id,
        name=row.name,
        repo_full_name=row.repo_full_name,
        department_id=row.department_id,
        ref=f"projects:id={row.id}",
    )


async def list_departments() -> list[DepartmentRef]:
    async with session_scope() as session:
        rows = await session.scalars(select(Department).order_by(Department.id))
        return [_department(r) for r in rows]


async def get_department(department_id: int) -> DepartmentRef | None:
    async with session_scope() as session:
        row = await session.get(Department, department_id)
        return _department(row) if row else None


async def find_department(name_or_code: str) -> DepartmentRef | None:
    needle = name_or_code.strip().lower()
    async with session_scope() as session:
        row = await session.scalar(
            select(Department).where(
                or_(func.lower(Department.name) == needle, func.lower(Department.code) == needle)
            )
        )
        return _department(row) if row else None


async def list_project_refs(department_id: int | None = None) -> list[ProjectRef]:
    stmt = select(Project).order_by(Project.id)
    if department_id is not None:
        stmt = stmt.where(Project.department_id == department_id)
    async with session_scope() as session:
        return [_project(r) for r in await session.scalars(stmt)]


async def get_project_ref(project_id: int) -> ProjectRef | None:
    async with session_scope() as session:
        row = await session.get(Project, project_id)
        return _project(row) if row else None


async def get_project_by_repo(repo_full_name: str) -> ProjectRef | None:
    async with session_scope() as session:
        row = await session.scalar(
            select(Project).where(func.lower(Project.repo_full_name) == repo_full_name.lower())
        )
        return _project(row) if row else None


async def find_projects(query: str) -> list[ProjectRef]:
    """Case-insensitive match on project name or repository name."""
    pattern = f"%{query.strip().lower()}%"
    async with session_scope() as session:
        rows = await session.scalars(
            select(Project)
            .where(
                or_(
                    func.lower(Project.name).like(pattern),
                    func.lower(Project.repo_full_name).like(pattern),
                )
            )
            .order_by(Project.id)
        )
        return [_project(r) for r in rows]
