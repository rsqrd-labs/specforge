from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = REPO_ROOT / "backend"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def backend_path(*parts: str) -> Path:
    return BACKEND_ROOT.joinpath(*parts)


def import_backend(module_name: str) -> Any:
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        pytest.fail(f"Expected backend module '{module_name}' to exist: {exc}")
        raise  # pragma: no cover - pytest.fail always raises; satisfies flow analysis


def read_backend_file(*parts: str) -> str:
    path = backend_path(*parts)
    assert path.exists(), f"Missing backend file: {path.relative_to(REPO_ROOT)}"
    return path.read_text(encoding="utf-8")


def route_paths(app: Any) -> set[str]:
    """Return every registered route path, flattening nested routers.

    FastAPI 0.139+ registers ``app.include_router(...)`` as ``_IncludedRouter``
    entries that carry no ``.path`` themselves; the real ``APIRoute`` objects
    (whose ``.path`` already includes the router prefix) live on the wrapped
    ``original_router``. Older FastAPI exposed the flattened routes directly,
    so both shapes are handled.
    """
    paths: set[str] = set()
    stack = list(app.routes)
    while stack:
        route = stack.pop()
        path = getattr(route, "path", None)
        if path is not None:
            paths.add(path)
        nested = getattr(route, "original_router", None)
        if nested is not None:
            stack.extend(nested.routes)
    return paths
