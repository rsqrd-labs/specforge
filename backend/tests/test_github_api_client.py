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
    GitHubRepoCreationPermissionError,
    GitHubRepoExistsError,
    GitHubTokenExpiredError,
    make_github_client,
)


def _make_client(handler: Any) -> GitHubAPIClient:
    """Build a GitHubAPIClient backed by an httpx MockTransport."""
    transport = httpx.MockTransport(handler)
    async_client = httpx.AsyncClient(transport=transport)
    return make_github_client(token="ghp_fake", client=async_client)


@pytest.mark.asyncio
async def test_list_issues_url_encodes_offset_cursor() -> None:
    cursor = "2026-07-15T18:31:53+00:00"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/octo/app/issues"
        assert request.url.params["since"] == cursor
        assert "%2B00%3A00" in str(request.url)
        return httpx.Response(
            200,
            json=[
                {
                    "number": 16,
                    "state": "closed",
                    "updated_at": "2026-07-15T18:58:58Z",
                }
            ],
        )

    client = _make_client(handler)
    issues = await client.list_issues("octo/app", since=cursor)

    assert issues[0]["number"] == 16
    await client._client.aclose()


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


@pytest.mark.asyncio
async def test_create_repo_raises_permission_error_on_non_rate_limited_403() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "Resource not accessible"})

    client = _make_client(handler)
    with pytest.raises(GitHubRepoCreationPermissionError):
        await client.create_repo("x", private=False)


# ---------------------------------------------------------------------------
# create_org_repo
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_org_repo_returns_repo_json_on_201() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/orgs/octo-org/repos"
        payload = json.loads(request.content)
        assert payload["name"] == "my-repo"
        assert payload["private"] is True
        return httpx.Response(
            201,
            json={
                "full_name": "octo-org/my-repo",
                "html_url": "https://github.com/octo-org/my-repo",
            },
        )

    client = _make_client(handler)
    repo = await client.create_org_repo("octo-org", "my-repo", private=True)
    assert repo["full_name"] == "octo-org/my-repo"


@pytest.mark.asyncio
async def test_create_org_repo_raises_exists_on_422_already_exists() -> None:
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
        await client.create_org_repo("octo-org", "dup", private=False)


@pytest.mark.asyncio
async def test_create_org_repo_raises_permission_error_on_non_rate_limited_403() -> (
    None
):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "Resource not accessible"})

    client = _make_client(handler)
    with pytest.raises(GitHubRepoCreationPermissionError):
        await client.create_org_repo("octo-org", "x", private=False)


# ---------------------------------------------------------------------------
# get_repo
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_repo_returns_json_on_200() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/repos/octo-org/my-repo"
        return httpx.Response(
            200,
            json={"full_name": "octo-org/my-repo", "id": 42},
        )

    client = _make_client(handler)
    repo = await client.get_repo("octo-org/my-repo")
    assert repo is not None
    assert repo["id"] == 42


@pytest.mark.asyncio
async def test_get_repo_returns_none_on_404() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not Found"})

    client = _make_client(handler)
    assert await client.get_repo("octo-org/missing") is None


