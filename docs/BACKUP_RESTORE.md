# Backup & Restore Design (PostgreSQL)

Owner: maintainer · Status: design (implement before public soft-launch, Phase B) ·
Applies to: the production Railway PostgreSQL database.

This is the disaster-recovery design for the single stateful component. Redis is a
cache/queue and is **not** backed up — it is reconstructible (admission leases,
rate-limit windows, token caches, arq queues); a Redis loss degrades in-flight jobs
but never loses committed data. All durable state is in Postgres.

## Goals (RPO / RTO)

| Target | Value | Rationale |
|---|---|---|
| **RPO** (max data loss) | ≤ 24h off-platform; ~minutes on-platform | Daily independent dump + Railway's own snapshots. |
| **RTO** (time to restore) | ≤ 1h to a working DB | Single `pg_restore` into a fresh Railway Postgres + `alembic upgrade head` (no-op) + smoke. |
| **Coverage** | Full logical dump (schema + data) | Enables full rebuild *and* single-table/row recovery. |

## Two independent layers (defense in depth)

Do not rely on a single mechanism. Use both:

### Layer 1 — Platform-native (Railway managed backups)
- Enable Railway's automated Postgres backups; confirm the schedule and retention on
  the current plan. This is the fast path (tighter RPO, snapshot-level restore) but is
  **single-vendor** — if the Railway project/account is lost, so are these.
- Action: turn it on, record retention, done. No code.

### Layer 2 — Independent off-platform logical dump (the real safety net)
An encrypted `pg_dump` on a schedule, pushed to object storage in a **different vendor**
(Cloudflare R2 / Backblaze B2 / AWS S3). This survives a total Railway loss and is the
one you drill.

