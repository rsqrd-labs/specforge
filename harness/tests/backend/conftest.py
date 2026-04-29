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


def read_backend_file(*parts: str) -> str:
    path = backend_path(*parts)
    assert path.exists(), f"Missing backend file: {path.relative_to(REPO_ROOT)}"
    return path.read_text(encoding="utf-8")
