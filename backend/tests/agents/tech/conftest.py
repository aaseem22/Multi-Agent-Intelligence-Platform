"""Tech test fixtures: the GitHub client serves recorded fixture responses (no network)."""

from collections.abc import AsyncIterator

import pytest

from app.integrations import github_client
from app.integrations.github_client import GitHubClient


@pytest.fixture
async def recorded_github() -> AsyncIterator[GitHubClient]:
    previous = github_client._client
    client = GitHubClient(token="", use_cache=False)
    assert client.offline
    github_client.set_github_client(client)
    try:
        yield client
    finally:
        github_client.set_github_client(previous)
        await client.aclose()
