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


_HARNESS_WITH_FILES = """\
## Test Harness

```python tests/test_auth.py
def test_login():
    assert True
```

```python tests/test_spec.py
def test_spec():
    pass
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
    assert any(n.startswith("harness/") for n in names)


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


def test_parse_harness_files_rejects_unsafe_filenames() -> None:
    files = parse_harness_files("""```python tests/test_ok.py
def test_ok():
    assert True
```

```python ../../tmp/pwned.py
print("owned")
```

```python /absolute/path.py
print("owned")
```

```python C:\\Users\\attacker\\pwned.py
print("owned")
```

```python CON
print("reserved")
```

```python file.txt:ads
print("alternate data stream")
```

```python tests/bad\u0001name.py
print("control char")
```
""")

    assert files == {"harness/tests/test_ok.py": "def test_ok():\n    assert True\n"}
