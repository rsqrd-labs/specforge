"""Thin async GitHub REST API wrapper with typed exceptions.

Scope discipline: this module has zero knowledge of business logic,
database, or SpecForge models. It performs only the operations the export
service needs.

Two token modes (Phase 21 — T-268):

- **Installation mode (v2, GitHub App):** the client holds no token. Each
  request resolves a short-lived installation token per call from an injected
  ``InstallationTokenSource`` (the T-267 ``TokenProvider``) keyed by
  ``installation_id``. On a 401 — the token may have rotated under us — the
  token is re-minted **exactly once** and the request retried; a second 401
  raises ``GitHubTokenExpiredError``.
- **Static mode (v1, legacy OAuth):** the client holds a plaintext token passed
  at construction. A 401 raises ``GitHubTokenExpiredError`` immediately (there
  is no installation to re-mint from).

A per-client :class:`GitHubCircuitBreaker` trips after repeated network/5xx/429
failures and raises :class:`GitHubUnavailableError` on subsequent calls, so a
caller can surface "sync paused" instead of hammering a degraded GitHub. Breaker
accounting is additive: it never changes how a single response maps to a typed
error (429 → ``GitHubRateLimitError``, 5xx → ``GitHubAPIError``).

Supported operations: create_repo, get_file_sha, upsert_file,
create_issue, update_issue. Later tasks add branch/PR/GraphQL/checks methods.
"""

from __future__ import annotations

import base64
import logging
import time
from typing import Any, Protocol
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"
_GITHUB_ACCEPT = "application/vnd.github+json"

# Bounded retries for a stale-SHA 409 on a content write (T-276): refetch the
# current SHA and retry, but never loop forever on a persistent conflict.
_UPSERT_MAX_ATTEMPTS = 3

# Bounded timeouts for GitHub REST calls. Unlike the LLM adapters (read=300s for
# streaming), GitHub calls are short request/response round-trips, so the read
# timeout is tight. connect/write/pool follow the project default.
_REQUEST_TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=5.0)
# Bounded connection pool so a burst of export issue-creates cannot exhaust
# sockets against api.github.com.
_CONNECTION_LIMITS = httpx.Limits(max_connections=20, max_keepalive_connections=10)


# ---------------------------------------------------------------------------
# Typed exceptions
# ---------------------------------------------------------------------------


class GitHubNotConnectedError(Exception):
    """No GitHub integration exists for the current user."""


class GitHubRepoExistsError(Exception):
    """The requested repo name is already in use under the user's account."""


class GitHubTokenExpiredError(Exception):
    """GitHub returned 401 — the token is no longer valid.

    In installation mode this is raised only after a single re-mint also
    returns 401. SpecForge never retries with a known-invalid token.
    """


class GitHubRateLimitError(Exception):
    """GitHub returned 429 or a rate-limit primary/secondary signal."""


class GitHubWorkflowsPermissionError(Exception):
    """A write to ``.github/workflows/*`` was refused with 403 (T-276).

    GitHub rejects a CI-workflow write when the App installation lacks the
    ``Workflows: write`` permission. This is a distinct, actionable condition
    (re-approve the App's permissions) — not a generic API error and not a
    rate-limit — so PR-mode export surfaces it as such rather than dead-lettering
    with an opaque 403.
    """


class GitHubUnavailableError(Exception):
    """The circuit breaker is open — GitHub is being treated as unavailable.

    Raised before a request is sent once repeated failures have tripped the
    breaker, so callers surface "sync paused" rather than hammering a degraded
    GitHub. Distinct from a one-off ``GitHubAPIError``.
    """


class GitHubAPIError(Exception):
    """Generic GitHub failure: non-2xx response not covered by the other types."""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"GitHub API error {status}: {message}")
        self.status = status
        self.message = message


# ---------------------------------------------------------------------------
# Token source + circuit breaker
# ---------------------------------------------------------------------------


class InstallationTokenSource(Protocol):
    """Structural type for the T-267 ``TokenProvider``.

    Decouples this module from ``github_app_auth`` (scope discipline) while
    documenting the surface the client depends on.
    """

    async def get(self, installation_id: int) -> str: ...

    async def refresh(self, installation_id: int) -> str: ...


class RateGovernor(Protocol):
    """Structural type for the T-274 per-installation rate governor.

    Decouples this module from ``github_governor`` (scope discipline). When a
    governor is supplied, ``acquire`` reserves budget before each request and
    ``observe`` reads the rate-limit headers off each response — either may raise
    ``GitHubThrottledError`` to requeue the worker job on backpressure.
    """

    async def acquire(self, *, write: bool) -> None: ...

    async def observe(self, response: httpx.Response) -> None: ...


