#!/usr/bin/env python3
"""ENCRYPTION_MASTER_KEY rotation script.

Usage:
    python backend/scripts/rotate_encryption_key.py \\
        --old-key <BASE64_FERNET_OLD_KEY> \\
        --new-key <BASE64_FERNET_NEW_KEY> \\
        --database-url <POSTGRESQL_URL>

    # Preview without writing:
    python backend/scripts/rotate_encryption_key.py \\
        --old-key <OLD> --new-key <NEW> --database-url <URL> --dry-run

This script re-encrypts all rows in ``user_integrations.encrypted_token``
from the old Fernet key to the new one.  It is **IDEMPOTENT**: rows that are
already encrypted under the new key (i.e., a previous run succeeded for that
row) are silently skipped.  Safe to re-run after partial failures.

Exit codes:
    0 — all rows rotated (or already on new key)
    1 — argument error or database connection failure
    2 — partial failure (some rows could not be decrypted — inspect stderr)

NOTE: Requires ``cryptography`` (already a backend dependency) and
``psycopg2-binary`` for direct DB access (avoids the async SQLAlchemy layer).
Run from the repo root: ``cd backend && uv run python scripts/rotate_encryption_key.py``
"""

from __future__ import annotations

import argparse
import sys


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Rotate ENCRYPTION_MASTER_KEY for stored integration tokens"
    )
    p.add_argument("--old-key", required=True, help="Current Fernet key (base64)")
    p.add_argument("--new-key", required=True, help="New Fernet key (base64)")
    p.add_argument("--database-url", required=True, help="PostgreSQL connection URL")
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be rotated without writing",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()

    # --- Import cryptography ---
    try:
        from cryptography.fernet import Fernet, InvalidToken
    except ImportError:
        print(
            "ERROR: cryptography package not installed.  "
            "Run: pip install cryptography",
            file=sys.stderr,
        )
        return 1

    # --- Validate Fernet keys ---
    try:
        old_fernet = Fernet(args.old_key.encode())
        new_fernet = Fernet(args.new_key.encode())
    except Exception as exc:
        print(f"ERROR: Invalid Fernet key: {exc}", file=sys.stderr)
        return 1

    # --- Connect to database ---
    try:
        import psycopg2  # type: ignore[import-untyped]
    except ImportError:
        print(
            "ERROR: psycopg2 not installed.  " "Run: pip install psycopg2-binary",
            file=sys.stderr,
        )
        return 1

    try:
        conn = psycopg2.connect(args.database_url)
    except Exception as exc:
        print(f"ERROR: Could not connect to database: {exc}", file=sys.stderr)
        return 1

    # --- Fetch all encrypted rows ---
    # Table: user_integrations
    # Column: encrypted_token (Fernet-encrypted GitHub OAuth tokens)
    # See backend/migrations/versions/0007_github_integration.py
    cur = conn.cursor()
    cur.execute(
        "SELECT id, encrypted_token"
        " FROM user_integrations"
        " WHERE encrypted_token IS NOT NULL"
    )
    rows = cur.fetchall()

    rotated = 0
    skipped_already_new = 0
    failed = 0

    for row_id, enc_value in rows:
        # --- Idempotency check: try new key first ---
        # If decryption succeeds with the new key, this row is already rotated.
        try:
            new_fernet.decrypt(enc_value.encode())
            skipped_already_new += 1
            continue
        except InvalidToken:
            # Not decryptable with the new key ⇒ this row is not yet rotated;
            # fall through to the old-key decrypt below.
            pass

        # --- Decrypt with old key ---
        try:
            plaintext = old_fernet.decrypt(enc_value.encode())
        except InvalidToken:
            print(
                f"WARN: row {row_id}: cannot decrypt with old key — "
                "skipping (manual inspection required)",
                file=sys.stderr,
            )
            failed += 1
            continue

        # --- Re-encrypt with new key ---
        new_enc = new_fernet.encrypt(plaintext).decode()

        if args.dry_run:
            print(f"DRY-RUN: would rotate row {row_id}")
        else:
            cur.execute(
                "UPDATE user_integrations" " SET encrypted_token = %s" " WHERE id = %s",
                (new_enc, row_id),
            )
        rotated += 1

    if not args.dry_run:
        conn.commit()

    conn.close()

    label = "DRY-RUN " if args.dry_run else ""
    print(
        f"{label}Done. "
        f"rotated={rotated} "
        f"skipped_already_new={skipped_already_new} "
        f"failed={failed}"
    )

    return 2 if failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
