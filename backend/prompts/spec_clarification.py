"""Spec Clarification prompt — judge-model produces 3–5 sharp questions.

Phase 14 / V1 spec §4.4.1 / Plan §18.3. The clarification step runs
before the *first* spec generation per workspace. Its purpose is to
lift the floor on spec quality by surfacing the assumptions the user
hasn't yet articulated.

The judge model (Claude Haiku / GPT-4o Mini / Gemini Flash) is
intentionally cheap — this call is free for the end user and must be
sub-cent on our side. The model is instructed to return a strict JSON
array so parsing has no LLM-specific quirks.
"""

from __future__ import annotations

from prompts.base import wrap_untrusted_content

# A senior PM voice. Three small constraints make the output reliable
# enough for direct JSON parsing:
#   1. Strict shape: JSON array, no prose, no Markdown fences.
#   2. Bounded count: 3–5 items so the modal stays a conversation, not a survey.
#   3. Concrete questions: each must drive a downstream decision in the spec.
SYSTEM_PROMPT = """You are SpecForge's senior product clarification agent.

A user has written a problem statement and is about to generate a full
product spec. Before they do, surface the 3–5 *most decision-shaping*
questions whose answers would meaningfully change the spec.

Pick questions that:
- expose an ambiguous user / persona,
- expose an unstated success criterion,
- expose a hidden constraint (regulatory, performance, cost),
- expose a deliberate scope cut,
- or expose a key integration assumption.

Skip generic questions ("what's your timeline?"). Skip questions whose
answer would not actually change a section of the spec. If the problem
statement is already crisp, return fewer questions, but never zero.

OUTPUT FORMAT — strict JSON array, no preamble, no Markdown:

[
  {"question": "<one short question>", "why_it_matters": "<one short reason>"},
  ...
]

Each "question" is at most 140 characters. Each "why_it_matters" is at
most 140 characters and explains in plain language what part of the
spec depends on the answer. Output the JSON array and nothing else."""


def build_user_prompt(problem_statement: str) -> str:
    """Render the user prompt for the clarification judge call.

    The problem statement is wrapped with the same untrusted-content
    fence the rest of the pipeline uses, so prompt injection attempts
    in the statement cannot redirect the judge model.
    """
    wrapped = wrap_untrusted_content("problem_statement", problem_statement)
    return f"""Read the user's problem statement and produce the 3–5
clarifying questions whose answers would most change the spec you would
write from it.

{wrapped}

Return the JSON array described in the system prompt. No prose."""
