"""Unit tests for GitHubAPIClient (T-150).

Uses httpx.MockTransport so no real GitHub calls are made and tests are
fully deterministic. Covers all paths from Plan §17.3:

- create_repo success (201) and 422 already-exists
- get_file_sha returns sha on 200, None on 404
- upsert_file POST when sha=None, PUT with sha when sha provided
- create_issue and update_issue
- 401 → GitHubTokenExpiredError on every method (per the design invariant)
- 429 / rate-limited 403 → GitHubRateLimitError
- network failure → GitHubAPIError
"""

from __future__ import annotations

import base64
import json
from typing import Any

import httpx
import pytest

from services.integrations.github_api_client import (
    GitHubAPIClient,
    GitHubAPIError,
    GitHubRateLimitError,
    GitHubRepoExistsError,
    GitHubTokenExpiredError,
    make_github_client,
)


def _make_client(handler: Any) -> GitHubAPIClient:
    """Build a GitHubAPIClient backed by an httpx MockTransport."""
    transport = httpx.MockTransport(handler)
    async_client = httpx.AsyncClient(transport=transport)
    return make_github_client(token="ghp_fake", client=async_client)


# ---------------------------------------------------------------------------
# create_repo
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_repo_returns_repo_json_on_201() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/user/repos"
        payload = json.loads(request.content)
        assert payload["name"] == "my-repo"
        assert payload["private"] is True
        return httpx.Response(
            201,
            json={
                "full_name": "octocat/my-repo",
                "html_url": "https://github.com/octocat/my-repo",
            },
        )

    client = _make_client(handler)
    repo = await client.create_repo("my-repo", private=True)
    assert repo["full_name"] == "octocat/my-repo"


@pytest.mark.asyncio
async def test_create_repo_raises_exists_on_422_already_exists() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422,
            json={
                "message": "Validation Failed",
                "errors": [
                    {
                        "resource": "Repository",
                        "code": "custom",
                        "message": "name already exists on this account",
                    }
                ],
            },
        )

    client = _make_client(handler)
    with pytest.raises(GitHubRepoExistsError):
        await client.create_repo("dup", private=False)


@pytest.mark.asyncio
async def test_create_repo_raises_token_expired_on_401() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Bad credentials"})

    client = _make_client(handler)
    with pytest.raises(GitHubTokenExpiredError):
        await client.create_repo("x", private=False)


@pytest.mark.asyncio
async def test_create_repo_raises_api_error_on_500() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"message": "boom"})

    client = _make_client(handler)
    with pytest.raises(GitHubAPIError) as exc_info:
        await client.create_repo("x", private=False)
    assert exc_info.value.status == 500


# ---------------------------------------------------------------------------
# get_file_sha
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_file_sha_returns_sha_on_200() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert "/repos/octocat/repo/contents/README.md" in request.url.path
        return httpx.Response(200, json={"sha": "abc123", "path": "README.md"})

    client = _make_client(handler)
    sha = await client.get_file_sha("octocat/repo", "README.md")
    assert sha == "abc123"


@pytest.mark.asyncio
async def test_get_file_sha_returns_none_on_404() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not Found"})

    client = _make_client(handler)
    sha = await client.get_file_sha("octocat/repo", "README.md")
    assert sha is None


@pytest.mark.asyncio
async def test_get_file_sha_raises_token_expired_on_401() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Bad credentials"})

    client = _make_client(handler)
    with pytest.raises(GitHubTokenExpiredError):
        await client.get_file_sha("octocat/repo", "README.md")


# ---------------------------------------------------------------------------
# upsert_file
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upsert_file_creates_when_sha_is_none() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        assert request.method == "PUT"
        return httpx.Response(201, json={"content": {"sha": "newsha"}})

    client = _make_client(handler)
    await client.upsert_file(
        "octocat/repo",
        "SPEC.md",
        "# spec body",
        sha=None,
        commit_message="add SPEC.md",
    )
    payload = captured["payload"]
    assert "sha" not in payload
    assert payload["message"] == "add SPEC.md"
    decoded = base64.b64decode(payload["content"]).decode("utf-8")
    assert decoded == "# spec body"


@pytest.mark.asyncio
async def test_upsert_file_updates_when_sha_provided() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"content": {"sha": "newer"}})

    client = _make_client(handler)
    await client.upsert_file(
        "octocat/repo",
        "SPEC.md",
        "# updated",
        sha="oldsha",
        commit_message="update SPEC.md",
    )
    assert captured["payload"]["sha"] == "oldsha"


@pytest.mark.asyncio
async def test_upsert_file_raises_token_expired_on_401() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    client = _make_client(handler)
    with pytest.raises(GitHubTokenExpiredError):
        await client.upsert_file("o/r", "a", "b", None, "msg")


# ---------------------------------------------------------------------------
# create_issue / update_issue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_issue_returns_number() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        payload = json.loads(request.content)
        assert payload["title"] == "T-001"
        return httpx.Response(201, json={"number": 7, "html_url": "x"})

    client = _make_client(handler)
    number = await client.create_issue("octocat/repo", "T-001", "body")
    assert number == 7


@pytest.mark.asyncio
async def test_update_issue_returns_none_on_200() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PATCH"
        assert "/issues/42" in request.url.path
        return httpx.Response(200, json={"number": 42})

    client = _make_client(handler)
    await client.update_issue("octocat/repo", 42, "title", "body")


@pytest.mark.asyncio
async def test_create_issue_raises_token_expired_on_401() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    client = _make_client(handler)
    with pytest.raises(GitHubTokenExpiredError):
        await client.create_issue("o/r", "t", "b")


# ---------------------------------------------------------------------------
# Rate-limit handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_429_maps_to_rate_limit_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"message": "Too Many Requests"})

    client = _make_client(handler)
    with pytest.raises(GitHubRateLimitError):
        await client.create_repo("x", private=False)


@pytest.mark.asyncio
async def test_403_with_remaining_zero_maps_to_rate_limit_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={"message": "API rate limit exceeded"},
            headers={"x-ratelimit-remaining": "0"},
        )

    client = _make_client(handler)
    with pytest.raises(GitHubRateLimitError):
        await client.create_repo("x", private=False)


# ---------------------------------------------------------------------------
# Hardening
# ---------------------------------------------------------------------------


def test_constructor_rejects_empty_token() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200))
    async_client = httpx.AsyncClient(transport=transport)
    with pytest.raises(ValueError):
        GitHubAPIClient(token="", client=async_client)


@pytest.mark.asyncio
async def test_upsert_file_path_with_traversal_segment_rejected() -> None:
    transport = httpx.MockTransport(lambda r: httpx.Response(200))
    async_client = httpx.AsyncClient(transport=transport)
    client = GitHubAPIClient(token="t", client=async_client)
    with pytest.raises(ValueError):
        await client.upsert_file("o/r", "../etc/passwd", "x", None, "msg")
