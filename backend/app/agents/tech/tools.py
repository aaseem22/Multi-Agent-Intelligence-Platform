"""Read-only Tech tools: project delivery (DB) and repository activity (GitHub, GET only).

Every tool returns `evidence_result(data, evidence)` with `projects:id=N` refs for DB rows and
`github:...` refs for API responses, or `tool_error(...)`. Tools never raise.
"""

import logging
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from langchain_core.tools import BaseTool, tool

from app.core.base_agent import db_evidence, evidence_result, github_evidence, tool_error
from app.core.contracts import Evidence
from app.data.repositories import reference
from app.data.repositories import tech as tech_repo
from app.data.repositories.reference import ProjectRef
from app.data.repositories.tech import ProjectDelivery
from app.integrations.github_client import GitHubError, get_github_client

logger = logging.getLogger(__name__)

MAX_LISTED = 20
STAFFING_NOTE = (
    "GitHub accounts show code activity only. They are not staffing or allocation data; "
    "ask the HR agent who is allocated to the project."
)


class TechLookupError(Exception):
    """A project, repository or department the caller named could not be resolved."""


# --- resolution helpers ---


async def _resolve_department_id(department: str | None) -> int | None:
    if department is None or not str(department).strip():
        return None
    value = str(department).strip()
    if value.isdigit():
        found = await reference.get_department(int(value))
    else:
        found = await reference.find_department(value)
    if found is None:
        names = ", ".join(d.name for d in await reference.list_departments())
        raise TechLookupError(f"Unknown department {department!r}. Known departments: {names}")
    return found.id


async def _resolve_project(project: str | int) -> ProjectRef:
    """Accepts a project id, a project name, a repo full name ("owner/repo") or a repo name."""
    value = str(project).strip()
    if value.removeprefix("projects:id=").isdigit():
        found = await reference.get_project_ref(int(value.removeprefix("projects:id=")))
        if found:
            return found
    if "/" in value:
        found = await reference.get_project_by_repo(value)
        if found:
            return found
    matches = await reference.find_projects(value)
    exact = [
        p
        for p in matches
        if p.name.lower() == value.lower()
        or (p.repo_full_name or "").split("/")[-1].lower() == value.lower()
    ]
    if len(exact) == 1:
        return exact[0]
    if len(matches) == 1:
        return matches[0]
    if matches:
        options = ", ".join(f"{p.name} (id={p.id})" for p in matches)
        raise TechLookupError(f"{project!r} matches several projects: {options}. Pick one id.")
    raise TechLookupError(f"No project or repository matches {project!r}. Try list_projects.")


async def _resolve_repo(repo: str | int) -> ProjectRef:
    project = await _resolve_project(repo)
    if not project.repo_full_name:
        raise TechLookupError(f"Project {project.name} (id={project.id}) has no linked repository.")
    return project


def _project_evidence(project: ProjectRef) -> Evidence:
    return db_evidence(
        project.ref,
        f"Project {project.name} is linked to repo {project.repo_full_name}",
        {"id": project.id, "name": project.name, "repo_full_name": project.repo_full_name},
    )


def _delivery_evidence(p: ProjectDelivery) -> Evidence:
    return db_evidence(
        p.ref,
        f"{p.name}: status {p.status}, schedule {p.schedule_status}, "
        f"planned end {p.planned_end}, expected end {p.expected_end}, {p.days_late} days late",
        _delivery_row(p),
    )


def _delivery_row(p: ProjectDelivery) -> dict[str, Any]:
    return p.model_dump(mode="json")


def _days_since(moment: datetime | None) -> int | None:
    if moment is None:
        return None
    moment = moment if moment.tzinfo else moment.replace(tzinfo=UTC)
    return (datetime.now(UTC) - moment).days


