"""Deterministic Storyboard quality gate (storyboard output-quality plan P3.5).

Pure, zero-LLM, zero-I/O structural checks over an already schema- and
grounding-valid ``StoryboardPayload``. Pydantic proves the payload's *shape*;
``storyboard_service._validate_payload_against_source`` proves its *grounding*.
This gate proves a floor of *substance and pacing* so a schema-valid but thin or
monotone deck — one slide per act, every slide the same visual, notes that
merely echo the slide text — does not ship as-is on the cheap primary tier.

Design contract:

* **Deterministic and side-effect-free.** ``assess_payload_quality`` is a pure
  function of the payload — same input, same findings — so it never destabilises
  idempotent generation retries and is trivially unit-testable without a DB.
* **Loose by design.** It gates junk, not style. The bounds are generous (a deck
  of 8–24 slides, ≤ 4 per act, ≥ 2 distinct visual kinds); the near-duplication
  test only fires on genuine restatement. A borderline-but-real deck passes.
* **Content-free findings.** Every finding is a structural statement — slide ids,
  slide counts, the six fixed act titles, visual-kind names — never headline,
  visible_text, note, or excerpt text. The caller folds them into a coarse
  ``StoryboardPayloadError('schema', 'quality: …')`` summary that is safe to log
  and to feed the repair prompt (privacy invariant §1.8). No finding contains the
  substrings ``provider`` / ``timeout`` so the failure is never misclassified as a
  transport error by ``_payload_error_type`` (which would skip escalation).

A non-empty result feeds the existing repair loop and, on exhausted repairs, the
one-shot mid-tier escalation in ``_run_storyboard_completion`` — zero new
plumbing, exactly as the plan specifies.
"""

from __future__ import annotations

import re

from prompts.storyboard import StoryboardPayload, StoryboardVisual, visual_has_substance

# Loose pacing bounds. Per-act count is only upper-bounded here (the schema
# already guarantees >= 1 slide/act); the deck total is bounded both ways.
_MAX_SLIDES_PER_ACT = 4
_MIN_TOTAL_SLIDES = 8
_MAX_TOTAL_SLIDES = 24
_MIN_DISTINCT_VISUAL_KINDS = 2

# Near-duplication: Jaccard token overlap at/above this flags a headline that
# restates its visible_text, or a talk track that merely echoes it. Jaccard
# (intersection / union) is symmetric, so a long talk track that legitimately
# *adds* depth around the slide's few words scores low (its extra tokens inflate
# the union) — only a genuine near-copy scores high.
_DUP_JACCARD = 0.7
# Below this token count on the smaller field a Jaccard ratio is noise (two
# two-word strings trivially match), so short fields are exempt from the checks.
_MIN_DUP_TOKENS = 4

# Interior acts whose whole job is product/technical substance: at least one of
# their slides must carry a points/metric descriptor or the act is decorative.
# (The four middle acts; Opening Thesis and Launch Close are framing acts and are
# intentionally exempt.)
_INTERIOR_ACT_TITLES = frozenset(
    {
        "Product Vision",
        "Product Walkthrough",
        "Technical Architecture",
        "Trust, Security, Reliability",
    }
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall((text or "").lower()))


def _near_duplicate(a: str, b: str) -> bool:
    """Whether *a* and *b* are near-duplicate text by symmetric token overlap."""

    ta, tb = _tokens(a), _tokens(b)
    if min(len(ta), len(tb)) < _MIN_DUP_TOKENS:
        return False
    union = ta | tb
    if not union:
        return False
    return len(ta & tb) / len(union) >= _DUP_JACCARD


def _slide_note(payload: StoryboardPayload, slide) -> object | None:
    return payload.notes.get(slide.speaker_notes_ref) or payload.notes.get(slide.id)


def assess_payload_quality(payload: StoryboardPayload) -> list[str]:
    """Return deterministic, content-free quality findings for *payload*.

    An empty list means the deck cleared the gate. A non-empty list is a set of
    short structural problem statements (see module docstring) the caller turns
    into an escalatable quality failure.
    """

    findings: list[str] = []
    total_slides = 0
    visual_kinds: set[str] = set()

    for section in payload.sections:
        slides = section.slides
        total_slides += len(slides)

        if len(slides) > _MAX_SLIDES_PER_ACT:
            findings.append(
                f"act {section.title!r} has {len(slides)} slides "
                f"(max {_MAX_SLIDES_PER_ACT})"
            )

        for slide in slides:
            visual_kinds.add(slide.visual.kind)
            if _near_duplicate(slide.headline, slide.visible_text):
                findings.append(
                    f"slide {slide.id!r} headline restates its visible_text"
                )
            note = _slide_note(payload, slide)
            if note is not None and _near_duplicate(
                note.talk_track, slide.visible_text
            ):
                findings.append(
                    f"slide {slide.id!r} talk track only echoes its visible_text"
                )

        if section.title in _INTERIOR_ACT_TITLES and not any(
            _slide_has_substance(slide.visual) for slide in slides
        ):
            findings.append(
                f"interior act {section.title!r} has no slide with a "
                "points/metric descriptor"
            )

    if not (_MIN_TOTAL_SLIDES <= total_slides <= _MAX_TOTAL_SLIDES):
        findings.append(
            f"deck has {total_slides} slides "
            f"(expected {_MIN_TOTAL_SLIDES}-{_MAX_TOTAL_SLIDES})"
        )

    if len(visual_kinds) < _MIN_DISTINCT_VISUAL_KINDS:
        findings.append(
            f"deck uses {len(visual_kinds)} distinct visual kind(s) "
            f"(min {_MIN_DISTINCT_VISUAL_KINDS})"
        )

    return findings


def _slide_has_substance(visual: StoryboardVisual) -> bool:
    # Single shared definition of "substance" with the P3.4 fresh-generation slide
    # floor in prompts/storyboard.py, so the gate and the floor never drift.
    return visual_has_substance(visual)
