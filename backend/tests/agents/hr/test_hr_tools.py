"""HR tools against the seeded test database. No LLM involved."""

import json
from datetime import date, timedelta

import pytest

from app.agents.hr import tools
from app.data.periods import today


def scenario(scenarios: dict, scenario_id: str) -> dict:
    return next(s for s in scenarios["scenarios"] if s["id"] == scenario_id)


async def call(tool, **args) -> dict:
    return json.loads(await tool.ainvoke(args))


def refs(output: dict) -> list[str]:
    return [e["source_ref"] for e in output["evidence"]]


# --- get_employee -----------------------------------------------------------------------


async def test_get_employee_by_id(seeded_db, scenarios):
    lead_id = scenario(scenarios, "understaffed")["lead_employee_id"]
    out = await call(tools.get_employee, employee_id=lead_id)
    [employee] = out["data"]["employees"]
    assert employee["id"] == lead_id
    assert employee["full_name"]
    assert employee["department_name"]
    assert refs(out) == [f"employees:id={lead_id}"]


async def test_get_employee_by_github_username(seeded_db, scenarios):
    lead_id = scenario(scenarios, "most_open_issues")["lead_employee_id"]
    out = await call(tools.get_employee, github_username="Fixture-Owner")
    [employee] = out["data"]["employees"]
    assert employee["id"] == lead_id
    assert employee["github_username"] == "fixture-owner"
    assert f"employees:id={lead_id}" in refs(out)


async def test_get_employee_by_name(seeded_db, scenarios):
    lead_id = scenario(scenarios, "healthy")["lead_employee_id"]
    by_id = await call(tools.get_employee, employee_id=lead_id)
    full_name = by_id["data"]["employees"][0]["full_name"]
    out = await call(tools.get_employee, name=full_name.split()[-1].lower())
    assert lead_id in [e["id"] for e in out["data"]["employees"]]
    assert f"employees:id={lead_id}" in refs(out)


async def test_get_employee_not_found_and_bad_input(seeded_db):
    missing = await call(tools.get_employee, employee_id=999_999)
    assert missing["data"]["employees"] == []
    assert missing["evidence"] == []
    assert "error" in await call(tools.get_employee)


# --- project_staffing -------------------------------------------------------------------


async def test_project_staffing_by_id(seeded_db, scenarios):
    s = scenario(scenarios, "over_budget")
    out = await call(tools.project_staffing, project=str(s["project_id"]))
    data = out["data"]
    assert data["project_id"] == s["project_id"]
    assert data["project_name"] == s["project_name"]
    assert data["headcount"] >= 3
    lead = next(a for a in data["allocations"] if a["employee_id"] == s["lead_employee_id"])
    assert lead["role"] == "Project Lead"
    assert f"projects:id={s['project_id']}" in refs(out)
    assert all(f"allocations:id={a['id']}" in refs(out) for a in data["allocations"])


async def test_project_staffing_by_name_and_repo(seeded_db, scenarios):
    s = scenario(scenarios, "understaffed")
    by_name = await call(tools.project_staffing, project=s["project_name"].upper())
    by_repo = await call(tools.project_staffing, project=s["repo_full_name"])
    assert by_name["data"]["project_id"] == by_repo["data"]["project_id"] == s["project_id"]


async def test_project_staffing_unknown_project(seeded_db):
    out = await call(tools.project_staffing, project="no-such-project-xyz")
    assert "error" in out


# --- employee_allocations ---------------------------------------------------------------


async def test_employee_allocations_over_allocated_lead(seeded_db, scenarios):
    s = scenario(scenarios, "understaffed")
    out = await call(tools.employee_allocations, employee_id=s["lead_employee_id"])
    data = out["data"]
    assert data["total_pct"] == s["lead_total_allocation_pct"] > 100
    assert data["over_allocated"] is True
    assert s["project_id"] in [a["project_id"] for a in data["allocations"]]
    assert all(a["project_name"] for a in data["allocations"])
    assert f"employees:id={s['lead_employee_id']}" in refs(out)
    assert all(a["ref"] in refs(out) for a in data["allocations"])


async def test_employee_allocations_unknown_employee(seeded_db):
    assert "error" in await call(tools.employee_allocations, employee_id=999_999)


# --- over_allocated ---------------------------------------------------------------------


async def test_over_allocated_default_threshold(seeded_db, scenarios):
    out = await call(tools.over_allocated)
    data = out["data"]
    assert data["threshold_pct"] == 100
    people = {p["employee_id"]: p for p in data["people"]}
    for scenario_id in ("understaffed", "both_problems", "most_open_issues"):
        lead_id = scenario(scenarios, scenario_id)["lead_employee_id"]
        assert lead_id in people
        assert people[lead_id]["employee_name"]
        assert people[lead_id]["total_pct"] > 100
        assert f"employees:id={lead_id}" in refs(out)
    healthy_lead = scenario(scenarios, "healthy")["lead_employee_id"]
    assert healthy_lead not in people
    totals = [p["total_pct"] for p in data["people"]]
    assert totals == sorted(totals, reverse=True)


