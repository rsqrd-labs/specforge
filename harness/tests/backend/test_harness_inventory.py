"""Meta-contract: the backend harness has no unaccounted-for test modules.

Issue #84 (backend audit #29, finding BE29-004): the full backend harness had
drifted to 21+ stale failures outside the CI-selected subset, so the documented
broad command (`pytest tests/backend/ -q`) could not be trusted and real
regressions could hide among known-stale ones.

The remediation makes the COMPLETE ``harness/tests/backend`` directory the
authoritative target:

1. CI runs the whole directory in one step ("Complete backend harness
   contracts" in .github/workflows/ci.yml). A new module is authoritative the
   moment it lands; there is no subset for it to fall outside of.
2. This meta-test fails if that CI step is ever narrowed back to a per-file
   selection, and polices the deprecation registry below.

A module that must be retired gracefully (e.g. it pins a feature scheduled for
removal) is not deleted silently: it gets an entry in ``DEPRECATED_MODULES``
with an owner and an expiry date. Expired entries fail this test, forcing the
final decision (delete the module or renew the entry with justification).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from conftest import REPO_ROOT

HARNESS_BACKEND_DIR = Path(__file__).resolve().parent

# Every module listed here must carry: owner (a GitHub handle), expiry (ISO
# date), and reason. While listed, the module may be skipped/xfailed inside the
# module itself — but it stays visible here and expires loudly.
DEPRECATED_MODULES: dict[str, dict[str, str]] = {
    # "test_example_contract.py": {
    #     "owner": "Arv-ind-s",
    #     "expiry": "2026-12-31",
    #     "reason": "Pins the Phase-N flow scheduled for removal in issue #NNN.",
    # },
}


def test_ci_runs_the_complete_backend_harness_directory() -> None:
    """CI must run the full harness directory, not a hand-picked file subset."""
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "pytest ../harness/tests/backend -q" in ci, (
        "The authoritative CI step must run the COMPLETE backend harness "
        "directory (`uv run pytest ../harness/tests/backend -q`). Narrowing it "
        "back to per-file selection reintroduces the BE29-004 drift class: "
        "stale failures accumulating outside the selected subset. Issue #84."
    )


def test_every_deprecated_module_has_owner_and_unexpired_expiry() -> None:
    """Deprecation is explicit, owned, and time-boxed — never silent."""
    problems: list[str] = []
    for name, meta in DEPRECATED_MODULES.items():
        if not (HARNESS_BACKEND_DIR / name).exists():
            problems.append(f"{name}: listed as deprecated but no longer exists — remove the entry")
            continue
        if not meta.get("owner"):
            problems.append(f"{name}: missing owner")
        if not meta.get("reason"):
            problems.append(f"{name}: missing reason")
        expiry = meta.get("expiry", "")
        try:
            expiry_date = date.fromisoformat(expiry)
        except ValueError:
            problems.append(f"{name}: expiry {expiry!r} is not an ISO date")
            continue
        if expiry_date < date.today():
            problems.append(
                f"{name}: deprecation expired on {expiry} — delete the module "
                "or renew the entry with justification (issue #84)"
            )
    assert not problems, "Deprecation registry violations:\n" + "\n".join(problems)


def test_no_unregistered_test_module_is_skipped_wholesale() -> None:
    """A module may only opt out of the harness via the deprecation registry.

    ``pytest.skip(..., allow_module_level=True)`` or a module-wide
    ``pytestmark = pytest.mark.skip`` silently removes a whole contract file
    from the authoritative run — exactly the invisible rot issue #84 closed.
    """
    offenders: list[str] = []
    for module in sorted(HARNESS_BACKEND_DIR.glob("test_*.py")):
        if module.name in DEPRECATED_MODULES or module.name == Path(__file__).name:
            continue
        source = module.read_text(encoding="utf-8")
        if "allow_module_level=True" in source or (
            "pytestmark" in source and "mark.skip" in source
        ):
            offenders.append(module.name)
    assert not offenders, (
        "These harness modules skip themselves wholesale without a "
        f"DEPRECATED_MODULES entry (issue #84): {offenders}"
    )
