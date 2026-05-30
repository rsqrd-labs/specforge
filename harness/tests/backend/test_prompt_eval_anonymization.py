from __future__ import annotations

import importlib
import sys
from pathlib import Path

HARNESS_ROOT = Path(__file__).resolve().parents[2]
if str(HARNESS_ROOT) not in sys.path:
    sys.path.insert(0, str(HARNESS_ROOT))

check_tree = importlib.import_module("prompt_eval.anonymize").check_tree


def test_prompt_eval_golden_workspaces_are_anonymized() -> None:
    """T-249: committed golden artifacts must not retain PII patterns."""

    checked = check_tree(HARNESS_ROOT / "prompt_eval" / "golden_workspaces")
    assert checked, "Expected at least one committed golden artifact to check."