**Mechanism: a scheduled GitHub Actions workflow.** Chosen over an in-app arq cron
because it is isolated from the app runtime (a wedged app can't stop backups), needs no
new Railway service, and is version-controlled. It reaches Postgres via Railway's public
TCP proxy connection string, held as an Actions secret.

**Implemented:** [`.github/workflows/db-backup.yml`](../.github/workflows/db-backup.yml)
(daily at 03:17 UTC + `workflow_dispatch`). The workflow hardens the sketch below into
production shape:

- **Version-matched client** — installs `postgresql-client-16` from PGDG (pinned to the
  Railway server major via the `PG_MAJOR` env) so `pg_dump` is always compatible.
- **Integrity gate before upload** — `pg_restore --list` must parse the archive, the dump
  must clear a size/TOC-entry floor, and a core table (`users`) must be present in the TOC.
  A truncated, empty, or wrong-database dump is rejected and never overwrites a good object.
- **Asymmetric encryption** — `age -r <public key>`; the runner holds only the public key.
- **Checksum + tiers** — uploads a `.sha256` sibling and promotes Sunday's dump to `weekly/`.
- **Least privilege + no overlap** — `permissions: contents: read`, a `db-backup`
  concurrency group, and a fail-loud precondition check on every required secret.
- **Dead-man's-switch** — an optional `BACKUP_HEARTBEAT_URL` ping on success, so a schedule
  that silently stops firing is detectable (a workflow that never runs raises no failure).

Required Actions secrets: `BACKUP_DATABASE_URL`, `BACKUP_AGE_PUBLIC_KEY`, `BACKUP_S3_BUCKET`,
`BACKUP_S3_KEY_ID`, `BACKUP_S3_SECRET`; optional `BACKUP_S3_ENDPOINT` (R2/B2),
`BACKUP_S3_REGION` (default `auto`), `BACKUP_HEARTBEAT_URL`.

Core of the flow (the workflow is the authoritative, hardened version):

```yaml
# .github/workflows/db-backup.yml (excerpt — see the file for the full, hardened job)
- run: |
    set -euo pipefail
    STAMP=$(date -u +%Y%m%dT%H%M%SZ); DUMP="t2b-${STAMP}.dump"
    pg_dump --format=custom --no-owner --no-privileges --dbname "$DSN" --file "$DUMP"
    pg_restore --list "$DUMP" >/dev/null              # integrity gate
    age -r "$AGE_PUBLIC_KEY" -o "$DUMP.age" "$DUMP"    # asymmetric encrypt at rest
    sha256sum "$DUMP.age" > "$DUMP.age.sha256"
    aws s3 cp "$DUMP.age" "s3://$S3_BUCKET/daily/$DUMP.age" --endpoint-url "$S3_ENDPOINT"
```

**Why encrypt (`age`, asymmetric):** dumps contain user PII (emails, workspace content).
User provider API keys are Fernet-encrypted *inside* the dump and stay encrypted (the
`ENCRYPTION_MASTER_KEY` is not in the dump), but PII is plaintext, so encrypt the whole
artifact at rest. Asymmetric `age` means the CI job only holds the **public** key — a
compromised Actions runner cannot decrypt existing backups. The private key lives in your
password manager / a sealed secret, used only at restore time.

## Retention (bounded, GDPR-aligned)

Backups holding PII must not live forever — they interact with the deletion promises in
[RETENTION_POLICY.md](RETENTION_POLICY.md) (30-day trash purge, 180-day legacy/eval window).

| Tier | Keep | Purpose |
|---|---|---|
| Daily | 14 days | Routine "oops" recovery. |
| Weekly (promote Sunday's dump) | 8 weeks | Corruption discovered late / migration regressions. |

- Total horizon ≈ 56 days — comfortably covers the 30-day trash window and a missed weekend,
  while bounded enough that a hard-deleted account's data ages out of backups within ~2 months.
  Document this bound so it is a defensible part of the retention story.
- Enforce via an S3/R2 **lifecycle rule** (expire `daily/` at 14d, `weekly/` at 56d) — no
  code, set once on the bucket.

## Restore procedures

Restore runs on a **Linux host** (a Railway shell, a Linux box, or the CI runner via a
`workflow_dispatch` drill) — never macOS. The steps below are automated by
[`scripts/backup/restore_backup.sh`](../scripts/backup/restore_backup.sh), which downloads,
verifies the `.sha256`, decrypts, validates the archive TOC, and restores under an
interactive confirmation guard. Run it directly, or follow the manual steps if you need to
deviate.

### A. Full restore (DR — lost or corrupted prod DB)
1. Provision a fresh Railway Postgres (or a scratch one to validate first).
2. One command does fetch → checksum → decrypt → validate → restore:
   ```bash
   scripts/backup/restore_backup.sh \
     --source s3://<bucket>/daily/t2b-<stamp>.dump.age \
     --identity /secure/age-private-key.txt \
     --target "$NEW_DATABASE_URL" \
     --endpoint-url "$BACKUP_S3_ENDPOINT"    # omit for AWS S3
   ```
   (Manual equivalent: `age -d -i key.txt file.age > file.dump` then
   `pg_restore --no-owner --no-privileges --clean --if-exists -d "$NEW_DATABASE_URL" file.dump`.)
3. Point the backend/worker `DATABASE_URL` at the restored DB; `alembic upgrade head`
   (expected no-op — the dump is already at head).
4. Run the production smoke (`scripts/production_smoke.py`) before taking traffic.
5. Rotate any secret you suspect was involved in the incident.

### B. Partial restore (single table / accidental data loss, prod still up)
1. Restore the dump into a **scratch** DB (steps A.1–A.3).
2. Selectively extract: `pg_restore -t <table> -a` from the dump into scratch, then
   `INSERT ... SELECT` / `COPY` the needed rows across, or `pg_dump -t <table> --data-only`
   from scratch → apply to prod inside a transaction. Never `--clean` a live prod table.

### C. Pre-migration backup (already in the runbook)
Before any risky/major migration, take an on-demand dump (trigger the workflow via
`workflow_dispatch`, or the `pg_dump` in [RUNBOOK.md](RUNBOOK.md) §"Schema Backup Before a
Major Migration"). Migrations already run automatically on deploy via `entrypoint.sh`.

## Restore drill (this is the part that's usually skipped — don't)

A backup you have never restored is a hypothesis, not a backup. Quarterly (and once before
Phase B launch):

1. `workflow_dispatch` the **DB Backup** workflow for a fresh dump.
2. Restore it into a throwaway scratch Postgres — `restore_backup.sh` prints the restore
   wall-clock, which validates the RTO target:
   ```bash
   scripts/backup/restore_backup.sh --source s3://<bucket>/daily/<latest>.age \
     --identity /secure/age-private-key.txt --target "$SCRATCH_DATABASE_URL" --yes
   ```
   To validate an artifact **without** a target DB, use `--verify-only` (decrypts and
   checks the archive TOC, touches no database).
3. Run the smoke script against an app instance pointed at the scratch DB.
4. Record: dump size, restore wall-clock (validates the RTO target), and pass/fail.
5. Tear down the scratch DB.

## Implementation checklist (Phase B, pre-public-launch)

Code is in the repo; the remaining items are one-time ops config on the platform side.

Code — done:
- [x] Backup workflow `.github/workflows/db-backup.yml` (integrity-gated, encrypted, tiered).
- [x] Restore/verify/drill helper `scripts/backup/restore_backup.sh`.
- [x] This doc linked from `PRODUCTION_RELEASE_GATE.md` and `GO_LIVE_RUNBOOK.md`.

Ops config — pending (no code):
- [ ] Enable + verify Railway managed backups (Layer 1).
- [ ] Create off-platform bucket (R2/B2/S3) with the lifecycle retention rules
      (expire `daily/` at 14d, `weekly/` at 56d).
- [ ] Generate the `age` keypair; store the **private** key in the password manager, add the
      **public** key + bucket creds + `BACKUP_DATABASE_URL` (+ optional endpoint/region/
      heartbeat) as Actions secrets.
- [ ] `workflow_dispatch` the workflow once; confirm the first artifact uploads.
- [ ] Do one full restore drill into a scratch DB; record RTO.