@pytest.mark.asyncio
async def test_get_repo_ignores_the_all_false_permissions_block() -> None:
    """Under an installation token GitHub fills the repo's `permissions` block
    with all-false values even for fully writable repos (verified live), so
    get_repo must NOT treat it as an access signal — grant checking is the
    export service's job (`_resolve_existing_repo`)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "full_name": "octo-org/my-repo",
                "id": 42,
                "permissions": {"admin": False, "push": False, "pull": False},
            },
        )

    client = _make_client(handler)
    repo = await client.get_repo("octo-org/my-repo")
    assert repo is not None
    assert repo["id"] == 42


# ---------------------------------------------------------------------------
# list_installation_repositories
# ---------------------------------------------------------------------------


def _repo_row(number: int, **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": number,
        "name": f"repo-{number}",
        "full_name": f"octo/repo-{number}",
        "private": False,
        "html_url": f"https://github.com/octo/repo-{number}",
    }
    row.update(overrides)
    return row


@pytest.mark.asyncio
async def test_list_installation_repositories_single_page() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/installation/repositories"
        assert request.url.params["page"] == "1"
        return httpx.Response(
            200,
            json={
                "total_count": 2,
                "repositories": [_repo_row(1), _repo_row(2)],
            },
        )

    client = _make_client(handler)
    repos, truncated = await client.list_installation_repositories()
    assert [r["name"] for r in repos] == ["repo-1", "repo-2"]
    assert truncated is False


@pytest.mark.asyncio
async def test_list_installation_repositories_paginates_until_total_count() -> None:
    pages_served: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        pages_served.append(page)
        if page == 1:
            rows = [_repo_row(n) for n in range(1, 101)]
        else:
            rows = [_repo_row(n) for n in range(101, 151)]
        return httpx.Response(200, json={"total_count": 150, "repositories": rows})

    client = _make_client(handler)
    repos, truncated = await client.list_installation_repositories()
    assert pages_served == [1, 2]
    assert len(repos) == 150
    assert truncated is False


@pytest.mark.asyncio
async def test_list_installation_repositories_truncates_beyond_page_cap() -> None:
    """More repos than max_pages×100 → the exact truncated flag comes from
    total_count, and paging stops at the cap instead of walking every page."""
    pages_served: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        pages_served.append(page)
        start = (page - 1) * 100 + 1
        rows = [_repo_row(n) for n in range(start, start + 100)]
        return httpx.Response(200, json={"total_count": 350, "repositories": rows})

    client = _make_client(handler)
    repos, truncated = await client.list_installation_repositories(max_pages=2)
    assert pages_served == [1, 2]
    assert len(repos) == 200
    assert truncated is True


@pytest.mark.asyncio
async def test_list_installation_repositories_exact_page_multiple_not_truncated() -> (
    None
):
    """Exactly max_pages×100 repos must NOT be reported truncated (the naive
    full-last-page heuristic false-positives here; total_count is exact)."""

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params["page"])
        start = (page - 1) * 100 + 1
        rows = [_repo_row(n) for n in range(start, start + 100)]
        return httpx.Response(200, json={"total_count": 200, "repositories": rows})

    client = _make_client(handler)
    repos, truncated = await client.list_installation_repositories(max_pages=2)
    assert len(repos) == 200
    assert truncated is False


@pytest.mark.asyncio
async def test_list_installation_repositories_filters_unusable_rows() -> None:
    """Archived/disabled repos are dropped (the export can never write to
    them) without inflating `truncated`. The `permissions` block must NOT be
    consulted: under an installation token GitHub returns it all-false even
    for writable repos (verified live), so filtering on it drops everything."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "total_count": 4,
                "repositories": [
                    _repo_row(1),
                    _repo_row(2, archived=True),
                    _repo_row(3, disabled=True),
                    _repo_row(
                        4,
                        permissions={"admin": False, "push": False, "pull": False},
                    ),
                ],
            },
        )

    client = _make_client(handler)
    repos, truncated = await client.list_installation_repositories()
    assert [r["id"] for r in repos] == [1, 4]
    assert truncated is False


@pytest.mark.asyncio
async def test_list_installation_repositories_raises_on_error_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"message": "boom"})

    client = _make_client(handler)
    with pytest.raises(GitHubAPIError):
        await client.list_installation_repositories()


@pytest.mark.asyncio
async def test_list_installation_repositories_raises_on_malformed_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=["not", "a", "dict"])

    client = _make_client(handler)
    with pytest.raises(GitHubAPIError):
        await client.list_installation_repositories()


@pytest.mark.asyncio
async def test_list_installation_repositories_rate_limit_maps_to_typed_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            headers={"x-ratelimit-remaining": "0"},
            json={"message": "API rate limit exceeded"},
        )

    client = _make_client(handler)
    with pytest.raises(GitHubRateLimitError):
        await client.list_installation_repositories()


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
