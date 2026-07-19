"""Tests for the Storyboard public sharing service (Phase 20 — T-256).

The allow-list / permission-filtering logic is pure and always runs; the
enable/disable/rotate lifecycle (slug uniqueness, atomic rotation, 404-on-disable)
is exercised against a live PostgreSQL instance. Requires TEST_DATABASE_URL;
skipped otherwise (CI injects it).
"""

from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from models import Base, Storyboard, User, Workspace
from prompts.storyboard import StoryboardPayload
from schemas.storyboard import (
    StoryboardShareRequest,
)
from services.pipeline import storyboard_public_service as svc
from services.pipeline.storyboard_service import (
    StoryboardNotFoundError,
    StoryboardNotPresentableError,
)

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")

pytestmark_db = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL not set — integration test skipped.",
)

# Long enough to clear the talk_track depth floor while staying a unique,
# searchable sentinel for the redaction assertions below.
_SECRET_TALK = (
    "SECRET-TALK-TRACK that runs deliberately long so it clears the speaker-note "
    "depth floor while remaining a unique searchable sentinel for redaction tests."
)
_SECRET_PAUSE = "SECRET-PAUSE-CUE"
_SECRET_BACKUP = "SECRET-BACKUP-POINT"
_SECRET_APPENDIX = "SECRET-TECHNICAL-APPENDIX"
_SECRET_LAYER_EXCERPT = "SECRET-LAYER-EXCERPT"
_SECRET_MAP_EXCERPT = "SECRET-SOURCEMAP-EXCERPT"

_ARCH_LAYER_KINDS = (
    "client",
    "frontend",
    "api",
    "data",
    "llm",
    "integrations",
    "trust",
    "recovery",
)
_SECTION_TITLES = (
    "Opening Thesis",
    "Product Vision",
    "Product Walkthrough",
    "Technical Architecture",
    "Trust, Security, Reliability",
    "Launch Close",
)


def _full_payload() -> dict:
    """A complete, schema-valid Storyboard payload with marked secret fields."""

    sections = []
    notes: dict[str, dict] = {}
    for i, title in enumerate(_SECTION_TITLES):
        sid = f"s{i}"
        sections.append(
            {
                "id": f"act-{i}",
                "title": title,
                "slides": [
                    {
                        "id": sid,
                        "type": "thesis",
                        "headline": f"Headline {i}",
                        "visible_text": "Visible.",
                        "visual": {"kind": "hero"},
                        "speaker_notes_ref": sid,
                        "sources": ["SPEC", "PLAN"],
                    }
                ],
            }
        )
        notes[sid] = {
            "slide_id": sid,
            "talk_track": _SECRET_TALK,
            "transition": "SECRET-TRANSITION",
            "timing_seconds": 45,
            "pause_cue": _SECRET_PAUSE,
            "demo_cue": "",
            "backup_points": [_SECRET_BACKUP, "Second backup point for Q&A."],
        }
    layers = [
        {
            "id": f"l-{k}",
            "kind": k,
            "label": k.title(),
            "summary": "Plane.",
            "source_refs": [
                {
                    "source": "PLAN",
                    "source_id": "PLAN:arch",
                    "excerpt": _SECRET_LAYER_EXCERPT,
                }
            ],
        }
        for k in _ARCH_LAYER_KINDS
    ]
    return {
        "title": "Public Keynote",
        "theme": {
            # 5 colours: fresh-generation palette floor (audit L16).
            "palette": ["#101418", "#1FB6FF", "#F5A623", "#F5F5F5", "#22CC88"],
            "typography": "Geometric sans",
            "motif": "Indica glassmorphism",
            "transition_style": "Cinematic fade",
            "diagram_style": "Layered planes",
        },
        "sections": sections,
        "diagrams": [{"id": "arch", "type": "architecture_reveal", "layers": layers}],
        "source_map": {
            "claim-1": [
                {
                    "source": "SPEC",
                    "source_id": "SPEC:overview",
                    "excerpt": _SECRET_MAP_EXCERPT,
                }
            ]
        },
        "notes": notes,
        "demo_script_md": "## Demo\n1. Show the editor.\n",
        "technical_appendix_md": _SECRET_APPENDIX,
    }


