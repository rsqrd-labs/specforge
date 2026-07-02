from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from harness_utils import import_backend, read_backend_file


class _NoopPipeline:
    def zremrangebyscore(self, *args):
        return self

    def zadd(self, *args):
        return self

    def zcard(self, *args):
        return self

    def expire(self, *args):
        return self

    async def execute(self) -> list:
        return [0, 1, 1, 1]


class _NoopRedis:
    def pipeline(self) -> _NoopPipeline:
        return _NoopPipeline()


def test_unhandled_errors_receive_security_headers_without_detail_leak() -> None:
    main = import_backend("main")
    settings = import_backend("config").settings
    app = main.create_app(redis_client=_NoopRedis())

    @app.get("/second-pass-boom")
    async def second_pass_boom() -> None:
        raise RuntimeError("internal secret context")

    with patch.object(settings, "environment", "development"):
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/second-pass-boom")

    assert response.status_code == 500
    assert response.json() == {"detail": "Internal Server Error"}
    for header in [
        "Content-Security-Policy",
        "X-Frame-Options",
        "X-Content-Type-Options",
        "Referrer-Policy",
    ]:
        assert response.headers.get(header)


def test_trusted_proxy_configuration_rejects_universal_trust_ranges() -> None:
    rate_limit = import_backend("middleware.rate_limit")

    with pytest.raises(ValueError, match="universal trust"):
        rate_limit._parse_trusted_proxy_networks("0.0.0.0/0")

    with pytest.raises(ValueError, match="universal trust"):
        rate_limit._parse_trusted_proxy_networks("::/0")


def test_refine_matches_raw_selection_and_sanitizes_prompt() -> None:
    router_source = read_backend_file("routers", "stage.py")
    manager_source = read_backend_file("services", "pipeline", "stage_manager.py")

    assert 'selected_text": sanitize_text' not in router_source
    assert (
        "content[request.selection_start:request.selection_end]" in manager_source
        or "content[request.selection_start : request.selection_end]" in manager_source
    )
    # Both prompt inputs must flow through the sanitizer before the prompt
    # build. Since scalability-audit P2 (F7) that is the async offload wrapper
    # (byte-identical output, dispatched off the event loop for large
    # selections) — pin the async form so a regression back to an inline
    # sync bleach pass on the loop fails this contract.
    assert "sanitize_text_async(request.selected_text)" in manager_source
    assert "sanitize_text_async(request.instruction)" in manager_source


def test_export_rejects_windows_unsafe_harness_filenames() -> None:
    export_service = import_backend("services.pipeline.export_service")

    files = export_service.parse_harness_files("""```python tests/ok.py
def test_ok():
    assert True
```

```python CON
print("reserved")
```

```python file.txt:ads
print("ads")
```
""")

    assert files == {"harness/tests/ok.py": "def test_ok():\n    assert True\n"}
