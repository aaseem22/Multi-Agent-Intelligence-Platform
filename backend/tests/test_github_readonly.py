"""GitHub access is read-only: the client has no write methods and only ever sends GET."""

import ast
import inspect

import httpx
import pytest

from app.integrations import github_client
from app.integrations.github_client import GitHubClient

WRITE_METHODS = ("post", "put", "patch", "delete")


def test_client_exposes_no_write_methods():
    for name in WRITE_METHODS:
        assert not hasattr(GitHubClient, name), f"GitHubClient must not define {name}()"
    public = {n for n in dir(GitHubClient) if not n.startswith("_")}
    assert not {n for n in public if n.split("_")[0] in WRITE_METHODS}


def test_every_http_call_in_module_is_get():
    """AST scan: any call like `x.<method>(...)` or `x.request("POST", ...)` must be a GET."""
    tree = ast.parse(inspect.getsource(github_client))
    offending: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        attr = node.func.attr
        if attr in WRITE_METHODS or attr in {"request", "stream", "send"}:
            offending.append(f"line {node.lineno}: .{attr}(...)")
        for kw in node.keywords:
            if kw.arg == "method" and not (
                isinstance(kw.value, ast.Constant) and str(kw.value.value).upper() == "GET"
            ):
                offending.append(f"line {node.lineno}: method={ast.unparse(kw.value)}")
    assert not offending, "Non-GET HTTP usage in github_client.py: " + ", ".join(offending)


def test_module_defines_no_write_functions():
    tree = ast.parse(inspect.getsource(github_client))
    names = {
        n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    assert not {n for n in names if n.lstrip("_").split("_")[0] in WRITE_METHODS}


@pytest.fixture
def recording_client():
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        path = request.url.path
        if path.endswith("/repos"):
            return httpx.Response(200, json=[{"full_name": "o/r", "name": "r"}])
        if path == "/repos/o/r":
            return httpx.Response(200, json={"full_name": "o/r", "name": "r"})
        return httpx.Response(200, json=[])

    client = GitHubClient(
        token="test-token", transport=httpx.MockTransport(handler), use_cache=False
    )
    return client, methods


async def test_transport_only_ever_sees_get(recording_client):
    client, methods = recording_client
    try:
        await client.list_owner_repos("o")
        await client.get_repo("o/r")
        await client.list_commits("o/r")
        await client.list_open_issues("o/r")
        await client.list_open_pulls("o/r")
        await client.list_contributors("o/r")
        await client.rate_limit()
    finally:
        await client.aclose()
    assert methods and set(methods) == {"GET"}


async def test_results_carry_api_path_for_evidence(recording_client):
    client, _ = recording_client
    try:
        result = await client.list_open_pulls("o/r")
    finally:
        await client.aclose()
    assert result.path == "/repos/o/r/pulls"
    assert result.source_ref.startswith("github:repos/o/r/pulls?")


def test_offline_fixture_transport_rejects_writes():
    transport = github_client.fixture_transport()
    request = httpx.Request("POST", "https://api.github.com/repos/o/r/issues")
    assert transport.handle_request(request).status_code == 405
