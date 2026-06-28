#!/bin/sh
set -e
uv run --no-sync alembic upgrade head
# T-USE-11: seed starter templates AFTER the migration so the table exists,
# BEFORE uvicorn so traffic never hits a templates-less DB. The script is
# idempotent and exits 0 on a fully-seeded DB.
uv run --no-sync python -m scripts.seed_templates
# F4 (scalability audit): worker count + bind come from gunicorn.conf.py
# (WEB_CONCURRENCY-driven, default 2) so there is one source of truth across
# entrypoint.sh / Procfile / railway.json.
exec uv run --no-sync gunicorn main:app -c gunicorn.conf.py
