"""
One-time backfill: bring Supabase `enquiries`/`students`/`memberships`/
`payments` up to full parity with SQLite, inserting only the rows Supabase
is missing (never touching a row that already exists on both sides).

Discovered while backfilling `payments` for the Payments migration slice:
Supabase's `memberships` was missing 339 rows SQLite has, `students` was
missing 433, and `enquiries` was missing 493 - none of the four ADR-18/19/20
route-level cutovers or the two backfill scripts before this one caught it,
because every one of them only guarantees parity *going forward* from the
moment a route started dual-writing. Any row created before that moment,
and never edited since (so no post-migration write ever re-synced it), was
never copied - the original one-time bulk import (ADR-15,
`database/migrate_to_supabase.py`) only ran once, before these tables had
accumulated their full history. `admins` has zero gap (every SQLite
admin_id already exists in Supabase), so it's not part of this script.

This matters beyond the Payments migration: any Supabase read of
`students`/`memberships`/`enquiries` (Dashboard, Membership Distribution,
Notifications, BI, Enquiries, Students - everything migrated by ADR-18
through ADR-23) has been silently missing these rows since the day each
table's reads cut over to Supabase. Running this script closes that gap for
all of them, not just for unblocking the payments backfill.

Run once from the project root, in this exact order (each table's rows can
reference an earlier table's row, so order matters - same reasoning as
`database/migrate_to_supabase.py`'s TABLES_IN_ORDER):

    python -m database.migrate_backfill_mirror_parity

For each of `enquiries`, `students`, `memberships`, `payments` in turn, this
script finds every `payment_id`/`membership_id`/`student_id`/`enquiry_id`
that exists in SQLite but not in Supabase, fetches those rows' full SQLite
data, and inserts them into Supabase preserving the exact id - the same
explicit-id reasoning ADR-18/19/20/22 already established for these exact
columns. Existing Supabase rows are never updated, only ever supplemented.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv
from postgrest import APIError

from database.supabase_client import get_supabase_client

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SQLITE_PATH = Path(__file__).resolve().parent / "library.db"

BATCH_SIZE = 500

# (table, pk_column) in FK-safe order - each table only references a table
# earlier in this list (plus admins, already at full parity).
TABLES_IN_ORDER = [
    ("enquiries", "enquiry_id"),
    ("students", "student_id"),
    ("memberships", "membership_id"),
    ("payments", "payment_id"),
]

# Columns typed DATE/TIMESTAMP in supabase_migration.sql, per table - same
# list database/migrate_to_supabase.py uses, needed here for the same
# reason: SQLite's dynamic typing let invalid strings (e.g. "not-a-date")
# into columns Postgres enforces as real DATE/TIMESTAMP values.
TEMPORAL_COLUMNS: dict[str, list[str]] = {
    "enquiries": ["followup_date", "created_at"],
    "students": ["join_date", "created_at"],
    "memberships": ["joining_date", "end_date", "created_at"],
    "payments": ["payment_date", "created_at"],
}

NULL_TOKENS = {"", "none", "null"}


def _is_valid_iso_temporal(text: str) -> bool:
    try:
        date.fromisoformat(text)
        return True
    except ValueError:
        pass
    try:
        datetime.fromisoformat(text)
        return True
    except ValueError:
        return False


def sanitize_temporal_value(value):
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in NULL_TOKENS:
        return None
    if _is_valid_iso_temporal(text):
        return text
    return None


def sanitize_row(table: str, row: dict) -> dict:
    columns = TEMPORAL_COLUMNS.get(table, [])
    if not columns:
        return row
    sanitized = dict(row)
    for column in columns:
        if column in sanitized:
            sanitized[column] = sanitize_temporal_value(sanitized[column])
    return sanitized


class MigrationError(Exception):
    """Raised to abort the migration immediately with a clear message."""


def get_sqlite_connection() -> sqlite3.Connection:
    if not SQLITE_PATH.exists():
        raise MigrationError(f"SQLite database not found at {SQLITE_PATH}")
    conn = sqlite3.connect(str(SQLITE_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def fetch_sqlite_ids(conn: sqlite3.Connection, table: str, pk_column: str) -> set[int]:
    return {row[0] for row in conn.execute(f"SELECT {pk_column} FROM {table}")}


def fetch_sqlite_rows_by_id(conn: sqlite3.Connection, table: str, pk_column: str, ids: set[int]) -> list[dict]:
    if not ids:
        return []
    rows = []
    id_list = list(ids)
    chunk_size = 500
    for start in range(0, len(id_list), chunk_size):
        chunk = id_list[start:start + chunk_size]
        placeholders = ",".join("?" * len(chunk))
        cursor = conn.execute(f"SELECT * FROM {table} WHERE {pk_column} IN ({placeholders})", chunk)
        rows.extend(dict(row) for row in cursor.fetchall())
    return rows


def fetch_supabase_ids(supabase, table: str, pk_column: str) -> set[int]:
    ids: set[int] = set()
    page_size = 1000
    start = 0
    while True:
        response = (
            supabase.table(table)
            .select(pk_column)
            .range(start, start + page_size - 1)
            .execute()
        )
        rows = response.data
        ids.update(row[pk_column] for row in rows)
        if len(rows) < page_size:
            break
        start += page_size
    return ids


def insert_rows(supabase, table: str, rows: list[dict]) -> None:
    for start in range(0, len(rows), BATCH_SIZE):
        chunk = rows[start:start + BATCH_SIZE]
        try:
            supabase.table(table).insert(chunk).execute()
        except APIError as exc:
            raise MigrationError(
                f"Insert into '{table}' failed on rows {start}-{start + len(chunk) - 1}: {exc}"
            ) from exc


def run(skip_confirm: bool) -> int:
    load_dotenv(dotenv_path=PROJECT_ROOT / ".env")
    conn = get_sqlite_connection()
    supabase = get_supabase_client()

    plan = []
    for table, pk_column in TABLES_IN_ORDER:
        sqlite_ids = fetch_sqlite_ids(conn, table, pk_column)
        supabase_ids = fetch_supabase_ids(supabase, table, pk_column)
        missing_ids = sqlite_ids - supabase_ids
        plan.append((table, pk_column, missing_ids))
        print(f"{table}: SQLite {len(sqlite_ids)}, Supabase {len(supabase_ids)}, missing {len(missing_ids)}")

    total_missing = sum(len(missing) for _, _, missing in plan)
    if total_missing == 0:
        print("\nNothing to do - Supabase already has full parity with SQLite for all four tables.")
        conn.close()
        return 0

    if not skip_confirm:
        answer = input(
            f"\nThis will insert {total_missing} row(s) total across "
            f"enquiries/students/memberships/payments into Supabase, "
            f"preserving each row's exact id. Continue? [y/N] "
        ).strip().lower()
        if answer != "y":
            print("Aborted by user.")
            conn.close()
            return 1

    for table, pk_column, missing_ids in plan:
        if not missing_ids:
            print(f"--- {table}: nothing to backfill ---")
            continue
        print(f"--- {table}: backfilling {len(missing_ids)} row(s) ---")
        rows = fetch_sqlite_rows_by_id(conn, table, pk_column, missing_ids)
        rows = [sanitize_row(table, row) for row in rows]
        try:
            insert_rows(supabase, table, rows)
        except MigrationError as exc:
            print(f"\nERROR: {exc}")
            print("Aborting immediately - later tables were NOT backfilled.")
            conn.close()
            return 1
        print(f"  Inserted {len(rows)} row(s).")

    conn.close()

    print("\n=== Verification ===")
    all_ok = True
    for table, pk_column in TABLES_IN_ORDER:
        conn2 = get_sqlite_connection()
        sqlite_count = len(fetch_sqlite_ids(conn2, table, pk_column))
        conn2.close()
        supabase_count = len(fetch_supabase_ids(supabase, table, pk_column))
        ok = supabase_count >= sqlite_count
        all_ok = all_ok and ok
        print(f"{table}: SQLite {sqlite_count}, Supabase {supabase_count} - {'OK' if ok else 'MISMATCH'}")

    return 0 if all_ok else 1


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
