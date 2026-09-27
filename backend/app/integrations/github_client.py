"""Read-only GitHub REST client.

Only GET requests exist here: there are no post/put/patch/delete methods and the transport is
only ever called with GET (tests/test_github_readonly.py enforces both). Responses are cached in
the `github_cache` table with a TTL. Without GITHUB_TOKEN the client serves recorded fixtures
from `app/data/seed/fixtures_repos.json`, so the app and tests run offline.
"""

import json
import logging
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Generic, TypeVar
from urllib.parse import urlencode

import httpx
from pydantic import BaseModel

from app.core.config import get_settings
from app.data.repositories import platform

logger = logging.getLogger(__name__)

FIXTURES_PATH = Path(__file__).resolve().parents[1] / "data" / "seed" / "fixtures_repos.json"
T = TypeVar("T")


class GitHubError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None, path: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.path = path


class GitHubRateLimitError(GitHubError):
    pass


class GitHubResponse(BaseModel):
    path: str
    params: dict[str, Any] = {}
    status_code: int
    data: Any
    from_cache: bool = False
    fetched_at: datetime

    @property
    def source_ref(self) -> str:
        query = f"?{urlencode(self.params)}" if self.params else ""
        return f"github:{self.path.lstrip('/')}{query}"


class GitHubResult(BaseModel, Generic[T]):
    """Typed result that carries its API path so tools can build Evidence(source_type='github')."""

    path: str
    source_ref: str
    from_cache: bool
    items: list[T]


class Repo(BaseModel):
    full_name: str
    name: str
    description: str | None = None
    html_url: str | None = None
    private: bool = False
    archived: bool = False
    language: str | None = None
    default_branch: str | None = None
    open_issues_count: int = 0
    pushed_at: datetime | None = None
    updated_at: datetime | None = None


class Commit(BaseModel):
    sha: str
    message: str
    author_name: str | None = None
    author_login: str | None = None
    date: datetime | None = None


class Issue(BaseModel):
    number: int
    title: str
    state: str
    user_login: str | None = None
    labels: list[str] = []
    created_at: datetime | None = None
    updated_at: datetime | None = None


class PullRequest(BaseModel):
    number: int
    title: str
    state: str
    user_login: str | None = None
    draft: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class Contributor(BaseModel):
    login: str
    contributions: int


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