def _storyboard(**overrides) -> Storyboard:
    """An in-memory Storyboard ORM instance (no session) for pure-function tests."""

    defaults = dict(
        id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        version=1,
        status="ready",
        title="Public Keynote",
        theme="Indica glassmorphism",
        content_json=_full_payload(),
        speaker_notes_md="# Notes\n",
        demo_script_md="## Demo\n",
        technical_appendix_md="## Appendix\n",
        source_map_json={},
        source_stage_version_ids={},
        public_share_slug=None,
        public_share_enabled=False,
        allow_pdf_download=True,
        allow_notes_download=False,
        allow_appendix_download=False,
        allow_source_layer=False,
    )
    defaults.update(overrides)
    sb = Storyboard(**defaults)
    # updated_at is normally a server default; set it for shared_at serialisation.
    from datetime import UTC, datetime

    sb.updated_at = datetime.now(UTC)
    return sb


# ---------------------------------------------------------------------------
# Slug entropy / source
# ---------------------------------------------------------------------------


def test_slug_length_and_alphabet() -> None:
    slugs = {svc.generate_slug() for _ in range(50)}
    assert len(slugs) == 50  # CSPRNG: no collisions across a small sample
    for slug in slugs:
        assert len(slug) >= 10
        assert len(slug) == svc._SLUG_LEN
        assert all(ch in svc._SLUG_ALPHABET for ch in slug)


def test_slug_uses_secrets_module() -> None:
    import inspect

    source = inspect.getsource(svc.generate_slug)
    assert "secrets." in source  # CSPRNG, not random


# ---------------------------------------------------------------------------
# Permission matrix — single source of truth
# ---------------------------------------------------------------------------


def test_default_permissions_downloads() -> None:
    sb = _storyboard()  # defaults: pdf on, rest off
    assert svc.available_public_downloads(sb) == ["pdf", "demo-script"]
    assert svc.is_public_download_allowed(sb, "pdf")
    assert svc.is_public_download_allowed(sb, "demo-script")
    assert not svc.is_public_download_allowed(sb, "notes")
    assert not svc.is_public_download_allowed(sb, "appendix")
    # html / unknown are never public.
    assert not svc.is_public_download_allowed(sb, "html")
    assert not svc.is_public_download_allowed(sb, "anything")


def test_storyboard_public_owner_permissions_filter_downloads() -> None:
    sb = _storyboard(
        allow_pdf_download=True,
        allow_notes_download=True,
        allow_appendix_download=True,
    )
    downloads = svc.available_public_downloads(sb)
    assert downloads == ["pdf", "demo-script", "notes", "appendix"]
    # The downloads list and the per-kind gate agree for every kind.
    for kind in ("pdf", "demo-script", "notes", "appendix"):
        assert svc.is_public_download_allowed(sb, kind) == (kind in downloads)
    # The public view reflects the same set.
    view = svc.build_public_view(sb)
    assert view.downloads == downloads

    # Turn notes + appendix off → they drop from both the gate and the list.
    sb.allow_notes_download = False
    sb.allow_appendix_download = False
    assert svc.available_public_downloads(sb) == ["pdf", "demo-script"]
    assert not svc.is_public_download_allowed(sb, "notes")
    assert not svc.is_public_download_allowed(sb, "appendix")


# ---------------------------------------------------------------------------
# Allow-list public view — schema-valid in both states, no leaks when off
# ---------------------------------------------------------------------------


def test_public_view_top_level_keys_are_allow_listed() -> None:
    view = svc.build_public_view(_storyboard())
    assert set(view.model_dump().keys()) == {
        "title",
        "presentation",
        "permissions",
        "downloads",
        "shared_at",
    }


