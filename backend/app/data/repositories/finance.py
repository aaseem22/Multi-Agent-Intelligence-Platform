"""Finance-owned data: budgets, expenses and payroll."""

from collections import defaultdict
from datetime import date

from pydantic import BaseModel
from sqlalchemy import func, select

from app.data.db import session_scope
from app.data.models import Budget, Expense, Payroll, Project
from app.data.periods import normalise_period, period_bounds


class BudgetRecord(BaseModel):
    id: int
    project_id: int
    period: str
    amount: float
    currency: str
    ref: str


class ExpenseRecord(BaseModel):
    id: int
    project_id: int
    category: str
    vendor: str
    amount: float
    currency: str
    spent_on: date
    description: str
    ref: str


class SpendSummary(BaseModel):
    project_id: int
    start: date
    end: date
    total: float
    currency: str
    expense_count: int
    expense_ids: list[int]
    by_category: dict[str, float]
    ref: str


class BudgetVsActualRow(BaseModel):
    project_id: int
    project_name: str
    department_id: int
    period: str
    budget_id: int | None
    budget: float
    actual: float
    variance: float  # actual - budget; positive means overspend
    variance_pct: float | None
    expense_count: int
    currency: str
    refs: list[str]


class CategoryTotal(BaseModel):
    category: str
    total: float
    expense_count: int
    expense_ids: list[int]
    currency: str
    ref: str


class PayrollRecord(BaseModel):
    id: int
    employee_id: int
    department_id: int
    month: date
    gross_cost: float
    currency: str
    ref: str


class PeopleCostSummary(BaseModel):
    start: date
    end: date
    total: float
    currency: str
    by_employee: dict[int, float]
    payroll_ids: list[int]
    ref: str


class DepartmentPeopleCost(BaseModel):
    department_id: int
    period: str
    total: float
    headcount_paid: int
    currency: str
    ref: str


def _budget(row: Budget) -> BudgetRecord:
    return BudgetRecord(
        id=row.id,
        project_id=row.project_id,
        period=row.period,
        amount=row.amount,
        currency=row.currency,
        ref=f"budgets:id={row.id}",
    )


def _expense(row: Expense) -> ExpenseRecord:
    return ExpenseRecord(
        id=row.id,
        project_id=row.project_id,
        category=row.category,
        vendor=row.vendor,
        amount=row.amount,
        currency=row.currency,
        spent_on=row.spent_on,
        description=row.description,
        ref=f"expenses:id={row.id}",
    )


def _payroll(row: Payroll) -> PayrollRecord:
    return PayrollRecord(
        id=row.id,
        employee_id=row.employee_id,
        department_id=row.department_id,
        month=row.month,
        gross_cost=row.gross_cost,
        currency=row.currency,
        ref=f"payroll:id={row.id}",
    )


async def get_project_budget(project_id: int, period: str | None = None) -> list[BudgetRecord]:
    stmt = select(Budget).where(Budget.project_id == project_id).order_by(Budget.period)
    if period:
        stmt = stmt.where(Budget.period == normalise_period(period))
    async with session_scope() as session:
        return [_budget(r) for r in await session.scalars(stmt)]


async def list_expenses(
    start: date, end: date, project_id: int | None = None, category: str | None = None
) -> list[ExpenseRecord]:
    stmt = (
        select(Expense)
        .where(Expense.spent_on >= start, Expense.spent_on <= end)
        .order_by(Expense.spent_on, Expense.id)
    )
    if project_id is not None:
        stmt = stmt.where(Expense.project_id == project_id)
    if category:
        stmt = stmt.where(func.lower(Expense.category) == category.lower())
    async with session_scope() as session:
        return [_expense(r) for r in await session.scalars(stmt)]


async def get_project_spend(project_id: int, start: date, end: date) -> SpendSummary:
    expenses = await list_expenses(start, end, project_id=project_id)
    by_category: dict[str, float] = defaultdict(float)
    for expense in expenses:
        by_category[expense.category] += expense.amount
    return SpendSummary(
        project_id=project_id,
        start=start,
        end=end,
        total=round(sum(e.amount for e in expenses), 2),
        currency=expenses[0].currency if expenses else "",
        expense_count=len(expenses),
        expense_ids=[e.id for e in expenses],
        by_category={k: round(v, 2) for k, v in sorted(by_category.items())},
        ref=f"expenses:project_id={project_id},spent_on={start}..{end}",
    )


