"""Web-grounding research enrichment (Brave LLM Context API, issue #12).

This package is a purely *additive*, fail-open enrichment layer over the
four-stage generation pipeline. Every failure or unconfigured path yields an
empty research block and generation proceeds identically to today. Phase 1 ships
only the never-raises HTTP adapter (``brave_client``); it is wired to nothing.
"""

from services.research.brave_client import (
    BraveResult,
    BraveSnippet,
    BraveSource,
    fetch,
)

__all__ = ["BraveResult", "BraveSnippet", "BraveSource", "fetch"]
