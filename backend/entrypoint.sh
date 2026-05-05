#!/bin/sh
set -e
uv run --no-sync alembic upgrade head
exec uv run --no-sync gunicorn main:app \
  --worker-class uvicorn.workers.UvicornWorker \
  --workers 2 \
  --bind 0.0.0.0:8000