def test_public_presentation_is_schema_valid_and_hides_private_by_default() -> None:
    sb = _storyboard()  # all private permissions off
    view = svc.build_public_view(sb)
    # The presentation is a structurally complete StoryboardPayload either way.
    StoryboardPayload.model_validate(view.presentation)
    import json

    blob = json.dumps(view.presentation)
    # Private content absent.
    assert _SECRET_TALK not in blob
    assert _SECRET_PAUSE not in blob
    assert _SECRET_BACKUP not in blob
    assert _SECRET_APPENDIX not in blob
    assert _SECRET_LAYER_EXCERPT not in blob
    assert _SECRET_MAP_EXCERPT not in blob
    # Source-attribution skeleton (section-level source_id) hidden too when the
    # source layer is off — only the SPEC/PLAN enum labels remain (required).
    assert "PLAN:arch" not in blob
    assert "SPEC:overview" not in blob
    # Public deck content present.
    assert "Headline 0" in blob
    assert "## Demo" in blob  # demo script is public when shared


def test_public_presentation_reveals_private_when_permissions_on() -> None:
    sb = _storyboard(
        allow_notes_download=True,
        allow_appendix_download=True,
        allow_source_layer=True,
    )
    view = svc.build_public_view(sb)
    StoryboardPayload.model_validate(view.presentation)
    import json

    blob = json.dumps(view.presentation)
    assert _SECRET_TALK in blob
    assert _SECRET_BACKUP in blob
    assert _SECRET_APPENDIX in blob
    assert _SECRET_LAYER_EXCERPT in blob
    assert _SECRET_MAP_EXCERPT in blob
    # Source ids are revealed alongside excerpts when the source layer is on.
    assert "PLAN:arch" in blob
    assert "SPEC:overview" in blob


def test_public_presentation_source_layer_gates_excerpts_independently() -> None:
    # Notes + appendix on, but source layer OFF: excerpts stay hidden.
    sb = _storyboard(
        allow_notes_download=True,
        allow_appendix_download=True,
        allow_source_layer=False,
    )
    view = svc.build_public_view(sb)
    StoryboardPayload.model_validate(view.presentation)
    import json

    blob = json.dumps(view.presentation)
    assert _SECRET_TALK in blob  # notes revealed
    assert _SECRET_APPENDIX in blob  # appendix revealed
    assert _SECRET_LAYER_EXCERPT not in blob  # excerpts still hidden
    assert _SECRET_MAP_EXCERPT not in blob


def test_public_view_never_exposes_forbidden_fields() -> None:
    sb = _storyboard()
    dumped = svc.build_public_view(sb).model_dump()
    blob = str(dumped)
    for forbidden in (
        "user_id",
        "workspace_id",
        "credit_ledger_id",
        "source_stage_version_ids",
    ):
        assert forbidden not in dumped
    # The actual id values never appear either.
    assert str(sb.user_id) not in blob
    assert str(sb.workspace_id) not in blob


# ---------------------------------------------------------------------------
# Lifecycle (real PostgreSQL): enable / disable / rotate / lookup
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db_engine():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def seeded(db_engine):
    """A user + workspace + one ready Storyboard (sharing disabled)."""

    factory = async_sessionmaker(db_engine, expire_on_commit=False)
    user_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    storyboard_id = uuid.uuid4()
    async with factory() as session:
        session.add(
            User(id=user_id, email=f"u-{user_id}@x.com", google_id=str(user_id))
        )
        session.add(
            Workspace(
                id=workspace_id,
                user_id=user_id,
                name="WS",
                problem_statement=(
                    "Build a structured engineering spec generator for teams "
                    "that turns an idea into spec, plan, harness, and tasks."
                ),
                provider="anthropic",
                model="claude-sonnet-4-6",
                status="active",
            )
        )
        session.add(
            Storyboard(
                id=storyboard_id,
                workspace_id=workspace_id,
                user_id=user_id,
                version=1,
                status="ready",
                title="Public Keynote",
                theme="Indica",
                content_json=_full_payload(),
                speaker_notes_md="# Notes\n",
                demo_script_md="## Demo\n",
                technical_appendix_md="## Appendix\n",
                source_map_json={},
                source_stage_version_ids={},
            )
        )
        await session.commit()
    return factory, user_id, storyboard_id


