"""Tech tools against the seeded test DB, with GitHub served from recorded fixtures."""

import json
from typing import Any

import pytest

from app.agents.tech import tools
from app.agents.tech.card import TECH_CARD

from .helpers import scenario

pytestmark = pytest.mark.usefixtures("seeded_db", "recorded_github")


async def call(tool: Any, args: dict[str, Any]) -> dict[str, Any]:
    return json.loads(await tool.ainvoke(args))


def refs(out: dict[str, Any]) -> list[str]:
    return [e["source_ref"] for e in out["evidence"]]


async def test_list_projects_returns_all_with_refs(scenarios):
    out = await call(tools.list_projects, {})
    projects = out["data"]["projects"]
    assert out["data"]["count"] == len(projects) == 12
    assert {f"projects:id={p['id']}" for p in projects} == set(refs(out))
    at_risk = await call(tools.list_projects, {"status": "at_risk"})
    ids = {p["id"] for p in at_risk["data"]["projects"]}
    assert scenario(scenarios, "understaffed")["project_id"] in ids
    assert scenario(scenarios, "both_problems")["project_id"] in ids


async def test_list_projects_filters_by_department_name():
    out = await call(tools.list_projects, {"department": "Engineering"})
    assert out["data"]["projects"]
    assert {p["department_id"] for p in out["data"]["projects"]} == {1}


async def test_list_projects_unknown_department_is_error():
    out = await call(tools.list_projects, {"department": "Astrology"})
    assert "error" in out


async def test_project_delivery_status_by_id_name_and_repo(scenarios):
    s = scenario(scenarios, "understaffed")
    for key in (str(s["project_id"]), s["project_name"], s["repo_full_name"]):
        out = await call(tools.project_delivery_status, {"project": key})
        assert out["data"]["id"] == s["project_id"]
        assert out["data"]["schedule_status"] == "behind"
        assert out["data"]["days_late"] > 0
        assert refs(out) == [f"projects:id={s['project_id']}"]


async def test_project_delivery_status_unknown_project():
    out = await call(tools.project_delivery_status, {"project": "no-such-project-xyz"})
    assert "error" in out


async def test_behind_schedule_includes_planted_delays(scenarios):
    out = await call(tools.behind_schedule, {})
    ids = [p["id"] for p in out["data"]["projects"]]
    for scenario_id in ("understaffed", "both_problems", "stale_repo"):
        assert scenario(scenarios, scenario_id)["project_id"] in ids
    assert scenario(scenarios, "healthy")["project_id"] not in ids
    days = [p["days_late"] for p in out["data"]["projects"]]
    assert days == sorted(days, reverse=True)


async def test_stale_repos_finds_planted_stale_repo(scenarios):
    s = scenario(scenarios, "stale_repo")
    out = await call(tools.stale_repos, {"days": 60})
    stale = out["data"]["stale_repos"]
    assert [r["repo"] for r in stale] == [s["repo_full_name"]]
    assert stale[0]["project_id"] == s["project_id"]
    assert stale[0]["days_since_push"] > 60
    assert f"projects:id={s['project_id']}" in refs(out)
    assert f"github:repos/{s['repo_full_name']}" in refs(out)
    assert out["data"]["repos_checked"] == 12
    assert not out["data"]["errors"]


async def test_stale_repos_lower_threshold_finds_more():
    out = await call(tools.stale_repos, {"days": 20})
    assert out["data"]["stale_count"] > 1


async def test_repo_activity_active_and_stale(scenarios):
    healthy = scenario(scenarios, "healthy")
    out = await call(tools.repo_activity, {"repo": healthy["repo_full_name"], "since_days": 30})
    data = out["data"]
    assert data["project_id"] == healthy["project_id"]
    assert data["commit_count"] > 0
    assert data["last_commit_date"] is not None
    assert data["days_since_push"] <= 2
    github_refs = [r for r in refs(out) if r.startswith("github:")]
    assert f"github:repos/{healthy['repo_full_name']}" in github_refs
    assert any(r.startswith(f"github:repos/{healthy['repo_full_name']}/commits") for r in refs(out))

    stale = scenario(scenarios, "stale_repo")
    out = await call(tools.repo_activity, {"repo": stale["project_name"], "since_days": 30})
    assert out["data"]["commit_count"] == 0
    assert out["data"]["days_since_push"] > 60


async def test_open_issues_counts_and_refs(scenarios):
    s = scenario(scenarios, "most_open_issues")
    out = await call(tools.open_issues, {"repo": s["repo_full_name"]})
    assert out["data"]["open_issue_count"] > 0
    assert out["data"]["issues"][0]["number"]
    assert f"github:repos/{s['repo_full_name']}/issues?state=open&per_page=100" in refs(out)
    assert f"projects:id={s['project_id']}" in refs(out)


async def test_repos_by_open_issues_ranks_planted_repo_first(scenarios):
    s = scenario(scenarios, "most_open_issues")
    out = await call(tools.repos_by_open_issues, {"limit": 3})
    repos = out["data"]["repos"]
    assert len(repos) == 3
    assert repos[0]["repo"] == s["repo_full_name"]
    counts = [r["open_issue_count"] for r in repos]
    assert counts == sorted(counts, reverse=True)
    assert any(r.startswith(f"github:repos/{s['repo_full_name']}/issues") for r in refs(out))


async def test_open_pulls(scenarios):
    s = scenario(scenarios, "over_budget")
    out = await call(tools.open_pulls, {"repo": s["repo_full_name"]})
    assert out["data"]["open_pull_count"] == 2
    assert f"github:repos/{s['repo_full_name']}/pulls?state=open&per_page=100" in refs(out)


async def test_contributors_marks_not_staffing(scenarios):
    s = scenario(scenarios, "most_open_issues")
    out = await call(tools.contributors, {"repo": s["repo_full_name"].split("/")[1]})
    assert out["data"]["contributors"]
    assert "not staffing" in out["data"]["note"]
    assert any(r.startswith(f"github:repos/{s['repo_full_name']}/contributors") for r in refs(out))


async def test_github_failure_is_tool_error_not_exception(scenarios, recorded_github):
    from app.integrations.github_client import GitHubError

    async def boom(*_: Any, **__: Any) -> Any:
        raise GitHubError("rate limited", status_code=403, path="/repos/x")

    recorded_github.list_open_issues = boom  # type: ignore[method-assign]
    s = scenario(scenarios, "healthy")
    out = await call(tools.open_issues, {"repo": s["repo_full_name"]})
    assert "GitHub request failed" in out["error"]


def test_card_and_tool_names():
    names = {t.name for t in tools.TECH_TOOLS}
    assert {
        "list_projects",
        "project_delivery_status",
        "repo_activity",
        "open_issues",
        "open_pulls",
        "stale_repos",
        "contributors",
    } <= names
    assert TECH_CARD.name == "tech"
    assert all(skill.example_questions for skill in TECH_CARD.skills)