async def budget_vs_actual(
    period: str, department_id: int | None = None
) -> list[BudgetVsActualRow]:
    period = normalise_period(period)
    start, end = period_bounds(period)
    async with session_scope() as session:
        project_stmt = select(Project.id, Project.name, Project.department_id).order_by(Project.id)
        if department_id is not None:
            project_stmt = project_stmt.where(Project.department_id == department_id)
        projects = (await session.execute(project_stmt)).all()
        budgets = {
            b.project_id: b
            for b in await session.scalars(select(Budget).where(Budget.period == period))
        }
        spend_rows = (
            await session.execute(
                select(Expense.project_id, func.sum(Expense.amount), func.count(Expense.id))
                .where(Expense.spent_on >= start, Expense.spent_on <= end)
                .group_by(Expense.project_id)
            )
        ).all()
    spend = {pid: (float(total or 0), int(count)) for pid, total, count in spend_rows}
    rows: list[BudgetVsActualRow] = []
    for project_id, name, dept_id in projects:
        budget = budgets.get(project_id)
        actual, count = spend.get(project_id, (0.0, 0))
        amount = budget.amount if budget else 0.0
        refs = [f"expenses:project_id={project_id},period={period}"]
        if budget:
            refs.insert(0, f"budgets:id={budget.id}")
        rows.append(
            BudgetVsActualRow(
                project_id=project_id,
                project_name=name,
                department_id=dept_id,
                period=period,
                budget_id=budget.id if budget else None,
                budget=round(amount, 2),
                actual=round(actual, 2),
                variance=round(actual - amount, 2),
                variance_pct=round((actual - amount) / amount * 100, 1) if amount else None,
                expense_count=count,
                currency=budget.currency if budget else "",
                refs=refs,
            )
        )
    return rows


async def expenses_by_category(
    start: date, end: date, project_id: int | None = None
) -> list[CategoryTotal]:
    expenses = await list_expenses(start, end, project_id=project_id)
    grouped: dict[str, list[ExpenseRecord]] = defaultdict(list)
    for expense in expenses:
        grouped[expense.category].append(expense)
    scope = f"project_id={project_id}," if project_id is not None else ""
    return sorted(
        (
            CategoryTotal(
                category=category,
                total=round(sum(e.amount for e in items), 2),
                expense_count=len(items),
                expense_ids=[e.id for e in items],
                currency=items[0].currency,
                ref=f"expenses:{scope}category={category},spent_on={start}..{end}",
            )
            for category, items in grouped.items()
        ),
        key=lambda c: c.total,
        reverse=True,
    )


async def list_payroll(
    start: date,
    end: date,
    employee_ids: list[int] | None = None,
    department_id: int | None = None,
) -> list[PayrollRecord]:
    stmt = (
        select(Payroll)
        .where(Payroll.month >= date(start.year, start.month, 1), Payroll.month <= end)
        .order_by(Payroll.month, Payroll.employee_id)
    )
    if employee_ids is not None:
        stmt = stmt.where(Payroll.employee_id.in_(employee_ids))
    if department_id is not None:
        stmt = stmt.where(Payroll.department_id == department_id)
    async with session_scope() as session:
        return [_payroll(r) for r in await session.scalars(stmt)]


async def people_cost(employee_ids: list[int], start: date, end: date) -> PeopleCostSummary:
    records = await list_payroll(start, end, employee_ids=employee_ids)
    by_employee: dict[int, float] = defaultdict(float)
    for record in records:
        by_employee[record.employee_id] += record.gross_cost
    ids = ",".join(str(i) for i in sorted(employee_ids))
    return PeopleCostSummary(
        start=start,
        end=end,
        total=round(sum(r.gross_cost for r in records), 2),
        currency=records[0].currency if records else "",
        by_employee={k: round(v, 2) for k, v in sorted(by_employee.items())},
        payroll_ids=[r.id for r in records],
        ref=f"payroll:employee_id in ({ids}),month={start}..{end}",
    )


async def people_cost_by_department(period: str) -> list[DepartmentPeopleCost]:
    period = normalise_period(period)
    start, end = period_bounds(period)
    async with session_scope() as session:
        rows = (
            await session.execute(
                select(
                    Payroll.department_id,
                    func.sum(Payroll.gross_cost),
                    func.count(func.distinct(Payroll.employee_id)),
                    func.min(Payroll.currency),
                )
                .where(Payroll.month >= start, Payroll.month <= end)
                .group_by(Payroll.department_id)
                .order_by(Payroll.department_id)
            )
        ).all()
    return [
        DepartmentPeopleCost(
            department_id=dept_id,
            period=period,
            total=round(float(total), 2),
            headcount_paid=int(headcount),
            currency=currency,
            ref=f"payroll:department_id={dept_id},period={period}",
        )
        for dept_id, total, headcount, currency in rows
    ]


async def top_overruns(period: str, n: int = 5) -> list[BudgetVsActualRow]:
    rows = [r for r in await budget_vs_actual(period) if r.budget and r.variance > 0]
    return sorted(rows, key=lambda r: r.variance_pct or 0, reverse=True)[:n]