class GitHubClient:
    def __init__(
        self,
        *,
        token: str | None = None,
        base_url: str | None = None,
        cache_ttl_seconds: int | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        use_cache: bool = True,
    ) -> None:
        settings = get_settings()
        self.token = settings.github_token if token is None else token
        self.offline = not self.token and transport is None
        self.cache_ttl = timedelta(
            seconds=settings.github_cache_ttl_seconds
            if cache_ttl_seconds is None
            else cache_ttl_seconds
        )
        self.use_cache = use_cache
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if transport is None and self.offline:
            transport = fixture_transport()
        self._http = httpx.AsyncClient(
            base_url=base_url or settings.github_api_url,
            headers=headers,
            timeout=20.0,
            transport=transport,
        )
        self._rate_limit_reset: datetime | None = None

    async def aclose(self) -> None:
        await self._http.aclose()

    # --- the only network primitive: GET ---

    async def get(self, path: str, params: dict[str, Any] | None = None) -> GitHubResponse:
        params = {k: v for k, v in (params or {}).items() if v is not None}
        key = f"GET {path}?{urlencode(sorted(params.items()))}"
        cached = await self._cached(key) if self.use_cache else None
        if cached and _utc(cached.fetched_at) > datetime.now(UTC) - self.cache_ttl:
            return self._from_cache(path, params, cached)

        if self._rate_limit_reset and datetime.now(UTC) < self._rate_limit_reset:
            if cached:
                return self._from_cache(path, params, cached)
            raise GitHubRateLimitError(
                f"GitHub rate limit exhausted until {self._rate_limit_reset.isoformat()}",
                status_code=403,
                path=path,
            )

        try:
            response = await self._http.get(path, params=params)
        except httpx.HTTPError as exc:
            if cached:
                return self._from_cache(path, params, cached)
            raise GitHubError(f"GitHub request failed: {exc}", path=path) from exc

        self._track_rate_limit(response)
        if (
            response.status_code in (403, 429)
            and response.headers.get("x-ratelimit-remaining") == "0"
        ):
            if cached:
                return self._from_cache(path, params, cached)
            raise GitHubRateLimitError("GitHub rate limit exceeded", status_code=403, path=path)
        if response.status_code >= 400:
            raise GitHubError(
                f"GitHub returned {response.status_code} for {path}",
                status_code=response.status_code,
                path=path,
            )

        data = response.json() if response.content else None
        fetched_at = datetime.now(UTC)
        if self.use_cache:
            await platform.put_github_cache(key, response.status_code, data, fetched_at)
        return GitHubResponse(
            path=path,
            params=params,
            status_code=response.status_code,
            data=data,
            fetched_at=fetched_at,
        )

    async def _cached(self, key: str) -> Any:
        try:
            return await platform.get_github_cache(key)
        except Exception as exc:  # cache table missing or DB unavailable: go to the network
            logger.debug("GitHub cache unavailable: %s", exc)
            return None

    @staticmethod
    def _from_cache(path: str, params: dict[str, Any], cached: Any) -> GitHubResponse:
        return GitHubResponse(
            path=path,
            params=params,
            status_code=cached.status_code,
            data=cached.body,
            from_cache=True,
            fetched_at=_utc(cached.fetched_at),
        )

    def _track_rate_limit(self, response: httpx.Response) -> None:
        remaining = response.headers.get("x-ratelimit-remaining")
        reset = response.headers.get("x-ratelimit-reset")
        if remaining == "0" and reset and reset.isdigit():
            self._rate_limit_reset = datetime.fromtimestamp(int(reset), UTC)
            logger.warning("GitHub rate limit reached; resets at %s", self._rate_limit_reset)

    # --- typed convenience reads ---

    async def list_owner_repos(self, owner: str, limit: int = 100) -> GitHubResult[Repo]:
        path = f"/users/{owner}/repos"
        response = await self.get(path, {"per_page": min(limit, 100), "sort": "pushed"})
        return self._result(response, [Repo.model_validate(r) for r in response.data or []])

    async def get_repo(self, full_name: str) -> GitHubResult[Repo]:
        response = await self.get(f"/repos/{full_name}")
        return self._result(response, [Repo.model_validate(response.data)])

    async def list_commits(
        self, full_name: str, since: datetime | None = None, limit: int = 100
    ) -> GitHubResult[Commit]:
        params = {"per_page": min(limit, 100), "since": since.isoformat() if since else None}
        response = await self.get(f"/repos/{full_name}/commits", params)
        commits = [
            Commit(
                sha=c["sha"],
                message=(c.get("commit", {}).get("message") or "").splitlines()[0][:200]
                if c.get("commit", {}).get("message")
                else "",
                author_name=(c.get("commit", {}).get("author") or {}).get("name"),
                author_login=(c.get("author") or {}).get("login"),
                date=(c.get("commit", {}).get("author") or {}).get("date"),
            )
            for c in response.data or []
        ]
        return self._result(response, commits)

    async def list_open_issues(self, full_name: str, limit: int = 100) -> GitHubResult[Issue]:
        response = await self.get(
            f"/repos/{full_name}/issues", {"state": "open", "per_page": min(limit, 100)}
        )
        issues = [
            Issue(
                number=i["number"],
                title=i["title"],
                state=i["state"],
                user_login=(i.get("user") or {}).get("login"),
                labels=[label["name"] for label in i.get("labels", []) if isinstance(label, dict)],
                created_at=i.get("created_at"),
                updated_at=i.get("updated_at"),
            )
            for i in response.data or []
            if "pull_request" not in i
        ]
        return self._result(response, issues)

    async def list_open_pulls(self, full_name: str, limit: int = 100) -> GitHubResult[PullRequest]:
        response = await self.get(
            f"/repos/{full_name}/pulls", {"state": "open", "per_page": min(limit, 100)}
        )
        pulls = [
            PullRequest(
                number=p["number"],
                title=p["title"],
                state=p["state"],
                user_login=(p.get("user") or {}).get("login"),
                draft=bool(p.get("draft")),
                created_at=p.get("created_at"),
                updated_at=p.get("updated_at"),
            )
            for p in response.data or []
        ]
        return self._result(response, pulls)

    async def list_contributors(
        self, full_name: str, limit: int = 100
    ) -> GitHubResult[Contributor]:
        response = await self.get(f"/repos/{full_name}/contributors", {"per_page": min(limit, 100)})
        contributors = [
            Contributor(login=c["login"], contributions=c.get("contributions", 0))
            for c in response.data or []
            if c.get("login")
        ]
        return self._result(response, contributors)

    async def rate_limit(self) -> GitHubResponse:
        return await self.get("/rate_limit")

    @staticmethod
    def _result(response: GitHubResponse, items: list[Any]) -> GitHubResult[Any]:
        return GitHubResult(
            path=response.path,
            source_ref=response.source_ref,
            from_cache=response.from_cache,
            items=items,
        )


