from __future__ import annotations

from conftest import import_backend, read_backend_file


HARNESS_CONTENT = """\
## File: harness/tests/unit/test_auth.py

```python
def test_login_returns_jwt():
    assert True
```

## File: harness/types/stage.ts

```typescript
export type StageType = "spec" | "plan" | "harness" | "tasks"
```
"""


def test_export_service_parses_file_path_labelled_code_fences() -> None:
    module = import_backend("services.pipeline.export_service")
    parse_harness_files = getattr(module, "parse_harness_files", None)
    assert parse_harness_files is not None

    files = parse_harness_files(HARNESS_CONTENT)

    assert "harness/tests/unit/test_auth.py" in files
    assert any(path.endswith("types/stage.ts") for path in files)


def test_export_service_falls_back_to_harness_markdown_when_parse_fails() -> None:
    module = import_backend("services.pipeline.export_service")
    parse_harness_files = getattr(module, "parse_harness_files", None)
    assert parse_harness_files is not None

    files = parse_harness_files("plain prose without labelled fences")

    assert files == {"harness/HARNESS.md": "plain prose without labelled fences"}


def test_eval_runner_dispatches_all_stage_evaluators() -> None:
    source = read_backend_file("services", "evals", "runner.py").lower()

    for stage_type in ["spec", "plan", "harness", "tasks"]:
        assert stage_type in source
    for evaluator in ["spec_eval", "plan_eval", "harness_eval", "tasks_eval"]:
        assert evaluator in source