@pytestmark_db
@pytest.mark.asyncio
async def test_enable_defaults_then_toggle(seeded) -> None:
    factory, user_id, sb_id = seeded
    async with factory() as session:
        sb = await svc.enable_share(session, sb_id, user_id, None)
        assert sb.public_share_enabled is True
        assert sb.public_share_slug and len(sb.public_share_slug) >= 10
        # Default permissions: pdf on, rest off.
        assert sb.allow_pdf_download is True
        assert sb.allow_notes_download is False
        assert sb.allow_appendix_download is False
        assert sb.allow_source_layer is False
        first_slug = sb.public_share_slug

    # Toggle permissions without changing the slug (req 4).
    async with factory() as session:
        sb = await svc.enable_share(
            session,
            sb_id,
            user_id,
            StoryboardShareRequest(allow_notes_download=True, allow_source_layer=True),
        )
        assert sb.public_share_slug == first_slug  # slug unchanged
        assert sb.allow_notes_download is True
        assert sb.allow_source_layer is True
        assert sb.allow_appendix_download is False  # untouched


@pytestmark_db
@pytest.mark.asyncio
async def test_storyboard_public_unknown_or_disabled_returns_404(seeded) -> None:
    factory, user_id, sb_id = seeded

    # Unknown slug → None.
    async with factory() as session:
        assert await svc.lookup_shareable(session, "doesnotexist123") is None

    # Enable → resolvable.
    async with factory() as session:
        sb = await svc.enable_share(session, sb_id, user_id, None)
        slug = sb.public_share_slug
    async with factory() as session:
        assert (await svc.lookup_shareable(session, slug)) is not None

    # Disable → lookup returns None (→ 404) but slug preserved.
    async with factory() as session:
        await svc.disable_share(session, sb_id, user_id)
    async with factory() as session:
        assert await svc.lookup_shareable(session, slug) is None
        result = await session.get(Storyboard, sb_id)
        assert result.public_share_slug == slug  # preserved for re-enable


@pytestmark_db
@pytest.mark.asyncio
async def test_rotate_invalidates_old_slug_atomically(seeded) -> None:
    factory, user_id, sb_id = seeded
    async with factory() as session:
        sb = await svc.enable_share(session, sb_id, user_id, None)
        old_slug = sb.public_share_slug

    async with factory() as session:
        sb = await svc.rotate_share(session, sb_id, user_id)
        new_slug = sb.public_share_slug
    assert new_slug != old_slug

    async with factory() as session:
        assert await svc.lookup_shareable(session, old_slug) is None  # old 404s
        assert (await svc.lookup_shareable(session, new_slug)) is not None  # new works


@pytestmark_db
@pytest.mark.asyncio
async def test_enable_non_owner_is_not_found(seeded) -> None:
    factory, _user_id, sb_id = seeded
    async with factory() as session:
        with pytest.raises(StoryboardNotFoundError):
            await svc.enable_share(session, sb_id, uuid.uuid4(), None)


@pytestmark_db
@pytest.mark.asyncio
async def test_enable_non_presentable_rejected(seeded) -> None:
    factory, user_id, sb_id = seeded
    async with factory() as session:
        sb = await session.get(Storyboard, sb_id)
        sb.status = "failed"
        await session.commit()
    async with factory() as session:
        with pytest.raises(StoryboardNotPresentableError):
            await svc.enable_share(session, sb_id, user_id, None)


@pytestmark_db
@pytest.mark.asyncio
async def test_disabled_then_reenable_reuses_slug(seeded) -> None:
    factory, user_id, sb_id = seeded
    async with factory() as session:
        slug = (await svc.enable_share(session, sb_id, user_id, None)).public_share_slug
    async with factory() as session:
        await svc.disable_share(session, sb_id, user_id)
    async with factory() as session:
        sb = await svc.enable_share(session, sb_id, user_id, None)
        assert sb.public_share_slug == slug  # same URL re-enabled
        assert sb.public_share_enabled is True