# --- offline fixtures ---


@lru_cache
def load_fixtures() -> dict[str, Any]:
    return json.loads(FIXTURES_PATH.read_text())


def _days_ago(days: float) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).replace(microsecond=0).isoformat()


def _materialise(value: Any) -> Any:
    """Turn `*_days_ago` numbers in fixtures into ISO timestamps relative to now."""
    if isinstance(value, list):
        return [_materialise(v) for v in value]
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if key.endswith("_days_ago") and isinstance(item, int | float):
                out[key.removesuffix("_days_ago")] = _days_ago(item)
            else:
                out[key] = _materialise(item)
        return out
    return value


def fixture_transport() -> httpx.MockTransport:
    """GET-only transport that answers from recorded fixtures."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method != "GET":
            return httpx.Response(405, json={"message": "read-only fixtures"})
        fixtures = load_fixtures()
        repos = {r["repo"]["full_name"].lower(): r for r in fixtures["repos"]}
        parts = [p for p in request.url.path.split("/") if p]
        if parts == ["rate_limit"]:
            return httpx.Response(200, json={"resources": {"core": {"limit": 0, "remaining": 0}}})
        if len(parts) == 3 and parts[0] in ("users", "orgs") and parts[2] == "repos":
            owned = [
                r["repo"]
                for r in fixtures["repos"]
                if r["repo"]["full_name"].split("/")[0].lower() == parts[1].lower()
            ]
            return httpx.Response(200, json=_materialise(owned))
        if len(parts) >= 3 and parts[0] == "repos":
            entry = repos.get(f"{parts[1]}/{parts[2]}".lower())
            if entry is None:
                return httpx.Response(404, json={"message": "Not Found"})
            if len(parts) == 3:
                return httpx.Response(200, json=_materialise(entry["repo"]))
            resource = parts[3]
            if resource in ("commits", "issues", "pulls", "contributors"):
                data = _materialise(entry.get(resource, []))
                since = request.url.params.get("since")
                if resource == "commits" and since:
                    cutoff = datetime.fromisoformat(since)
                    data = [
                        c
                        for c in data
                        if datetime.fromisoformat(c["commit"]["author"]["date"]) >= _utc(cutoff)
                    ]
                return httpx.Response(200, json=data)
        return httpx.Response(404, json={"message": "Not Found"})

    return httpx.MockTransport(handler)


_client: GitHubClient | None = None


def get_github_client() -> GitHubClient:
    global _client
    if _client is None:
        _client = GitHubClient()
    return _client


def set_github_client(client: GitHubClient | None) -> None:
    """Swap the shared client (tests)."""
    global _client
    _client = client
