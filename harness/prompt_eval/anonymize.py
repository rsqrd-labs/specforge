from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path

GOLDEN_ROOT = Path(__file__).parent / "golden_workspaces"
MAX_FREEFORM_CHARS = 280

PII_PATTERNS: dict[str, re.Pattern[str]] = {
    "email": re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),
    "ipv4": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    "phone": re.compile(r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}\b"),
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "sample_person_name": re.compile(r"\b(?:Alice|Bob|Carol|Dave|Eve|Mallory)\b"),
}


class AnonymizationError(ValueError):
    pass


def anonymize_text(text: str) -> str:
    """Strip common PII patterns and replace oversized free-form lines."""

    sanitized = text
    for label, pattern in PII_PATTERNS.items():
        sanitized = pattern.sub(f"<REDACTED_{label.upper()}>", sanitized)

    lines: list[str] = []
    for line in sanitized.splitlines():
        if len(line) <= MAX_FREEFORM_CHARS:
            lines.append(line)
            continue
        digest = hashlib.sha256(line.encode("utf-8")).hexdigest()[:12]
        lines.append(f"<REDACTED_LONG_TEXT sha256={digest}>")
    suffix = "\n" if text.endswith("\n") else ""
    return "\n".join(lines) + suffix


def iter_golden_files(root: Path = GOLDEN_ROOT):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.name == ".DS_Store":
            continue
        yield path


def assert_no_pii(text: str, *, path: Path | None = None) -> None:
    failures: list[str] = []
    for label, pattern in PII_PATTERNS.items():
        if pattern.search(text):
            failures.append(label)
    long_lines = [
        index
        for index, line in enumerate(text.splitlines(), start=1)
        if len(line) > MAX_FREEFORM_CHARS
    ]
    if long_lines:
        failures.append(f"long_line:{long_lines[:5]}")
    if failures:
        where = f" in {path}" if path else ""
        raise AnonymizationError(f"PII/anonymization failures{where}: {failures}")


def check_tree(root: Path = GOLDEN_ROOT) -> list[Path]:
    checked: list[Path] = []
    for path in iter_golden_files(root):
        text = path.read_text(encoding="utf-8")
        assert_no_pii(text, path=path)
        checked.append(path)
    return checked


def main() -> int:
    parser = argparse.ArgumentParser(description="Anonymize or check golden artifacts.")
    parser.add_argument("--root", type=Path, default=GOLDEN_ROOT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        checked = check_tree(args.root)
        print(f"Checked {len(checked)} golden artifact files.")
        return 0

    for path in iter_golden_files(args.root):
        original = path.read_text(encoding="utf-8")
        path.write_text(anonymize_text(original), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
