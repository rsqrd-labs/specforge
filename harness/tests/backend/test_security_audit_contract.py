from __future__ import annotations

from pathlib import PurePosixPath

import pytest
from harness_utils import REPO_ROOT, import_backend, read_backend_file
from pydantic import ValidationError


def _is_safe_zip_member(path: str) -> bool:
    parsed = PurePosixPath(path)
    return (
        not parsed.is_absolute()
        and parsed.parts[:1] == ("harness",)
        and ".." not in parsed.parts
        and len(parsed.parts) > 1
    )


def test_export_service_rejects_zip_slip_harness_filenames() -> None:
    module = import_backend("services.pipeline.export_service")
    parse_harness_files = getattr(
        module,
        "parse_harness_files",
        getattr(module, "_parse_harness_files", None),
    )
    assert parse_harness_files is not None

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

```python nested/../escape.py
print("owned")
```
""")

    assert "harness/tests/test_ok.py" in files
    assert all(_is_safe_zip_member(path) for path in files), (
        "Exported ZIP members must stay under harness/ and reject absolute or "
        f"parent-traversal paths. Got: {sorted(files)}"
    )


def test_refine_request_enforces_size_and_selection_bounds() -> None:
    schemas = import_backend("schemas.stage")
    RefineRequest = getattr(schemas, "RefineRequest")

    with pytest.raises(ValidationError):
        RefineRequest(
            instruction="x" * 20_001,
            selection_start=0,
            selection_end=1,
            selected_text="x",
        )

    with pytest.raises(ValidationError):
        RefineRequest(
            instruction="short",
            selection_start=0,
            selection_end=1,
            selected_text="x" * 100_001,
        )

    with pytest.raises(ValidationError):
        RefineRequest(
            instruction="short",
            selection_start=10,
            selection_end=1,
            selected_text="text",
        )


def test_refine_flow_verifies_selection_matches_current_content() -> None:
    source = read_backend_file("services", "pipeline", "stage_manager.py")

    assert (
        "selection_end > len(content)" in source
        or "selection_end <= len(content)" in source
    )
    assert (
        "content[request.selection_start:request.selection_end]" in source
        or "content[request.selection_start : request.selection_end]" in source
    )
    assert "request.selected_text" in source


def test_rate_limiter_only_trusts_forwarded_for_from_known_proxies() -> None:
    source = read_backend_file("middleware", "rate_limit.py").lower()

    assert "x-forwarded-for" in source
    assert "trusted" in source and "proxy" in source, (
        "X-Forwarded-For must only be honored when request.client.host is a "
        "configured trusted proxy."
    )


def test_backend_sets_standard_security_headers() -> None:
    combined = "\n".join(
        [
            read_backend_file("main.py"),
            read_backend_file("services", "observability.py"),
        ]
    )

    for header in [
        "Content-Security-Policy",
        "Strict-Transport-Security",
        "X-Frame-Options",
        "X-Content-Type-Options",
        "Referrer-Policy",
    ]:
        assert header in combined


def test_compose_does_not_publish_datastores_on_all_interfaces() -> None:
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert '"5432:5432"' not in compose
    assert '"6379:6379"' not in compose
    assert "127.0.0.1:5432:5432" in compose
    assert "127.0.0.1:6379:6379" in compose
