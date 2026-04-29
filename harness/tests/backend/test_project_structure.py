from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]


EXPECTED_DIRECTORIES = [
    ".github/workflows",
    "backend/config",
    "backend/routers",
    "backend/services/llm",
    "backend/services/pipeline",
    "backend/services/evals",
    "backend/services/security",
    "backend/services/observability",
    "backend/prompts",
    "backend/models",
    "backend/schemas",
    "backend/middleware",
    "backend/migrations/versions",
    "backend/tests",
    "frontend/src/pages",
    "frontend/src/components/workspace",
    "frontend/src/components/shared",
    "frontend/src/store",
    "frontend/src/services",
    "frontend/src/hooks",
    "frontend/src/types",
    "frontend/src/config",
    "frontend/public",
]


EXPECTED_FILES = [
    "docker-compose.yml",
    ".gitignore",
    "README.md",
    "backend/.python-version",
    "backend/.env.example",
    "backend/requirements.txt",
    "backend/requirements-dev.txt",
    "backend/pyproject.toml",
    "backend/main.py",
    "backend/config.py",
    "backend/database.py",
    "frontend/package.json",
    "frontend/vite.config.ts",
    "frontend/tsconfig.json",
    "frontend/tailwind.config.ts",
    "frontend/index.html",
    "frontend/.env.example",
    "frontend/src/main.tsx",
    "frontend/src/App.tsx",
]


def test_v1_monorepo_structure_exists() -> None:
    missing_dirs = [
        path for path in EXPECTED_DIRECTORIES if not (REPO_ROOT / path).is_dir()
    ]
    missing_files = [
        path for path in EXPECTED_FILES if not (REPO_ROOT / path).is_file()
    ]

    assert not missing_dirs, "Missing directories:\n" + "\n".join(missing_dirs)
    assert not missing_files, "Missing files:\n" + "\n".join(missing_files)


def test_gitignore_blocks_local_secrets_and_build_artifacts() -> None:
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    required_patterns = {
        "__pycache__",
        "*.pyc",
        ".env",
        "node_modules",
        ".venv",
        "dist",
        "*.pem",
        "*.log",
    }

    missing = sorted(pattern for pattern in required_patterns if pattern not in gitignore)
    assert not missing, f".gitignore is missing: {missing}"


def test_docker_compose_declares_postgres_and_redis() -> None:
    compose_path = REPO_ROOT / "docker-compose.yml"
    assert compose_path.exists(), "docker-compose.yml must exist at repo root"
    compose = compose_path.read_text(encoding="utf-8")

    for expected in ["postgres:16-alpine", "redis:7-alpine", "healthcheck"]:
        assert expected in compose