class GitHubCircuitBreaker:
    """Per-client circuit breaker following the T-217 failure-window pattern.

    Counts failures that signal a degraded GitHub (network errors, 5xx, 429).
    When ``failure_threshold`` failures occur within ``window_seconds`` the
    breaker opens and rejects calls with :class:`GitHubUnavailableError` for
    ``cooldown_seconds``, after which it half-opens to allow one trial request;
    a success closes it, a failure re-opens it.

    Default scope is per-client-instance (one export job). Cross-installation
    persistence is the per-installation governor's job (T-274); this breaker
    stops a single job from hammering a degraded GitHub. A monotonic clock is
    used so wall-clock changes cannot wedge the breaker open.
    """

    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        window_seconds: float = 60.0,
        cooldown_seconds: float = 30.0,
    ) -> None:
        self._threshold = failure_threshold
        self._window = window_seconds
        self._cooldown = cooldown_seconds
        self._failures = 0
        self._window_start = 0.0
        self._open_until: float | None = None
        self._half_open = False

    def before_request(self) -> None:
        """Raise GitHubUnavailableError if the breaker is open; else permit."""
        if self._open_until is None:
            return
        now = time.monotonic()
        if now < self._open_until:
            raise GitHubUnavailableError(
                "GitHub is temporarily unavailable (circuit breaker open)"
            )
        # Cooldown elapsed → allow a single half-open trial request.
        self._open_until = None
        self._half_open = True

    def record_success(self) -> None:
        self._failures = 0
        self._window_start = 0.0
        self._open_until = None
        self._half_open = False

    def record_failure(self) -> None:
        now = time.monotonic()
        if self._half_open:
            # The half-open trial failed — re-open immediately.
            self._half_open = False
            self._open_until = now + self._cooldown
            self._failures = 0
            return
        if self._window_start == 0.0 or now - self._window_start > self._window:
            self._window_start = now
            self._failures = 0
        self._failures += 1
        if self._failures >= self._threshold:
            self._open_until = now + self._cooldown
            self._failures = 0


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class GitHubAPIClient:
    """Async wrapper around the GitHub REST API.

    The wrapper accepts a shared ``httpx.AsyncClient`` so callers can reuse a
    connection pool across multiple operations (the export service makes O(N)
    issue creates per push). Exactly one auth source must be supplied: a static
    ``token`` (legacy OAuth) or a ``token_provider`` + ``installation_id``
    (GitHub App).
    """

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        token: str | None = None,
        token_provider: InstallationTokenSource | None = None,
        installation_id: int | None = None,
        breaker: GitHubCircuitBreaker | None = None,
        governor: RateGovernor | None = None,
    ) -> None:
        if token is not None and token_provider is not None:
            raise ValueError(
                "GitHubAPIClient takes either a static token or a token_provider, "
                "not both"
            )
        if token_provider is not None:
            if installation_id is None:
                raise ValueError(
                    "GitHubAPIClient requires installation_id with a token_provider"
                )
        elif token is not None:
            if not token:
                raise ValueError("GitHubAPIClient requires a non-empty token")
        else:
            raise ValueError("GitHubAPIClient requires a token or a token_provider")
        self._token = token
        self._token_provider = token_provider
        self._installation_id = installation_id
        self._client = client
        self._breaker = breaker if breaker is not None else GitHubCircuitBreaker()
        self._governor = governor

    # ----- repo -----

    async def create_repo(self, name: str, private: bool) -> dict[str, Any]:
        """POST /user/repos.

        Returns the full repo JSON on success.
        """
        body = {
            "name": name,
            "private": private,
            "auto_init": False,
            "description": "Generated by SpecForge",
        }
        response = await self._request("POST", "/user/repos", json=body)

        if response.status_code == 201:
            return response.json()

        if response.status_code == 422 and _is_already_exists(response):
            raise GitHubRepoExistsError(
                f"Repository {name!r} already exists in your GitHub account"
            )

        self._raise_for_status(response)
        # _raise_for_status always raises on non-2xx — this is unreachable.
        raise GitHubAPIError(response.status_code, response.text)

    # ----- contents (files) -----

    async def get_file_content(
        self, repo: str, path: str, *, ref: str | None = None
    ) -> tuple[str, str] | None:
        """GET a file's decoded text + blob SHA, or ``None`` on 404 (T-277).

        Used by the non-clobbering ``AGENTS.md`` write to read the current file
        before regenerating its managed block. GitHub returns base64 with
        embedded newlines, so the payload is whitespace-stripped before decoding.
        """
        url = f"/repos/{repo}/contents/{_quote_path(path)}"
        if ref is not None:
            url += f"?ref={quote(ref, safe='')}"
        response = await self._request("GET", url)
        if response.status_code == 404:
            return None
        if response.status_code == 200:
            body = response.json()
            if not isinstance(body, dict):
                raise GitHubAPIError(
                    response.status_code, f"bad contents body for {path}"
                )
            sha = body.get("sha")
            encoded = body.get("content")
            if not isinstance(sha, str) or not isinstance(encoded, str):
                raise GitHubAPIError(
                    response.status_code, f"contents response missing fields for {path}"
                )
            text = base64.b64decode("".join(encoded.split())).decode("utf-8")
            return text, sha
        self._raise_for_status(response)
        return None  # unreachable

    async def get_file_sha(
        self, repo: str, path: str, *, ref: str | None = None
    ) -> str | None:
        """GET /repos/{owner}/{repo}/contents/{path}.

        Returns the blob SHA if the file exists, or ``None`` on 404. ``ref``
        (a branch/tag/SHA) reads the file on that branch — required by PR mode so
        the SHA matches the branch being written, not the default branch.
        """
        url = f"/repos/{repo}/contents/{_quote_path(path)}"
        if ref is not None:
            url += f"?ref={quote(ref, safe='')}"
        response = await self._request("GET", url)
        if response.status_code == 404:
            return None
        if response.status_code == 200:
            body = response.json()
            sha = body.get("sha") if isinstance(body, dict) else None
            if isinstance(sha, str):
                return sha
            raise GitHubAPIError(
                response.status_code,
                f"contents response missing sha for {path}",
            )
        self._raise_for_status(response)
        return None  # unreachable

    async def upsert_file(
        self,
        repo: str,
        path: str,
        content: str,
        sha: str | None,
        commit_message: str,
        *,
        branch: str | None = None,
    ) -> None:
        """PUT /repos/{owner}/{repo}/contents/{path}.

        When ``sha`` is provided this updates an existing file; otherwise it
        creates one. ``branch`` writes on a named branch (PR mode). The content
        is base64-encoded.

        Resilience (T-276):

        - A ``409`` (the blob SHA went stale under a concurrent write) is
          recovered by re-reading the current SHA **on the same branch** and
          retrying, bounded by :data:`_UPSERT_MAX_ATTEMPTS` so a persistent
          conflict cannot loop forever.
        - A ``403`` on a ``.github/workflows/*`` path means the App lacks the
          ``Workflows: write`` permission; it raises
          :class:`GitHubWorkflowsPermissionError` (a distinct, actionable error)
          rather than an opaque API error.
        """
        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
        current_sha = sha
        for attempt in range(1, _UPSERT_MAX_ATTEMPTS + 1):
            body: dict[str, Any] = {
                "message": commit_message,
                "content": encoded,
            }
            if current_sha is not None:
                body["sha"] = current_sha
            if branch is not None:
                body["branch"] = branch

            response = await self._request(
                "PUT",
                f"/repos/{repo}/contents/{_quote_path(path)}",
                json=body,
            )
            if response.status_code in (200, 201):
                return

            # Workflows:write 403 on a CI-workflow path — distinct, actionable.
            if response.status_code == 403 and _is_workflow_path(path):
                raise GitHubWorkflowsPermissionError(
                    "The GitHub App lacks 'Workflows: write' permission required "
                    f"to push {path!r}. Re-approve the App's permissions on GitHub, "
                    "then re-export."
                )

            # Stale-SHA 409: refetch the SHA on the write branch and retry.
            if response.status_code == 409 and attempt < _UPSERT_MAX_ATTEMPTS:
                current_sha = await self.get_file_sha(repo, path, ref=branch)
                continue

            self._raise_for_status(response)
            return  # unreachable — _raise_for_status always raises on non-2xx

    # ----- git refs / branches / pulls (PR mode, T-276) -----

    async def get_ref(self, repo: str, ref: str) -> str:
        """GET /repos/{owner}/{repo}/git/ref/{ref} → the referenced commit SHA.

        ``ref`` is unprefixed, e.g. ``"heads/main"``. Raises ``GitHubAPIError``
        if the ref does not exist (an empty repo has no default branch yet).
        """
        response = await self._request(
            "GET", f"/repos/{repo}/git/ref/{quote(ref, safe='/')}"
        )
        if response.status_code == 200:
            body = response.json()
            obj = body.get("object") if isinstance(body, dict) else None
            sha = obj.get("sha") if isinstance(obj, dict) else None
            if isinstance(sha, str):
                return sha
            raise GitHubAPIError(response.status_code, f"ref {ref} missing object.sha")
        self._raise_for_status(response)
        raise GitHubAPIError(response.status_code, response.text)  # unreachable

    async def create_branch(self, repo: str, branch: str, base_sha: str) -> None:
        """POST /repos/{owner}/{repo}/git/refs — create ``refs/heads/{branch}``.

        Idempotent: a ``422`` ("Reference already exists") on re-export is a
        no-op, so a resumed PR export reuses the same branch instead of failing.
        """
        response = await self._request(
            "POST",
            f"/repos/{repo}/git/refs",
            json={"ref": f"refs/heads/{branch}", "sha": base_sha},
        )
        if response.status_code == 201:
            return
        if response.status_code == 422 and _ref_already_exists(response):
            return  # branch already present — idempotent
        self._raise_for_status(response)

    async def create_pull_request(
        self, repo: str, *, head: str, base: str, title: str, body: str
    ) -> int:
        """POST /repos/{owner}/{repo}/pulls → the new PR number.

        Idempotent under resume: if a PR already exists for ``head`` (a crash
        between create and persisting ``pr_number``), GitHub 422s; we recover the
        existing PR number by listing open pulls for the head branch instead of
        opening a duplicate.
        """
        response = await self._request(
            "POST",
            f"/repos/{repo}/pulls",
            json={"title": title, "head": head, "base": base, "body": body},
        )
        if response.status_code == 201:
            data = response.json()
            number = data.get("number") if isinstance(data, dict) else None
            if isinstance(number, int):
                return number
            raise GitHubAPIError(
                response.status_code, "pull creation response missing 'number'"
            )
        if response.status_code == 422:
            existing = await self.find_open_pull_number(repo, head=head)
            if existing is not None:
                return existing
        self._raise_for_status(response)
        raise GitHubAPIError(response.status_code, response.text)  # unreachable

    async def find_open_pull_number(self, repo: str, *, head: str) -> int | None:
        """GET /repos/{owner}/{repo}/pulls?head=… → an open PR number, or None.

        ``head`` may be a bare branch name or ``owner:branch``; GitHub expects
        the latter, so we pass it through and also match the branch suffix.
        """
        response = await self._request(
            "GET",
            f"/repos/{repo}/pulls?state=open&head={quote(head, safe=':')}",
        )
        if response.status_code != 200:
            return None
        rows = response.json()
        if not isinstance(rows, list):
            return None
        branch = head.split(":", 1)[-1]
        for row in rows:
            if not isinstance(row, dict):
                continue
            ref = (row.get("head") or {}).get("ref") if isinstance(row, dict) else None
            number = row.get("number")
            if isinstance(number, int) and (ref == branch or ref == head):
                return number
        return None

    # ----- issues -----

    async def create_issue(
        self,
        repo: str,
        title: str,
        body: str,
        *,
        labels: tuple[str, ...] | list[str] | None = None,
    ) -> int:
        """POST /repos/{owner}/{repo}/issues. Returns the new issue number.

        ``labels`` (T-277) are attached on creation; GitHub auto-creates any
        label that does not yet exist on the repo, so no separate ensure step is
        needed.
        """
        payload: dict[str, Any] = {"title": title, "body": body}
        if labels:
            payload["labels"] = list(labels)
        response = await self._request(
            "POST",
            f"/repos/{repo}/issues",
            json=payload,
        )
        if response.status_code == 201:
            data = response.json()
            number = data.get("number") if isinstance(data, dict) else None
            if isinstance(number, int):
                return number
            raise GitHubAPIError(
                response.status_code,
                "issue creation succeeded but response missing 'number'",
            )

        self._raise_for_status(response)
        raise GitHubAPIError(response.status_code, response.text)  # unreachable

    async def update_issue(
        self,
        repo: str,
        number: int,
        title: str,
        body: str,
        *,
        labels: tuple[str, ...] | list[str] | None = None,
    ) -> None:
        """PATCH /repos/{owner}/{repo}/issues/{number}."""
        payload: dict[str, Any] = {"title": title, "body": body}
        if labels:
            payload["labels"] = list(labels)
        response = await self._request(
            "PATCH",
            f"/repos/{repo}/issues/{number}",
            json=payload,
        )
        if response.status_code == 200:
            return
        self._raise_for_status(response)

    async def list_issues(
        self,
        repo: str,
        *,
        state: str = "all",
        since: str | None = None,
        max_pages: int = 20,
    ) -> list[dict[str, Any]]:
        """GET /repos/{owner}/{repo}/issues — paginated, for backfill (T-273).

        Returns raw issue rows. NOTE: GitHub's issues endpoint also returns pull
        requests (each carries a ``pull_request`` key); the caller must filter
        those out. ``since`` is an ISO-8601 timestamp to fetch only rows updated
        after the last sync. Pagination is bounded by ``max_pages`` as a safety
        cap.
        """
        issues: list[dict[str, Any]] = []
        for page in range(1, max_pages + 1):
            path = (
                f"/repos/{repo}/issues?state={state}&per_page=100&page={page}"
                "&sort=updated&direction=asc"
            )
            if since:
                path += f"&since={since}"
            response = await self._request("GET", path)
            if response.status_code != 200:
                self._raise_for_status(response)
            batch = response.json()
            if not isinstance(batch, list) or not batch:
                break
            issues.extend(batch)
            if len(batch) < 100:
                break
        return issues

    # ----- internals -----

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> httpx.Response:
        """Send a request, resolving the token per call and applying the breaker.

        A 401 in installation mode re-mints the token once and retries; a second
        401 (or any 401 in static mode) raises ``GitHubTokenExpiredError``.
        """
        return await self._send(method, path, json=json, allow_remint=True)

    async def _send(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None,
        allow_remint: bool,
    ) -> httpx.Response:
        # Breaker first: a tripped breaker rejects before any token resolution
        # or network call, so a degraded GitHub is not hammered.
        self._breaker.before_request()

        # Governor budget reservation (T-274): consume a primary token for every
        # request and a secondary token for content-creating writes. Exhaustion
        # raises GitHubThrottledError → the worker requeues the job (no token is
        # spent and no GitHub call is made).
        if self._governor is not None:
            await self._governor.acquire(write=_is_write_method(method))

        token = await self._resolve_token()
        url = f"{GITHUB_API_BASE}{path}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": _GITHUB_ACCEPT,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "SpecForge/1.0",
        }
        try:
            response = await self._client.request(
                method,
                url,
                headers=headers,
                json=json,
                timeout=_REQUEST_TIMEOUT,
            )
        except httpx.HTTPError as exc:
            # Network/timeout failure counts toward the breaker. The exception
            # class name only — never an interpolated untrusted string.
            self._breaker.record_failure()
            raise GitHubAPIError(0, f"network error: {type(exc).__name__}") from exc

        # 401 is mapped here before anything else so callers cannot accidentally
        # treat it as a generic API error. A 401 means GitHub is up (auth issue,
        # not downtime), so it is a breaker success.
        if response.status_code == 401:
            self._breaker.record_success()
            if allow_remint and self._token_provider is not None:
                await self._token_provider.refresh(self._installation_id)  # type: ignore[arg-type]
                return await self._send(method, path, json=json, allow_remint=False)
            raise GitHubTokenExpiredError(
                "GitHub returned 401; the token is no longer valid"
            )

        # Governor observation (T-274) runs BEFORE breaker accounting so a plain
        # rate-limit 429/403 requeues the job as backpressure rather than tripping
        # the breaker into a false "GitHub unavailable" state. It realigns the
        # budget to GitHub's reported remaining on a healthy response and raises
        # GitHubThrottledError on a rate-limit response.
        if self._governor is not None:
            await self._governor.observe(response)

        # Degraded-GitHub signals trip the breaker; the response is still
        # returned so the calling method maps it to its typed error.
        if response.status_code >= 500 or response.status_code == 429:
            self._breaker.record_failure()
        else:
            self._breaker.record_success()
        return response

    async def _resolve_token(self) -> str:
        """Resolve the bearer token for this request (per-call in App mode)."""
        if self._token_provider is not None:
            return await self._token_provider.get(self._installation_id)  # type: ignore[arg-type]
        assert self._token is not None  # guaranteed by __init__  # nosec B101
        return self._token

    def _raise_for_status(self, response: httpx.Response) -> None:
        status = response.status_code
        if status < 400:
            return

        # 401 is already short-circuited in _request, but guard here too
        # for paranoia in case a subclass bypasses _request.
        if status == 401:
            raise GitHubTokenExpiredError(
                "GitHub returned 401; the stored token is no longer valid"
            )
        if status == 403 and _is_rate_limited(response):
            raise GitHubRateLimitError("GitHub API rate limit reached")
        if status == 429:
            raise GitHubRateLimitError("GitHub API rate limit reached")

        message = _short_error_message(response)
        raise GitHubAPIError(status, message)