async def test_over_allocated_higher_threshold(seeded_db, scenarios):
    out = await call(tools.over_allocated, threshold_pct=175)
    assert all(p["total_pct"] > 175 for p in out["data"]["people"])
    lead_id = scenario(scenarios, "understaffed")["lead_employee_id"]
    assert lead_id in [p["employee_id"] for p in out["data"]["people"]]


# --- leave_overlap ----------------------------------------------------------------------


async def test_leave_overlap_flags_people_away(seeded_db, scenarios):
    s = scenario(scenarios, "understaffed")
    start, end = s["overlapping_leave_window"]
    out = await call(tools.leave_overlap, project=str(s["project_id"]), start=start, end=end)
    data = out["data"]
    lead = next(m for m in data["team"] if m["employee_id"] == s["lead_employee_id"])
    assert lead["away"] is True and lead["leave_ids"]
    assert s["lead_employee_id"] in data["away_employee_ids"]
    assert data["people_away"] == data["team_size"]
    assert data["max_concurrent_away"] >= 2
    for leave_id in lead["leave_ids"]:
        assert f"leave:id={leave_id}" in refs(out)
    assert lead["allocation_ref"] in refs(out)


async def test_leave_overlap_default_window(seeded_db, scenarios):
    s = scenario(scenarios, "both_problems")
    out = await call(tools.leave_overlap, project=s["project_name"])
    window = out["data"]["window"]
    assert window["start"] == str(today())
    assert window["end"] == str(today() + timedelta(days=tools.DEFAULT_LEAVE_WINDOW_DAYS))
    assert s["lead_employee_id"] in out["data"]["away_employee_ids"]


async def test_leave_overlap_healthy_project_in_planted_window(seeded_db, scenarios):
    healthy = scenario(scenarios, "healthy")
    start, end = scenario(scenarios, "understaffed")["overlapping_leave_window"]
    out = await call(tools.leave_overlap, project=str(healthy["project_id"]), start=start, end=end)
    assert out["data"]["people_away"] < out["data"]["team_size"]


@pytest.mark.parametrize(
    ("start", "end"), [("not-a-date", None), (str(date(2026, 5, 2)), str(date(2026, 5, 1)))]
)
async def test_leave_overlap_bad_dates(seeded_db, scenarios, start, end):
    s = scenario(scenarios, "understaffed")
    args = {"project": str(s["project_id"]), "start": start}
    if end:
        args["end"] = end
    assert "error" in await call(tools.leave_overlap, **args)


# --- open_positions ---------------------------------------------------------------------


async def test_open_positions_all(seeded_db, scenarios):
    out = await call(tools.open_positions)
    positions = out["data"]["positions"]
    assert out["data"]["count"] == len(positions) >= 6
    project_ids = {p["project_id"] for p in positions}
    assert scenario(scenarios, "understaffed")["project_id"] in project_ids
    assert scenario(scenarios, "both_problems")["project_id"] in project_ids
    assert all(p["department_name"] and p["days_open"] >= 0 for p in positions)
    assert all(f"open_positions:id={p['id']}" in refs(out) for p in positions)


async def test_open_positions_by_department(seeded_db):
    by_name = await call(tools.open_positions, department="Engineering")
    by_code = await call(tools.open_positions, department="eng")
    assert by_name["data"]["positions"] == by_code["data"]["positions"]
    assert {p["department_name"] for p in by_name["data"]["positions"]} == {"Engineering"}
    assert "error" in await call(tools.open_positions, department="Astrology")


# --- headcount_by_department ------------------------------------------------------------


async def test_headcount_by_department(seeded_db):
    out = await call(tools.headcount_by_department)
    data = out["data"]
    assert len(data["departments"]) == 4
    assert data["total"] == sum(d["headcount"] for d in data["departments"])
    assert {d["department_name"] for d in data["departments"]} == {
        "Engineering",
        "Product",
        "Data",
        "Operations",
    }
    assert all(d["ref"] in refs(out) for d in data["departments"])


async def test_headcount_before_company_existed(seeded_db):
    out = await call(tools.headcount_by_department, as_of="2000-01-01")
    assert out["data"]["total"] == 0
    assert out["evidence"] == []


def test_tool_names_match_spec():
    assert [t.name for t in tools.HR_TOOLS] == [
        "get_employee",
        "project_staffing",
        "employee_allocations",
        "over_allocated",
        "leave_overlap",
        "open_positions",
        "headcount_by_department",
    ]
    assert all(t.description for t in tools.HR_TOOLS)
