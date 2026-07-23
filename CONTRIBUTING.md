# Contributing to Thought2Build

Thank you for improving Thought2Build. Open an issue before a large architectural
change so its scope and migration impact can be agreed before implementation.

## Development setup

The recommended full-stack environment is:

```bash
docker compose up --build
```

For focused work, follow the backend and frontend setup commands in the
[README](README.md). Never commit `.env` files, provider keys, OAuth secrets,
production data, or generated coverage/build output.

## Before opening a pull request

Run the checks relevant to your change. The full release checks are:

```bash
cd backend
uv run ruff check .
uv run black --check .
uv run pytest tests/ -q

cd ../frontend
corepack pnpm install --frozen-lockfile
corepack pnpm lint
corepack pnpm tsc --noEmit
corepack pnpm test
corepack pnpm build
```

Also run harness, marketing, container, or migration checks when those areas
change. A pull request should explain the user impact, test evidence, rollout or
rollback concerns, and any configuration or database changes. Keep unrelated
formatting and refactors out of the patch.

Report security issues using [SECURITY.md](SECURITY.md), never a public issue.
