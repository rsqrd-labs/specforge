from prompts.base import (
    SECURITY_AND_PRIVACY_RULES,
    load_prompt,
    wrap_untrusted_content,
)

_PATCH_SYSTEM_PROMPT = f"""{SECURITY_AND_PRIVACY_RULES}

Role: You are SpecForge's test architect writing a targeted patch for an existing test
harness. Produce new test files covering specific uncovered requirements — nothing else.

Output rules:
- Output ONLY new `### File:` sections, each as `### File: path/to/new_test_file.py` followed by one fenced code block with complete, runnable content. Use exactly three hashes, matching the existing harness's Files section, so the new file is counted as covered.
- Create new companion files (e.g. test_auth_patch.py); never modify existing files.
- Match the existing harness exactly: import patterns, fixture names, factory usage, test structure.
- Tag every test on the line immediately before `def test_`: `# Tests: <req-id>`.
- No preamble, matrix, coverage plan, or commentary — file sections only.
- Every test is runnable: real imports, real assertions, no pass/TODO bodies.
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

Output one `### File: path/to/file` section per new file, with complete runnable
content. Do not repeat or modify existing files.

{wrapped}"""


def build_missing_files_user_prompt(
    existing_harness: str,
    missing_files: list[str],
) -> str:
    """Prompt for the Prong-A auto-complete: emit the exact files the harness's
    own File Tree / Requirement-to-Test Matrix named but whose content is missing
    from the ## Files section. Unlike the coverage patch (which invents new files
    for uncovered requirements), this fills in files the harness already committed
    to, so the paths are fixed — the model must not rename or substitute them.
    """
    file_list = "\n".join(f"- `{path}`" for path in missing_files)
    context = _harness_context_for_patch(existing_harness)
    wrapped = wrap_untrusted_content("existing_harness", context)
    return f"""The harness below names these files in its File Tree and/or
Requirement-to-Test Matrix, but their content is missing from the `## Files`
section. Emit the full content of ONLY these files, using each path EXACTLY as
written (do not rename, move, or substitute a different path):

{file_list}

Output one `### File: path` section per file, each followed by one complete,
runnable fenced code block. Match the existing harness's stack, imports, fixture
names, factory usage, and traceability-comment style (`# Tests: <req-id>` or
`// Tests: <req-id>`). Do not repeat, modify, or invent any other file.

{wrapped}"""
