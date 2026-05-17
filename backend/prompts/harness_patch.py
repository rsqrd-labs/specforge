from prompts.base import (
    SECURITY_AND_PRIVACY_RULES,
    load_prompt,
    wrap_untrusted_content,
)

_PATCH_SYSTEM_PROMPT = f"""{SECURITY_AND_PRIVACY_RULES}

Role:
You are SpecForge's test architect writing a targeted patch for an existing test
harness. Your sole task is to produce new test files that cover specific uncovered
requirements — nothing else.

Output rules:
- Output ONLY new ## File: sections. Format:
    ## File: path/to/new_test_file.py
    ```python
    <complete, runnable file content>
    ```
- Create new companion files rather than modifying existing ones
  (e.g. test_auth_patch.py instead of modifying test_auth.py).
- Follow the exact same import patterns, fixture names, factory usage, and test
  structure as the existing harness.
- Tag every test immediately before def test_: `# Tests: <req-id>`
- No preamble, no matrix, no coverage plan, no commentary. File sections only.
- Every test must be runnable: real imports, real assertions, no pass/TODO bodies.
"""


async def get_patch_system_prompt() -> str:
    return await load_prompt("specforge.harness.patch.system", _PATCH_SYSTEM_PROMPT)


_MAX_HARNESS_CONTEXT = 4000


def _harness_context_for_patch(harness_content: str) -> str:
    if len(harness_content) <= _MAX_HARNESS_CONTEXT:
        return harness_content
    # Keep the overview + file tree (typically the first portion); skip file bodies.
    files_section = harness_content.find("\n## Files\n")
    if files_section != -1 and files_section <= _MAX_HARNESS_CONTEXT * 2:
        return harness_content[:files_section].rstrip() + "\n\n(file contents omitted)"
    return harness_content[:_MAX_HARNESS_CONTEXT] + "\n\n(truncated)"


def build_patch_user_prompt(
    existing_harness: str,
    uncovered_reqs: list[str],
) -> str:
    req_list = "\n".join(f"- {req}" for req in uncovered_reqs)
    context = _harness_context_for_patch(existing_harness)
    wrapped = wrap_untrusted_content("existing_harness", context)
    return f"""Generate new test files covering the following uncovered requirements.

Uncovered requirements:
{req_list}

Output one `## File: path/to/file` section per new file, with complete runnable
content. Do not repeat or modify existing files.

{wrapped}"""
