"""Unit tests for the public share service (T-USE-09 / T-168).

These tests focus on the slug alphabet, the secrets-module usage, the
allow-list response shape (no leakage), and the lifecycle behaviour
(`enable` rejects non-finalised workspaces; `disable` keeps the slug;
`rotate` allocates a new one). DB-level integration is covered via the
service's interaction with an in-memory fake session.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from services.sharing import public_share_service as share


def test_alphabet_excludes_ambiguous_characters() -> None:
    # 0, o, 1, l, i must never appear in a slug or the alphabet itself.
    for forbidden in "01loiLI":
        assert forbidden not in share.ALPHABET, (
            f"Slug alphabet must not contain {forbidden!r}. "
            "Plan §18.3 mandates the unambiguous 31-character set."
        )
    assert len(share.ALPHABET) == 31, "Expected 31-character alphabet."


def test_generate_slug_uses_secrets_module() -> None:
    # Source-level assertion: secrets must be imported and used; random must not.
    src = inspect.getsource(share)
    assert "import secrets" in src
    assert "secrets.choice" in src
    assert (
        "import random" not in src
    ), "random.* is predictable. Slug generation must use secrets.* only."


def test_generate_slug_returns_only_alphabet_chars() -> None:
    for _ in range(2_000):
        slug = share._generate_slug()
        assert len(slug) == share.SLUG_LEN
        assert all(ch in share.ALPHABET for ch in slug)


# ---------------------------------------------------------------------------
# In-memory fake session covering just what the service touches.
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, row: Any) -> None:
        self._row = row

    def scalar_one_or_none(self) -> Any:
        return self._row

    def scalars(self):  # noqa: ANN201 — duck-type
        return iter(self._row or [])

    def __iter__(self):  # noqa: ANN204 — support direct row iteration
        # derive_coverage_summaries iterates the result set directly.
        # None → empty iterator (no eval data); list → iter(list).
        if self._row is None:
            return iter([])
        return iter(self._row)


class _FakeDB:
    """Minimal AsyncSession stand-in. Routes SELECTs by inspecting the where()."""

    def __init__(self, workspace: Any, stages: list[Any]) -> None:
        self.workspace = workspace
        self.stages = stages
        self.committed = 0

    async def execute(self, statement: Any) -> _FakeResult:
        # Crude but reliable: stringify the compiled select and decide based
        # on which table it targets. Tests don't need real SQL semantics.
        text = str(statement)
        # T-USE-13: the coverage-summary query joins eval_results.
        # Return None so the chip stays hidden in the test fixtures.
        if "eval_results" in text:
            return _FakeResult(None)
        if "workspaces" in text and "stages" not in text:
            return _FakeResult(self.workspace)
        return _FakeResult(self.stages)

    async def commit(self) -> None:
        self.committed += 1

    async def rollback(self) -> None:
        pass


def _make_workspace(**overrides: Any) -> Any:
    base = SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        name="My Workspace",
        provider="anthropic",
        public_share_slug=None,
        public_share_enabled=False,
        public_shared_at=None,
        updated_at=datetime.now(timezone.utc),
    )
    for k, v in overrides.items():
        setattr(base, k, v)
    return base


def _make_stage(stage_type: str, status: str = "finalised", content: str = "x") -> Any:
    return SimpleNamespace(type=stage_type, status=status, content=content)


def _all_finalised_stages() -> list[Any]:
    return [_make_stage(t) for t in ("spec", "plan", "harness", "tasks")]


@pytest.mark.asyncio
async def test_enable_rejects_non_finalised_workspace() -> None:
    workspace = _make_workspace()
    stages = [_make_stage("spec"), _make_stage("plan", status="draft")]
    db = _FakeDB(workspace, stages)
    with pytest.raises(share.WorkspaceNotFinalisedError):
        await share.enable(workspace.id, db)


@pytest.mark.asyncio
async def test_enable_assigns_slug_and_flips_flag() -> None:
    workspace = _make_workspace()
    db = _FakeDB(workspace, _all_finalised_stages())
    slug = await share.enable(workspace.id, db)
    assert slug == workspace.public_share_slug
    assert workspace.public_share_enabled is True
    assert workspace.public_shared_at is not None
    assert all(ch in share.ALPHABET for ch in slug)


@pytest.mark.asyncio
async def test_enable_is_idempotent_for_existing_slug() -> None:
    existing = "abcxyz"
    workspace = _make_workspace(
        public_share_slug=existing,
        public_share_enabled=False,
    )
    db = _FakeDB(workspace, _all_finalised_stages())
    slug = await share.enable(workspace.id, db)
    assert slug == existing
    assert workspace.public_share_enabled is True


@pytest.mark.asyncio
async def test_disable_keeps_slug_for_reuse() -> None:
    workspace = _make_workspace(
        public_share_slug="abcxyz",
        public_share_enabled=True,
    )
    db = _FakeDB(workspace, _all_finalised_stages())
    await share.disable(workspace.id, db)
    assert workspace.public_share_enabled is False
    assert workspace.public_share_slug == "abcxyz"


@pytest.mark.asyncio
async def test_rotate_generates_new_slug() -> None:
    workspace = _make_workspace(
        public_share_slug="oldddd",
        public_share_enabled=True,
    )
    db = _FakeDB(workspace, _all_finalised_stages())
    new_slug = await share.rotate(workspace.id, db)
    assert new_slug != "oldddd"
    assert workspace.public_share_slug == new_slug


@pytest.mark.asyncio
async def test_build_public_view_returns_none_for_disabled_share() -> None:
    # The service query filters on `public_share_enabled IS TRUE`; a disabled
    # row simply returns no result. We model that by handing the fake DB
    # no workspace row at all.
    db = _FakeDB(None, _all_finalised_stages())
    view = await share.build_public_view("abcxyz", db)
    assert view is None


@pytest.mark.asyncio
async def test_build_public_view_rejects_unknown_slug() -> None:
    db = _FakeDB(None, [])
    assert await share.build_public_view("unknwn", db) is None


@pytest.mark.asyncio
async def test_build_public_view_rejects_slug_with_forbidden_chars() -> None:
    # `1`/`l`/`o` cannot appear in a real slug, so the service short-circuits.
    db = _FakeDB(None, [])
    assert await share.build_public_view("abc1de", db) is None
    assert await share.build_public_view("abcloi", db) is None


@pytest.mark.asyncio
async def test_build_public_view_allow_list_contains_only_safe_keys() -> None:
    workspace = _make_workspace(
        public_share_slug="abcxyz",
        public_share_enabled=True,
        public_shared_at=datetime.now(timezone.utc),
    )
    db = _FakeDB(workspace, _all_finalised_stages())
    view = await share.build_public_view("abcxyz", db)
    assert view is not None
    body = view.model_dump()
    allowed = {
        "name",
        "provider_label",
        "stages",
        "coverage_summary",
        "eval_summary",
        "shared_at",
    }
    assert set(body.keys()) == allowed
    # Leakage guard: none of these private fields may appear.
    for forbidden in (
        "user_id",
        "email",
        "google_id",
        "credit_balance",
        "problem_statement",
        "clarification_qa",
        "public_share_slug",
    ):
        assert (
            forbidden not in body
        ), f"Private field {forbidden!r} leaked into public response."
