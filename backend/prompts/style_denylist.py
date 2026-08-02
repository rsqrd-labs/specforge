"""Filler/hedge-phrase denylist for generated artifacts (density initiative).

Companion to plan.py's DENYLIST_LAST_REVIEWED (the T-241 deprecated-technology
denylist): same "grep it out" mechanism, a different axis. That list catches
EOL tech; this one catches low-specificity marketing/hedge language that pads
an artifact without adding decision-relevant content — the kind of phrase a
coding-agent consumer gets zero signal from ("robust" tells it nothing an
actual threshold or control would).

Read by two consumers that must not import each other:
- backend/services/pipeline/critic.py imports FILLER_PHRASES directly (same
  process, no constraint) to seed the judge's BannedPhrase examples.
- harness/prompt_eval/graders/quality.py cannot import the backend package
  (it runs from harness/ with no runtime dependency on backend), so it reads
  this file's source as text instead, mirroring the existing
  _read_denylist_review_date() pattern for plan.py's anchor.

FILLER_DENYLIST_LAST_REVIEWED is graded by
prompt_eval.graders.quality.denylist_freshness for staleness, same 12-month
budget as the deprecated-tech anchor.
"""

from __future__ import annotations

FILLER_DENYLIST_LAST_REVIEWED = "2026-08-02"

# Deliberately excludes words that are also legitimate, specific engineering
# vocabulary in context (e.g. "significant", "in order to") — those produce
# too many false positives on genuine NFR/rationale prose to be worth the
# noise. This list targets phrases that are filler in every context.
FILLER_PHRASES: tuple[str, ...] = (
    "robust",
    "seamless",
    "seamlessly",
    "leverage",
    "leveraging",
    "cutting-edge",
    "cutting edge",
    "state-of-the-art",
    "state of the art",
    "world-class",
    "best-in-class",
    "powerful",
    "intuitive",
    "user-friendly",
    "comprehensive solution",
    "it is important to note",
    "needless to say",
    "a variety of",
    "in today's fast-paced",
)
