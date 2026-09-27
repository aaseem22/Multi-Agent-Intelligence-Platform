"""Finance tools against the seeded test database. No LLM involved."""

import json

import pytest

from app.agents.finance.tools import (
    FINANCE_TOOLS,
    budget_vs_actual,
    expenses_by_category,
    get_project_budget,
    get_project_spend,
    people_cost,
    people_cost_by_department,
    top_overruns,
)
from app.data import periods

pytestmark = pytest.mark.usefixtures("seeded_db")


def _scenario(scenarios: dict, scenario_id: str) -> dict:
    return next(s for s in scenarios["scenarios"] if s["id"] == scenario_id)


async def _call(tool, args: dict) -> dict:
    return json.loads(await tool.ainvoke(args))


def _refs(out: dict) -> list[str]:
    assert "error" not in out, out
    refs = [e["source_ref"] for e in out["evidence"]]
    assert refs, "tool returned no evidence refs"
    return refs


def test_tool_names_match_spec():
    assert {t.name for t in FINANCE_TOOLS} == {
        "get_project_budget",
        "get_project_spend",
        "budget_vs_actual",
        "expenses_by_category",
        "people_cost",
        "people_cost_by_department",
        "top_overruns",
    }


async def test_get_project_budget_by_id(scenarios):
    over = _scenario(scenarios, "over_budget")
    out = await _call(
        get_project_budget, {"project": str(over["project_id"]), "period": over["period"]}
    )
    refs = _refs(out)
    [budget] = out["data"]["budgets"]
    assert budget["amount"] == pytest.approx(over["budget"])
    assert f"budgets:id={budget['id']}" in refs
    assert f"projects:id={over['project_id']}" in refs


async def test_get_project_budget_by_name_lists_all_quarters(scenarios):
    over = _scenario(scenarios, "over_budget")
    out = await _call(get_project_budget, {"project": over["project_name"]})
    _refs(out)
    assert out["data"]["project"]["id"] == over["project_id"]
    assert len(out["data"]["budgets"]) >= 4


async def test_get_project_budget_unknown_project_is_error_not_exception():
    out = await _call(get_project_budget, {"project": "no-such-project-xyz"})
    assert "error" in out


async def test_invalid_period_is_error():
    out = await _call(budget_vs_actual, {"period": "last year"})
    assert "error" in out


async def test_get_project_spend_matches_budget_vs_actual(scenarios):
    over = _scenario(scenarios, "over_budget")
    out = await _call(
        get_project_spend, {"project": str(over["project_id"]), "period": over["period"]}
    )
    refs = _refs(out)
    spend = out["data"]["spend"]
    assert spend["total"] > 0
    assert spend["expense_ids"]
    assert spend["ref"] in refs
    assert spend["total"] == pytest.approx(over["budget"] * over["spend_ratio"], rel=0.15)


async def test_get_project_spend_explicit_dates(scenarios):
    over = _scenario(scenarios, "over_budget")
    start, end = periods.period_bounds(over["period"])
    out = await _call(
        get_project_spend,
        {"project": over["project_name"], "start": start.isoformat(), "end": end.isoformat()},
    )
    _refs(out)
    assert out["data"]["spend"]["start"] == start.isoformat()


async def test_budget_vs_actual_over_budget_scenario_positive_variance(scenarios):
    over = _scenario(scenarios, "over_budget")
    out = await _call(budget_vs_actual, {"period": over["period"]})
    refs = _refs(out)
    row = next(r for r in out["data"]["rows"] if r["project_id"] == over["project_id"])
    assert row["variance"] > 0
    assert f"budgets:id={row['budget_id']}" in refs


async def test_budget_vs_actual_healthy_is_within_budget(scenarios):
    healthy = _scenario(scenarios, "healthy")
    out = await _call(
        budget_vs_actual, {"period": healthy["period"], "project": str(healthy["project_id"])}
    )
    _refs(out)
    [row] = out["data"]["rows"]
    assert row["variance"] < 0


async def test_budget_vs_actual_department_filter(scenarios):
    over = _scenario(scenarios, "over_budget")
    out = await _call(
        budget_vs_actual, {"period": over["period"], "department": str(over["department_id"])}
    )
    _refs(out)
    assert {r["department_id"] for r in out["data"]["rows"]} == {over["department_id"]}


async def test_expenses_by_category_for_project(scenarios):
    over = _scenario(scenarios, "over_budget")
    out = await _call(
        expenses_by_category, {"project": str(over["project_id"]), "period": over["period"]}
    )
    refs = _refs(out)
    categories = out["data"]["categories"]
    assert categories
    totals = [c["total"] for c in categories]
    assert totals == sorted(totals, reverse=True)
    assert all(c["ref"] in refs and c["expense_ids"] for c in categories)


async def test_expenses_by_category_all_projects(scenarios):
    over = _scenario(scenarios, "over_budget")
    out = await _call(expenses_by_category, {"period": over["period"]})
    _refs(out)
    assert out["data"]["project"] is None


async def test_people_cost_for_employees(scenarios):
    over = _scenario(scenarios, "over_budget")
    ids = [over["lead_employee_id"], _scenario(scenarios, "healthy")["lead_employee_id"]]
    out = await _call(people_cost, {"employee_ids": ids, "period": over["period"]})
    refs = _refs(out)
    data = out["data"]
    assert data["total"] > 0
    assert data["payroll_ids"]
    assert data["ref"] in refs
    assert {int(k) for k in data["by_employee"]} == set(ids)


async def test_people_cost_empty_ids_points_to_hr():
    out = await _call(people_cost, {"employee_ids": []})
    assert "HR" in out["error"]


async def test_people_cost_by_department_growth_scenario(scenarios):
    growth = _scenario(scenarios, "people_cost_growth")
    out = await _call(
        people_cost_by_department, {"period": growth["period"], "compare_to": growth["compared_to"]}
    )
    refs = _refs(out)
    top = out["data"]["departments"][0]
    assert top["department_id"] == growth["department_id"]
    assert top["department_name"] == growth["department_name"]
    assert top["growth"] > 0
    assert all(ref in refs for ref in top["refs"])


async def test_people_cost_by_department_defaults_to_previous_period(scenarios):
    growth = _scenario(scenarios, "people_cost_growth")
    out = await _call(people_cost_by_department, {"period": growth["period"]})
    _refs(out)
    assert out["data"]["compare_to"] == growth["compared_to"]


async def test_top_overruns_includes_planted_overruns(scenarios):
    over = _scenario(scenarios, "over_budget")
    both = _scenario(scenarios, "both_problems")
    out = await _call(top_overruns, {"period": over["period"], "n": 3})
    refs = _refs(out)
    rows = out["data"]["overruns"]
    assert len(rows) <= 3
    assert {over["project_id"], both["project_id"]} <= {r["project_id"] for r in rows}
    assert all(r["variance"] > 0 for r in rows)
    assert all(ref in refs for r in rows for ref in r["refs"])