def _iso(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment else None


# --- project delivery (DB) ---


@tool
async def list_projects(status: str | None = None, department: str | None = None) -> str:
    """List projects with delivery fields and schedule status.

    Args:
        status: Optional project status filter, e.g. "active", "at_risk", "completed".
        department: Optional department name, code or id, e.g. "Engineering".
    """
    try:
        department_id = await _resolve_department_id(department)
        rows = await tech_repo.list_projects(status=status, department_id=department_id)
    except TechLookupError as exc:
        return tool_error(str(exc))
    except Exception as exc:
        logger.exception("list_projects failed")
        return tool_error(f"list_projects failed: {exc}")
    if not rows:
        return evidence_result({"projects": [], "count": 0}, [])
    return evidence_result(
        {"projects": [_delivery_row(p) for p in rows], "count": len(rows)},
        [_delivery_evidence(p) for p in rows],
    )


@tool
async def project_delivery_status(project: str) -> str:
    """Planned vs expected delivery dates, schedule status and days late for one project.

    Args:
        project: Project id, project name, or repository full name ("owner/repo").
    """
    try:
        ref = await _resolve_project(project)
        delivery = await tech_repo.get_project_delivery(ref.id)
    except TechLookupError as exc:
        return tool_error(str(exc))
    except Exception as exc:
        logger.exception("project_delivery_status failed")
        return tool_error(f"project_delivery_status failed: {exc}")
    if delivery is None:
        return tool_error(f"Project id={ref.id} not found")
    return evidence_result(_delivery_row(delivery), [_delivery_evidence(delivery)])


@tool
async def behind_schedule(department: str | None = None) -> str:
    """Projects that are behind schedule or overdue, most days late first.

    Args:
        department: Optional department name, code or id.
    """
    try:
        department_id = await _resolve_department_id(department)
        rows = await tech_repo.behind_schedule(department_id=department_id)
    except TechLookupError as exc:
        return tool_error(str(exc))
    except Exception as exc:
        logger.exception("behind_schedule failed")
        return tool_error(f"behind_schedule failed: {exc}")
    return evidence_result(
        {"projects": [_delivery_row(p) for p in rows], "count": len(rows)},
        [_delivery_evidence(p) for p in rows],
    )


# --- repository activity (GitHub, GET only) ---


@tool
async def repo_activity(repo: str, since_days: int = 30) -> str:
    """Commit count and last commit in the last `since_days` days, plus the repo's last push.

    Args:
        repo: Repository full name ("owner/repo"), repo name, project name or project id.
        since_days: Size of the commit window in days (default 30).
    """
    try:
        project = await _resolve_repo(repo)
        client = get_github_client()
        since = datetime.now(UTC) - timedelta(days=max(since_days, 1))
        repo_result = await client.get_repo(project.repo_full_name or "")
        commits = await client.list_commits(project.repo_full_name or "", since=since)
    except TechLookupError as exc:
        return tool_error(str(exc))
    except GitHubError as exc:
        return tool_error(f"GitHub request failed: {exc}", path=exc.path)
    except Exception as exc:
        logger.exception("repo_activity failed")
        return tool_error(f"repo_activity failed: {exc}")

    info = repo_result.items[0]
    last = max(
        (c for c in commits.items if c.date is not None),
        key=lambda c: c.date or datetime.min.replace(tzinfo=UTC),
        default=None,
    )
    data = {
        "project_id": project.id,
        "project_name": project.name,
        "repo": info.full_name,
        "since_days": since_days,
        "commit_count": len(commits.items),
        "last_commit_date": _iso(last.date) if last else None,
        "last_commit_message": last.message if last else None,
        "pushed_at": _iso(info.pushed_at),
        "days_since_push": _days_since(info.pushed_at),
        "archived": info.archived,
        "recent_commits": [
            {"sha": c.sha[:12], "date": _iso(c.date), "message": c.message}
            for c in commits.items[:5]
        ],
    }
    evidence = [
        _project_evidence(project),
        github_evidence(
            repo_result.source_ref,
            f"{info.full_name} last pushed {data['pushed_at']} "
            f"({data['days_since_push']} days ago)",
            {"pushed_at": data["pushed_at"], "archived": info.archived},
        ),
        github_evidence(
            commits.source_ref,
            f"{len(commits.items)} commits to {info.full_name} in the last {since_days} days",
            {"commit_count": len(commits.items), "last_commit_date": data["last_commit_date"]},
        ),
    ]
    return evidence_result(data, evidence)


@tool
async def open_issues(repo: str) -> str:
    """Open GitHub issues (pull requests excluded) for a project repository.

    Args:
        repo: Repository full name ("owner/repo"), repo name, project name or project id.
    """
    try:
        project = await _resolve_repo(repo)
        result = await get_github_client().list_open_issues(project.repo_full_name or "")
    except TechLookupError as exc:
        return tool_error(str(exc))
    except GitHubError as exc:
        return tool_error(f"GitHub request failed: {exc}", path=exc.path)
    except Exception as exc:
        logger.exception("open_issues failed")
        return tool_error(f"open_issues failed: {exc}")
    labels = Counter(label for issue in result.items for label in issue.labels)
    data = {
        "project_id": project.id,
        "project_name": project.name,
        "repo": project.repo_full_name,
        "open_issue_count": len(result.items),
        "labels": dict(labels.most_common()),
        "issues": [
            {
                "number": i.number,
                "title": i.title,
                "labels": i.labels,
                "created_at": _iso(i.created_at),
            }
            for i in result.items[:MAX_LISTED]
        ],
    }
    evidence = [
        _project_evidence(project),
        github_evidence(
            result.source_ref,
            f"{len(result.items)} open issues on {project.repo_full_name}",
            {"open_issue_count": len(result.items)},
        ),
    ]
    return evidence_result(data, evidence)


@tool
async def open_pulls(repo: str) -> str:
    """Open GitHub pull requests for a project repository.

    Args:
        repo: Repository full name ("owner/repo"), repo name, project name or project id.
    """
    try:
        project = await _resolve_repo(repo)
        result = await get_github_client().list_open_pulls(project.repo_full_name or "")
    except TechLookupError as exc:
        return tool_error(str(exc))
    except GitHubError as exc:
        return tool_error(f"GitHub request failed: {exc}", path=exc.path)
    except Exception as exc:
        logger.exception("open_pulls failed")
        return tool_error(f"open_pulls failed: {exc}")
    data = {
        "project_id": project.id,
        "project_name": project.name,
        "repo": project.repo_full_name,
        "open_pull_count": len(result.items),
        "draft_count": sum(1 for p in result.items if p.draft),
        "pulls": [
            {
                "number": p.number,
                "title": p.title,
                "draft": p.draft,
                "created_at": _iso(p.created_at),
                "days_open": _days_since(p.created_at),
            }
            for p in result.items[:MAX_LISTED]
        ],
    }
    evidence = [
        _project_evidence(project),
        github_evidence(
            result.source_ref,
            f"{len(result.items)} open pull requests on {project.repo_full_name}",
            {"open_pull_count": len(result.items)},
        ),
    ]
    return evidence_result(data, evidence)


@tool
async def stale_repos(days: int = 60) -> str:
    """Project repositories with no push in more than `days` days, most stale first.

    Args:
        days: Staleness threshold in days (default 60).
    """
    try:
        projects = [p for p in await reference.list_project_refs() if p.repo_full_name]
    except Exception as exc:
        logger.exception("stale_repos failed")
        return tool_error(f"stale_repos failed: {exc}")
    client = get_github_client()
    stale: list[dict[str, Any]] = []
    evidence: list[Evidence] = []
    errors: list[dict[str, Any]] = []
    for project in projects:
        try:
            result = await client.get_repo(project.repo_full_name or "")
        except GitHubError as exc:
            errors.append({"repo": project.repo_full_name, "error": str(exc)})
            continue
        info = result.items[0]
        age = _days_since(info.pushed_at)
        if age is not None and age <= days:
            continue
        stale.append(
            {
                "project_id": project.id,
                "project_name": project.name,
                "repo": info.full_name,
                "pushed_at": _iso(info.pushed_at),
                "days_since_push": age,
                "archived": info.archived,
            }
        )
        evidence.append(_project_evidence(project))
        evidence.append(
            github_evidence(
                result.source_ref,
                f"{info.full_name} last pushed {_iso(info.pushed_at)} ({age} days ago)",
                {"pushed_at": _iso(info.pushed_at), "days_since_push": age},
            )
        )
    stale.sort(key=lambda r: r["days_since_push"] or 10**6, reverse=True)
    data = {
        "threshold_days": days,
        "repos_checked": len(projects),
        "stale_count": len(stale),
        "stale_repos": stale,
        "errors": errors,
    }
    return evidence_result(data, evidence)


@tool
async def repos_by_open_issues(limit: int = 5) -> str:
    """Rank project repositories by number of open GitHub issues, highest first.

    Args:
        limit: How many repositories to return (default 5).
    """
    try:
        projects = [p for p in await reference.list_project_refs() if p.repo_full_name]
    except Exception as exc:
        logger.exception("repos_by_open_issues failed")
        return tool_error(f"repos_by_open_issues failed: {exc}")
    client = get_github_client()
    ranked: list[tuple[ProjectRef, int, str]] = []
    errors: list[dict[str, Any]] = []
    for project in projects:
        try:
            result = await client.list_open_issues(project.repo_full_name or "")
        except GitHubError as exc:
            errors.append({"repo": project.repo_full_name, "error": str(exc)})
            continue
        ranked.append((project, len(result.items), result.source_ref))
    ranked.sort(key=lambda r: r[1], reverse=True)
    top = ranked[: max(limit, 1)]
    data = {
        "repos": [
            {
                "project_id": p.id,
                "project_name": p.name,
                "repo": p.repo_full_name,
                "open_issue_count": count,
            }
            for p, count, _ in top
        ],
        "repos_checked": len(projects),
        "errors": errors,
    }
    evidence: list[Evidence] = []
    for project, count, source_ref in top:
        evidence.append(_project_evidence(project))
        evidence.append(
            github_evidence(
                source_ref,
                f"{count} open issues on {project.repo_full_name}",
                {"open_issue_count": count},
            )
        )
    return evidence_result(data, evidence)


@tool
async def contributors(repo: str) -> str:
    """GitHub contributor accounts and commit counts for a repository.

    This is code activity only. It does not say who is staffed on the project; ask HR.

    Args:
        repo: Repository full name ("owner/repo"), repo name, project name or project id.
    """
    try:
        project = await _resolve_repo(repo)
        result = await get_github_client().list_contributors(project.repo_full_name or "")
    except TechLookupError as exc:
        return tool_error(str(exc))
    except GitHubError as exc:
        return tool_error(f"GitHub request failed: {exc}", path=exc.path)
    except Exception as exc:
        logger.exception("contributors failed")
        return tool_error(f"contributors failed: {exc}")
    data = {
        "project_id": project.id,
        "project_name": project.name,
        "repo": project.repo_full_name,
        "contributor_count": len(result.items),
        "contributors": [
            {"login": c.login, "contributions": c.contributions} for c in result.items[:MAX_LISTED]
        ],
        "note": STAFFING_NOTE,
    }
    evidence = [
        _project_evidence(project),
        github_evidence(
            result.source_ref,
            f"{len(result.items)} GitHub contributors on {project.repo_full_name}",
            {"contributors": data["contributors"][:5]},
        ),
    ]
    return evidence_result(data, evidence)


TECH_TOOLS: list[BaseTool] = [
    list_projects,
    project_delivery_status,
    behind_schedule,
    repo_activity,
    open_issues,
    open_pulls,
    stale_repos,
    repos_by_open_issues,
    contributors,
]
