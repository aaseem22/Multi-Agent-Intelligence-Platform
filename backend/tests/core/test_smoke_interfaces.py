from app.core.base_agent import db_evidence, evidence_result
from app.data.repositories import finance, hr, reference, tech


async def test_repositories_read_seeded_db(seeded_db, scenarios):
    over = next(s for s in scenarios["scenarios"] if s["id"] == "over_budget")
    rows = await finance.budget_vs_actual(over["period"])
    row = next(r for r in rows if r.project_id == over["project_id"])
    assert row.variance > 0
    assert await hr.project_staffing(over["project_id"])
    assert (await tech.get_project_delivery(over["project_id"])) is not None
    assert len(await reference.list_departments()) == 4


def test_evidence_result_outside_run_is_plain_json():
    out = evidence_result({"x": 1}, [db_evidence("budgets:id=1", "a budget")])
    assert '"source_ref": "budgets:id=1"' in out
