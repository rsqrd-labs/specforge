from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from models import Stage, Workspace
from services.pipeline.export_service import (
    ExportNotReadyError,
    build_export,
    parse_harness_files,
)


def _make_workspace(user_id=None) -> Workspace:
    return Workspace(
        id=uuid4(),
        user_id=user_id or uuid4(),
        name="WS",
        problem_statement="build a todo app",
        provider="anthropic",
        model="claude-sonnet-4-6",
        status="active",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _make_stage(workspace_id, stage_type, status="finalised", content="") -> Stage:
    return Stage(
        id=uuid4(),
        workspace_id=workspace_id,
        type=stage_type,
        status=status,
        content=content,
        current_version=1,
        review_gate_acknowledged=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


# Matches the format the LLM actually emits: ## File: <path> heading followed
# by a fenced code block.
_HARNESS_WITH_FILES = """\
## Harness Overview

Overview text.

## Files

## File: harness/tests/test_auth.py

```python
def test_login():
    assert True
```

## File: harness/tests/test_spec.py

```python
def test_spec():
    assert True
```
"""


class _FakeDB:
    def __init__(self, workspace: Workspace, stages: list[Stage]) -> None:
        self._workspace = workspace
        self._stages = stages
        self._calls = 0

    async def execute(self, statement: Any) -> Any:
        self._calls += 1
        result = MagicMock()
        if self._calls == 1:
            result.scalar_one_or_none.return_value = self._workspace
        else:
            result.scalars.return_value = iter(self._stages)
        return result


@pytest.mark.asyncio
async def test_build_export_returns_valid_zip() -> None:
    user_id = uuid4()
    ws = _make_workspace(user_id=user_id)
    stages = [
        _make_stage(ws.id, "spec", content="# Spec"),
        _make_stage(ws.id, "plan", content="# Plan"),
        _make_stage(ws.id, "harness", content=_HARNESS_WITH_FILES),
        _make_stage(ws.id, "tasks", content="# Tasks"),
    ]
    db = _FakeDB(ws, stages)

    result = await build_export(ws.id, user_id, db)

    assert isinstance(result, bytes)
    zf = zipfile.ZipFile(io.BytesIO(result))
    names = zf.namelist()
    assert "SPEC.md" in names
    assert "PLAN.md" in names
    assert "TASKS.md" in names
    assert "harness/tests/test_auth.py" in names
    assert "harness/tests/test_spec.py" in names


@pytest.mark.asyncio
async def test_build_export_raises_when_stage_not_finalised() -> None:
    user_id = uuid4()
    ws = _make_workspace(user_id=user_id)
    stages = [
        _make_stage(ws.id, "spec", status="draft", content="# Spec"),
        _make_stage(ws.id, "plan", content="# Plan"),
        _make_stage(ws.id, "harness", content="# Harness"),
        _make_stage(ws.id, "tasks", content="# Tasks"),
    ]
    db = _FakeDB(ws, stages)

    with pytest.raises(ExportNotReadyError):
        await build_export(ws.id, user_id, db)


@pytest.mark.asyncio
async def test_build_export_harness_fallback_when_no_code_fences() -> None:
    user_id = uuid4()
    ws = _make_workspace(user_id=user_id)
    stages = [
        _make_stage(ws.id, "spec", content="# Spec"),
        _make_stage(ws.id, "plan", content="# Plan"),
        _make_stage(ws.id, "harness", content="plain harness content, no code blocks"),
        _make_stage(ws.id, "tasks", content="# Tasks"),
    ]
    db = _FakeDB(ws, stages)

    result = await build_export(ws.id, user_id, db)
    zf = zipfile.ZipFile(io.BytesIO(result))
    names = zf.namelist()
    assert "harness/HARNESS.md" in names


def test_parse_harness_files_parses_file_headings() -> None:
    # Three-file harness with harness/ prefix on filenames (as LLM emits)
    content = """\
## File: harness/conftest.py

```python
import pytest

@pytest.fixture
def client():
    return None
```

## File: harness/tests/unit/test_core.py

```python
def test_something():
    assert True
```

## File: harness/schemas/api.json

```json
{"type": "object"}
```
"""
    files = parse_harness_files(content)

    assert files == {
        "harness/conftest.py": (
            "import pytest\n\n@pytest.fixture\ndef client():\n" "    return None\n"
        ),
        "harness/tests/unit/test_core.py": "def test_something():\n    assert True\n",
        "harness/schemas/api.json": '{"type": "object"}\n',
    }


def test_parse_harness_files_strips_redundant_harness_prefix() -> None:
    # LLM sometimes includes harness/ prefix, sometimes omits it — both should
    # produce the same harness/ path in the zip.
    with_prefix = "## File: harness/tests/test_a.py\n\n```python\nx = 1\n```\n"
    without_prefix = "## File: tests/test_a.py\n\n```python\nx = 1\n```\n"

    assert parse_harness_files(with_prefix) == parse_harness_files(without_prefix)
    assert "harness/tests/test_a.py" in parse_harness_files(with_prefix)


def test_parse_harness_files_handles_nested_fences_in_readme() -> None:
    # README.md contains markdown with its own ``` blocks; the state machine
    # must track the outer fence and not terminate early on an inner one.
    content = (
        "## File: harness/README.md\n\n"
        "````markdown\n"
        "# Harness\n\n"
        "Run with:\n\n"
        "```bash\n"
        "pytest harness/\n"
        "```\n"
        "````\n"
        "\n"
        "## File: harness/conftest.py\n\n"
        "```python\n"
        "pass\n"
        "```\n"
    )
    files = parse_harness_files(content)

    assert "harness/README.md" in files
    assert "```bash" in files["harness/README.md"]
    assert "harness/conftest.py" in files


def test_parse_harness_files_rejects_unsafe_filenames() -> None:
    content = """\
## File: harness/tests/test_ok.py

```python
def test_ok():
    assert True
```

## File: ../../tmp/pwned.py

```python
print("path traversal")
```

## File: /absolute/path.py

```python
print("absolute")
```

## File: harness/CON

```python
print("windows reserved")
```

## File: harness/file.txt:ads

```python
print("alternate data stream")
```
"""
    files = parse_harness_files(content)

    assert files == {"harness/tests/test_ok.py": "def test_ok():\n    assert True\n"}
