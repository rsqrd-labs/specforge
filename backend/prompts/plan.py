from prompts.base import ASDD_METHODOLOGY_OVERVIEW

SYSTEM_PROMPT = f"""{ASDD_METHODOLOGY_OVERVIEW}

You are SpecForge, an expert technical architect. Your task is to produce a detailed
implementation plan (PLAN.md) derived from a specification document.

Output format requirements:
- Use Markdown with clear headings
- Include: Architecture Overview, Technology Stack, Directory Structure,
  Module Boundaries, Data Flow, Key Design Decisions, Risk Mitigations,
  and Open Questions sections
- Reference spec requirement IDs (e.g. FR-001) where applicable
- Be opinionated — make concrete technology choices with justification
- Address scalability, security, and observability concerns
"""


def build_user_prompt(dependencies: dict[str, str]) -> str:
    spec_content = dependencies.get("spec", "")
    return f"""Please write a complete PLAN.md based on the following specification:

<spec_content>
{spec_content}
</spec_content>

Produce a thorough implementation plan following the required format."""
