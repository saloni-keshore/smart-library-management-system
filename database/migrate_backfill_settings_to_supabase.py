"""
One-time backfill: sync every SQLite row in the four Settings-owned tables
(`library_settings`, `membership_settings`, `backup_log`, `security_settings`)
into their existing Supabase counterparts.

Unlike `database/migrate_to_supabase.py` (which requires every destination
table to be empty before it runs), these four Supabase tables already hold a
partial copy from that earlier one-time import (ADR-15) - every write since
then has gone to SQLite only, so SQLite is the more current copy for rows
that exist in both. This script closes that gap with a plain upsert, keyed
on `admin_id` (which is `UNIQUE` on both sides, one row per admin - unlike
the append-only ledgers `enquiries`/`students`/`memberships`/`cashbook`/
`payments`, there is no ordering/identity-sequence concern here, so this
script does not need those migrations' explicit-id/sequence-reset machinery).

Run once from the project root, before flipping any of the four
`database/*_queries.py` modules over to Supabase:

    python database/migrate_backfill_settings_to_supabase.py

For each table, this script:
  1. Reads every row from the SQLite table (never writes to library.db).
  2. Drops the SQLite-only primary key column (`setting_id`/`log_id`) from
     each row - Supabase assigns its own, and nothing anywhere reads these
     tables by that column, only by `admin_id`.
  3. Upserts the remaining rows into Supabase in batches, `on_conflict="admin_id"`
     - inserting admins that don't have a Supabase row yet, and overwriting
       Supabase's stale copy for admins that do (SQLite wins, since it is
       the table every `database/*_queries.py` module has been writing to).
  4. Verifies the Supabase row count now matches the SQLite row count.

Reads SUPABASE_URL / SUPABASE_SECRET_KEY from .env, same as
database/migrate_to_supabase.py and database/supabase_client.py.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv
from postgrest import APIError

from database.supabase_client import get_supabase_client

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SQLITE_PATH = Path(__file__).resolve().parent / "library.db"

# (table_name, sqlite_primary_key_column) - the primary key is dropped from
# every row before upserting, since Supabase assigns its own and nothing
# reads these tables by it.
TABLES = [
    ("library_settings", "setting_id"),
    ("membership_settings", "setting_id"),
    ("backup_log", "log_id"),
    ("security_settings", "setting_id"),
]

BATCH_SIZE = 500


class MigrationError(Exception):
    """Raised to abort the migration immediately with a clear message."""


def get_sqlite_connection() -> sqlite3.Connection:
    if not SQLITE_PATH.exists():
        raise MigrationError(f"SQLite database not found at {SQLITE_PATH}")
    conn = sqlite3.connect(str(SQLITE_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def fetch_sqlite_rows(conn: sqlite3.Connection, table: str, pk_column: str) -> list[dict]:
    cursor = conn.execute(f"SELECT * FROM {table}")
    rows = []
    for row in cursor.fetchall():
        row_dict = dict(row)
        row_dict.pop(pk_column, None)
        rows.append(row_dict)
    return rows


def upsert_rows(supabase, table: str, rows: list[dict]) -> None:
    for start in range(0, len(rows), BATCH_SIZE):
        chunk = rows[start:start + BATCH_SIZE]
        try:
            supabase.table(table).upsert(chunk, on_conflict="admin_id").execute()
        except APIError as exc:
            raise MigrationError(
                f"Upsert into '{table}' failed on rows "
                f"{start}-{start + len(chunk) - 1}: {exc}"
            ) from exc


def get_remote_count(supabase, table: str) -> int:
    response = supabase.table(table).select("*", count="exact", head=True).execute()
    return response.count or 0


def run(skip_confirm: bool) -> int:
    load_dotenv(dotenv_path=PROJECT_ROOT / ".env")
    conn = get_sqlite_connection()
    supabase = get_supabase_client()

    if not skip_confirm:
        answer = input(
            "This will upsert every SQLite row in library_settings/"
            "membership_settings/backup_log/security_settings into their "
            "Supabase counterparts (SQLite wins on conflict). Continue? [y/N] "
        ).strip().lower()
        if answer != "y":
            print("Aborted by user.")
            return 1

    report: list[tuple[str, int, int, bool]] = []

    for table, pk_column in TABLES:
        print(f"--- {table} ---")
        rows = fetch_sqlite_rows(conn, table, pk_column)
        sqlite_count = len(rows)

        if sqlite_count == 0:
            print("  No rows in SQLite -- skipping.")
            report.append((table, 0, 0, True))
            continue

        try:
            upsert_rows(supabase, table, rows)
            remote_count = get_remote_count(supabase, table)
        except MigrationError as exc:
            report.append((table, sqlite_count, 0, False))
            print(f"\nERROR: {exc}")
            print("\nAborting immediately -- later tables were NOT migrated.")
            conn.close()
            return 1

        verified = remote_count >= sqlite_count
        report.append((table, sqlite_count, remote_count, verified))
        print(f"  Upserted {sqlite_count} row(s); Supabase now has {remote_count}.")

    conn.close()

    print("\n=== Migration Report ===")
    header = f"{'Table':<24}{'SQLite':>8}{'Supabase':>10}{'Verified':>10}"
    print(header)
    print("-" * len(header))
    for table, sqlite_count, remote_count, verified in report:
        print(f"{table:<24}{sqlite_count:>8}{remote_count:>10}{'OK' if verified else 'FAIL':>10}")

    return 0 if all(r[3] for r in report) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Skip the confirmation prompt (for non-interactive runs).",
    )
    args = parser.parse_args()

    try:
        return run(skip_confirm=args.yes)
    except MigrationError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