def make_github_client(token: str, client: httpx.AsyncClient) -> GitHubAPIClient:
    """Factory for the legacy static-token (v1 OAuth) path.

    Tests inject a custom ``httpx.AsyncClient`` (often with a ``MockTransport``)
    via this entry point so the production call sites can build clients
    against the real ``httpx.AsyncClient`` without modification.
    """
    return GitHubAPIClient(token=token, client=client)


def make_app_github_client(
    token_provider: InstallationTokenSource,
    installation_id: int,
    client: httpx.AsyncClient,
    *,
    breaker: GitHubCircuitBreaker | None = None,
    governor: RateGovernor | None = None,
) -> GitHubAPIClient:
    """Factory for the GitHub App path: per-call installation tokens (T-268).

    The worker (T-269+) builds one client per export job; the token is resolved
    fresh on each request from ``token_provider`` and re-minted once on a 401.
    When a per-installation ``governor`` (T-274) is supplied, every call is
    budgeted and every response is observed for rate-limit headers.
    """
    return GitHubAPIClient(
        client=client,
        token_provider=token_provider,
        installation_id=installation_id,
        breaker=breaker,
        governor=governor,
    )


def make_shared_async_client() -> httpx.AsyncClient:
    """Build the shared httpx client for GitHub calls.

    Bounded timeouts and a bounded connection pool (spec §12 robustness) so a
    slow or degraded GitHub cannot stall the worker or exhaust sockets.
    Production call sites reuse one client across many operations; tests inject
    their own ``MockTransport`` client instead.
    """
    return httpx.AsyncClient(timeout=_REQUEST_TIMEOUT, limits=_CONNECTION_LIMITS)


