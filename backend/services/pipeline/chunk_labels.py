"""Human-readable names for generation chunks, consistent across every stage.

Chunk keys (``product-scope``, ``task-foundation-blocks``, ``demo-harness-files``)
are internal routing identifiers. They leak into the user-facing resume offer —
"2 of 3 sections generated … still missing: validation-risk" — where they read as
jargon, differ in style between stages (``harness-contract`` vs ``task-overview``
vs ``demo-full``), and name nothing the user can find in their document.

This is the single place that maps a chunk to what a person would call it, so all
four stages and both modes describe their progress the same way. It lives in its
own module rather than in ``stage_manager`` because ``generation_runs`` builds the
gate payload and ``stage_manager`` imports ``generation_runs`` — putting the map
in either one would close an import cycle.

Falling back to a title-cased key rather than raising is deliberate: a chunk plan
is data that can outlive a code change (it is persisted on the run row), so an
unmapped key must still render as something sane instead of breaking the resume
offer that is the whole point of storing it.
"""

from __future__ import annotations

# Keyed by (stage_type, chunk_key). The stage is part of the key because the
# single-pass modes share the literal chunk key ``demo-full`` across spec, plan
# and tasks, and "the complete Spec" is a very different sentence from "the
# complete Task list".
_CHUNK_LABELS: dict[tuple[str, str], str] = {
    # Standard spec
    ("spec", "product-scope"): "Product scope and requirements",
    ("spec", "system-expectations"): "System expectations and constraints",
    ("spec", "validation-risk"): "Validation and risks",
    # Standard plan
    ("plan", "architecture-foundation"): "Architecture foundation",
    ("plan", "quality-and-structure"): "Quality and structure",
    ("plan", "data-api-security"): "Data, API and security",
    ("plan", "operations-risk"): "Operations and risk",
    # Harness (both modes — same two-part shape, different keys)
    ("harness", "harness-contract"): "Test contracts and coverage matrix",
    ("harness", "harness-files"): "Runnable test files",
    ("harness", "demo-harness-contract"): "Test contracts and coverage matrix",
    ("harness", "demo-harness-files"): "Runnable test files",
    # Standard tasks
    ("tasks", "task-overview"): "Task overview",
    ("tasks", "task-foundation-blocks"): "Foundation tasks",
    ("tasks", "task-interface-blocks"): "Interface tasks",
    ("tasks", "task-hardening-blocks"): "Hardening tasks",
    # Demo Day single-pass stages
    ("spec", "demo-full"): "The complete spec",
    ("plan", "demo-full"): "The complete plan",
    ("tasks", "demo-full"): "The complete task list",
    # Standard single-chunk fallback shape
    ("spec", "full"): "The complete spec",
    ("plan", "full"): "The complete plan",
    ("harness", "full"): "The complete harness",
    ("tasks", "full"): "The complete task list",
}


def chunk_label(stage_type: str, chunk_key: str) -> str:
    """Return the user-facing name for one generation chunk."""
    mapped = _CHUNK_LABELS.get((stage_type, chunk_key))
    if mapped:
        return mapped
    return chunk_key.replace("-", " ").replace("_", " ").strip().capitalize()


def chunk_labels(stage_type: str, chunk_keys: list[str]) -> list[str]:
    """Map a list of chunk keys to user-facing names, preserving order."""
    return [chunk_label(stage_type, key) for key in chunk_keys]
