#!/usr/bin/env bash
#
# restore_backup.sh — restore (or verify) an off-platform encrypted PostgreSQL
# backup produced by .github/workflows/db-backup.yml.
#
# This automates Procedure A (full restore) and the quarterly restore drill from
# docs/BACKUP_RESTORE.md so the RTO target is measured, not hypothetical.
#
# It intentionally does NOT handle Procedure B (single-table surgery into a live
# prod DB) — that is deliberately manual. Restore here targets a FRESH or SCRATCH
# database.
#
# Usage:
#   restore_backup.sh --source <s3://bucket/daily/x.dump.age | /path/x.dump.age> \
#                     --identity <age-private-key-file> \
#                     --target <postgresql://user:pass@host:port/dbname> \
#                     [--endpoint-url <s3-endpoint>] [--verify-only] [--yes]
#
# Options:
#   --source        s3:// URL or local path to the encrypted (.age) artifact.
#   --identity      Path to the age private key file (kept in the password
#                   manager; never in CI). Required unless --verify-only with a
#                   plaintext .dump source.
#   --target        Destination libpq DSN. The restore uses --clean --if-exists,
#                   so point it at a fresh/scratch DB, never live prod.
#   --endpoint-url  S3-compatible endpoint (R2/B2). Omit for AWS S3. Env
#                   AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY/AWS_DEFAULT_REGION
#                   must be set for an s3:// source.
#   --verify-only   Decrypt and validate the archive TOC, then stop. No DB is
#                   touched. Safe to run against any artifact.
#   --yes           Skip the interactive confirmation before writing to --target.
#
# Runtime: a Linux host with bash 5 + GNU coreutils — the GitHub Actions
# ubuntu runner (via workflow_dispatch of a drill), a Railway shell, or any
# Linux box. It uses GNU tools (sha256sum) and is not intended to run on macOS.
#
# Requires: age, pg_restore (matching the server major), and — for s3:// sources
# — the aws CLI and sha256sum.

set -euo pipefail

die() {
  echo "error: $*" >&2
  exit 1
}

SOURCE=""
IDENTITY=""
TARGET=""
ENDPOINT=""
VERIFY_ONLY=0
ASSUME_YES=0

while [ $# -gt 0 ]; do
  case "$1" in
    --source) SOURCE="${2:-}"; shift 2 ;;
    --identity) IDENTITY="${2:-}"; shift 2 ;;
    --target) TARGET="${2:-}"; shift 2 ;;
    --endpoint-url) ENDPOINT="${2:-}"; shift 2 ;;
    --verify-only) VERIFY_ONLY=1; shift ;;
    --yes) ASSUME_YES=1; shift ;;
    -h|--help)
      sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) die "unknown argument: $1" ;;
  esac
done

[ -n "$SOURCE" ] || die "--source is required"
if [ "$VERIFY_ONLY" -eq 0 ]; then
  [ -n "$TARGET" ] || die "--target is required (or pass --verify-only)"
fi

command -v age >/dev/null 2>&1 || die "age not found on PATH"
command -v pg_restore >/dev/null 2>&1 || die "pg_restore not found on PATH"

# Scratch workspace; wiped on any exit so decrypted plaintext never lingers.
WORK="$(mktemp -d)"
cleanup() { rm -rf "$WORK"; }
trap cleanup EXIT

# ---- 1. Fetch the artifact (and its checksum) locally.
if [[ "$SOURCE" == s3://* ]]; then
  command -v aws >/dev/null 2>&1 || die "aws CLI not found (needed for an s3:// source)"
  command -v sha256sum >/dev/null 2>&1 || die "sha256sum not found"
  ep=()
  [ -n "$ENDPOINT" ] && ep=(--endpoint-url "$ENDPOINT")
  base="$(basename "$SOURCE")"
  echo "Downloading $SOURCE ..."
  aws s3 cp "$SOURCE" "$WORK/$base" "${ep[@]}" --only-show-errors
  # Verify the sibling checksum if it exists; a storage-corrupted artifact must
  # not silently reach pg_restore.
  if aws s3 cp "${SOURCE}.sha256" "$WORK/$base.sha256" "${ep[@]}" --only-show-errors 2>/dev/null; then
    echo "Verifying checksum ..."
    ( cd "$WORK" && sed "s#[^ ]*\$#$base#" "$base.sha256" | sha256sum -c - ) \
      || die "checksum mismatch — artifact is corrupt"
  else
    echo "warning: no .sha256 sibling found; skipping checksum verification" >&2
  fi
  ARTIFACT="$WORK/$base"
else
  [ -f "$SOURCE" ] || die "source file not found: $SOURCE"
  ARTIFACT="$SOURCE"
  if [ -f "${SOURCE}.sha256" ]; then
    echo "Verifying checksum ..."
    ( cd "$(dirname "$SOURCE")" && sha256sum -c "$(basename "$SOURCE").sha256" ) \
      || die "checksum mismatch — artifact is corrupt"
  fi
fi

# ---- 2. Decrypt (unless already a plaintext .dump).
if [[ "$ARTIFACT" == *.age ]]; then
  [ -n "$IDENTITY" ] || die "--identity is required to decrypt an .age artifact"
  [ -f "$IDENTITY" ] || die "identity file not found: $IDENTITY"
  DUMP="$WORK/restore.dump"
  echo "Decrypting ..."
  age -d -i "$IDENTITY" -o "$DUMP" "$ARTIFACT"
else
  DUMP="$ARTIFACT"
fi

# ---- 3. Validate the archive before touching any database.
echo "Validating archive TOC ..."
pg_restore --list "$DUMP" > "$WORK/toc.txt" || die "archive is unreadable — restore aborted"
entries="$(wc -l < "$WORK/toc.txt")"
echo "archive OK: $entries TOC entries"

if [ "$VERIFY_ONLY" -eq 1 ]; then
  echo "verify-only: archive is valid and restorable. No database was modified."
  exit 0
fi

# ---- 4. Confirm the destination. --clean --if-exists DROPS existing objects,
# so make an accidental prod target hard to hit.
target_display="$(printf '%s' "$TARGET" | sed -E 's#(://[^:/@]+):[^@/]*@#\1:***@#')"
echo
echo "About to restore into:"
echo "    $target_display"
echo "This uses 'pg_restore --clean --if-exists' and will DROP and recreate the"
echo "objects in that database. It must be a FRESH or SCRATCH database."
if [ "$ASSUME_YES" -ne 1 ]; then
  printf "Type 'yes' to proceed: "
  read -r reply
  [ "$reply" = "yes" ] || die "aborted by operator"
fi

# ---- 5. Restore. --exit-on-error surfaces the first failure instead of limping
# to a half-restored DB; single connection keeps ordering deterministic.
echo "Restoring ..."
start="$(date +%s)"
pg_restore \
  --no-owner --no-privileges \
  --clean --if-exists \
  --exit-on-error \
  --dbname "$TARGET" \
  "$DUMP"
elapsed="$(( $(date +%s) - start ))"

echo
echo "Restore complete in ${elapsed}s."
echo "Next: run 'alembic upgrade head' (expected no-op) and the production smoke"
echo "(scripts/production_smoke.py) before taking traffic. See docs/BACKUP_RESTORE.md."