# ---------------------------------------------------------------------------
# Module helpers
# ---------------------------------------------------------------------------


def _is_write_method(method: str) -> bool:
    """True for content-creating verbs that count against the secondary limit."""
    return method.upper() in {"POST", "PUT", "PATCH", "DELETE"}


def _is_workflow_path(path: str) -> bool:
    """True for a CI-workflow file requiring the App's Workflows:write scope."""
    return path.lstrip("/").startswith(".github/workflows/")


def _ref_already_exists(response: httpx.Response) -> bool:
    """True if a 422 from create-ref means the branch already exists."""
    try:
        body = response.json()
    except ValueError:
        return False
    if not isinstance(body, dict):
        return False
    message = (body.get("message") or "").lower()
    return "already exists" in message or "reference already exists" in message


def _is_already_exists(response: httpx.Response) -> bool:
    """Return True if a 422 response indicates a name collision."""
    try:
        body = response.json()
    except ValueError:
        return False
    if not isinstance(body, dict):
        return False
    errors = body.get("errors") or []
    if isinstance(errors, list):
        for err in errors:
            if isinstance(err, dict):
                msg = (err.get("message") or "").lower()
                if "already exists" in msg or err.get("code") == "already_exists":
                    return True
    message = (body.get("message") or "").lower()
    return "already exists" in message or "name already exists" in message


def _is_rate_limited(response: httpx.Response) -> bool:
    """Distinguish a permission-denied 403 from a rate-limit 403."""
    remaining = response.headers.get("x-ratelimit-remaining")
    if remaining == "0":
        return True
    try:
        body = response.json()
    except ValueError:
        return False
    if not isinstance(body, dict):
        return False
    message = (body.get("message") or "").lower()
    return "rate limit" in message or "abuse" in message or "secondary rate" in message


def _short_error_message(response: httpx.Response) -> str:
    """Extract a concise error message from a GitHub response body."""
    try:
        body = response.json()
    except ValueError:
        return (response.text or "")[:200]
    if isinstance(body, dict):
        message = body.get("message")
        if isinstance(message, str):
            return message[:200]
    return (response.text or "")[:200]


def _quote_path(path: str) -> str:
    """GitHub Contents API accepts paths containing slashes verbatim.

    We strip any leading slash and forbid traversal segments — callers
    should pass repo-relative paths.
    """
    cleaned = path.lstrip("/")
    if ".." in cleaned.split("/"):
        raise ValueError(f"invalid path with traversal segment: {path!r}")
    return cleaned
