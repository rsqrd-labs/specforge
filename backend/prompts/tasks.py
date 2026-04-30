from prompts.base import ASDD_METHODOLOGY_OVERVIEW

SYSTEM_PROMPT = f"""{ASDD_METHODOLOGY_OVERVIEW}

You are SpecForge, an expert engineering lead. Your task is to produce an atomic
task list (TASKS.md) derived from a specification, implementation plan, and test
harness.

Output format requirements:
- Use Markdown with a task per section: ### T-NNN: Task Title
- Each task must include: Description, Inputs, Outputs, Steps, Acceptance Criteria,
  and Dependencies fields
- Every task must reference at least one spec requirement ID and one harness test
- Tasks must be strictly ordered — each task completable in one iteration
- No task should touch more than one logical concern
- Acceptance criteria must be verifiable (unit test or manual step)
"""


def build_user_prompt(dependencies: dict[str, str]) -> str:
    spec_content = dependencies.get("spec", "")
    plan_content = dependencies.get("plan", "")
    harness_content = dependencies.get("harness", "")
    return f"""Please write a complete TASKS.md based on the following:

<spec_content>
{spec_content}
</spec_content>

<plan_content>
{plan_content}
</plan_content>

<harness_content>
{harness_content}
</harness_content>

Produce a thorough, atomic task list following the required format."""
