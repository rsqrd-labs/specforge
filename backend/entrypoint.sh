#!/bin/sh
set -e
uv run --no-sync alembic upgrade head
# T-USE-11: seed starter templates AFTER the migration so the table exists,
# BEFORE uvicorn so traffic never hits a templates-less DB. The script is
# idempotent and exits 0 on a fully-seeded DB.
uv run --no-sync python -m scripts.seed_templates
exec uv run --no-sync gunicorn main:app \
  --worker-class uvicorn.workers.UvicornWorker \
  --workers 2 \
  --bind 0.0.0.0:8000
