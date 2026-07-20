#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCHEMA="$(mktemp "${TMPDIR:-/tmp}/specforge-openapi.XXXXXX.json")"
trap 'rm -f "$SCHEMA"' EXIT

cd "$ROOT/backend"
DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://specforge:specforge@localhost:5432/specforge}" \
REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}" \
GOOGLE_CLIENT_ID="${GOOGLE_CLIENT_ID:-contract-check}" \
GOOGLE_CLIENT_SECRET="${GOOGLE_CLIENT_SECRET:-contract-check}" \
FRONTEND_URL="${FRONTEND_URL:-http://localhost:5173}" \
ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-contract-check}" \
OPENAI_API_KEY="${OPENAI_API_KEY:-contract-check}" \
GOOGLE_API_KEY="${GOOGLE_API_KEY:-contract-check}" \
ENCRYPTION_MASTER_KEY="${ENCRYPTION_MASTER_KEY:-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=}" \
CSRF_SECRET="${CSRF_SECRET:-contract-check-secret-long-enough}" \
ENVIRONMENT="test" \
uv run python -c 'import json; from main import app; print(json.dumps(app.openapi(), sort_keys=True))' > "$SCHEMA"

cd "$ROOT/frontend"
pnpm exec openapi-typescript "$SCHEMA" -o src/types/api.generated.ts
