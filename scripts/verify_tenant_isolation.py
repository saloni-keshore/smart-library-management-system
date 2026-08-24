"""Post-provisioning data-isolation check for one Supabase project (ADR-53).

Under the one-deployment-per-library pilot model, isolation between
libraries is a deployment/configuration problem, not an application-layer
one: each library has its own Supabase project, so "no other library's data
in this database" should be true by construction. This script exists to
*verify* that construction actually held for a freshly provisioned project -
catching exactly the failure mode the rest of this fix doesn't touch: an
operator who pasted the wrong SUPABASE_URL/SUPABASE_SECRET_KEY into this
deployment's .env and is unknowingly looking at a different project (a
stale local one, or - worst case - another library's).

`tests/conftest.py` has no mocking and no teardown, so the real pytest
suite is unsafe to run against a freshly provisioned, production-intended
project - it would permanently seed random test data into it. This script
is read-only and safe to run against a real project at any time.

Usage (from the repository root, with this deployment's own .env already in
place - see docs/PROVISIONING.md):

    # Before any admin has registered - every table must be empty.
    python scripts/verify_tenant_isolation.py

    # After Step E's first-admin registration - every row must belong to
    # that one admin (or, for FK-only tables, transitively belong to them).
    python scripts/verify_tenant_isolation.py --expected-admin-id 1

Exits 0 if the project contains only what's expected, 1 otherwise.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.supabase_client import get_supabase_client  # noqa: E402


# Tables with their own admin_id column - checked directly.
DIRECT_ADMIN_TABLES = [
    "enquiries",
    "students",
    "cashbook",
    "expenses",
    "audit_log",
    "library_settings",
    "membership_settings",
    "backup_log",
    "security_settings",
    "ai_center_settings",
    "panda_conversations",
]

# Tables with no admin_id column of their own - ownership is checked
# transitively through a parent table's admin_id, the same "no
# server-side JOIN, fetch-and-filter-in-Python" shape
# database/payment_queries.py's get_payments_for_admin() already uses.
FK_SCOPED_TABLES = {
    # table_name: (fk_column, parent_table, parent_id_column)
    "memberships": ("student_id", "students", "student_id"),
    "payments": ("student_id", "students", "student_id"),
    "panda_messages": ("conversation_id", "panda_conversations", "conversation_id"),
}

# Legacy/unused tables (confirmed by the pre-deployment audit: no live code
# path reads or writes them) - reported for visibility only, never asserted
# against, since they carry no per-admin ownership concept in the schema.
UNSCOPED_LEGACY_TABLES = ["settings", "transactions"]


_PAGE_SIZE = 1000


def _fetch_all(supabase, table_name, columns="*"):
    """Every row in table_name, paginated with .range() - PostgREST caps a
    single request at a server-configured max page size (commonly 1000
    rows), so a plain .select(columns).execute() silently truncates on any
    table larger than that instead of raising. This matters here even
    though the intended target (a freshly provisioned, near-empty pilot
    project) is unlikely to ever hit that cap - a leak-detection script
    that silently under-reports on a larger project is worse than one that
    is merely slower."""

    rows = []
    start = 0
    while True:
        resp = (
            supabase.table(table_name)
            .select(columns)
            .range(start, start + _PAGE_SIZE - 1)
            .execute()
        )
        page = resp.data or []
        rows.extend(page)
        if len(page) < _PAGE_SIZE:
            break
        start += _PAGE_SIZE
    return rows


def _check_admins_table(supabase, expected_admin_id):
    rows = _fetch_all(supabase, "admins", "admin_id")
    ids = {r["admin_id"] for r in rows}

    if expected_admin_id is None:
        if not ids:
            return "OK", "empty, as expected before first admin registration"
        return "FAIL", f"expected no admins yet, found admin_id(s) {sorted(ids)}"

    if ids == {expected_admin_id}:
        return "OK", f"exactly the expected admin_id {expected_admin_id}"
    unexpected = ids - {expected_admin_id}
    if unexpected:
        return "FAIL", f"found unexpected admin_id(s) {sorted(unexpected)}"
    return "OK", "no rows"


def _check_direct_table(supabase, table_name, expected_admin_id):
    rows = _fetch_all(supabase, table_name, "admin_id")
    if not rows:
        return "OK", "empty"

    if expected_admin_id is None:
        return "FAIL", f"expected empty (no admin registered yet), found {len(rows)} row(s)"

    ids = {r["admin_id"] for r in rows}
    unexpected = ids - {expected_admin_id}
    if unexpected:
        return "FAIL", f"found admin_id(s) {sorted(unexpected)} - not the expected {expected_admin_id}"
    return "OK", f"{len(rows)} row(s), all admin_id={expected_admin_id}"


def _check_fk_scoped_table(supabase, table_name, fk_column, parent_table, parent_id_column, expected_admin_id):
    rows = _fetch_all(supabase, table_name, fk_column)
    if not rows:
        return "OK", "empty"

    if expected_admin_id is None:
        return "FAIL", f"expected empty (no admin registered yet), found {len(rows)} row(s)"

    parent_rows = supabase.table(parent_table).select(parent_id_column).eq(
        "admin_id", expected_admin_id
    ).execute().data or []
    allowed_ids = {r[parent_id_column] for r in parent_rows}

    fk_values = {r[fk_column] for r in rows if r.get(fk_column) is not None}
    unexpected = fk_values - allowed_ids
    if unexpected:
        return (
            "FAIL",
            f"found {fk_column} value(s) {sorted(unexpected)} not owned by "
            f"admin_id={expected_admin_id} via {parent_table}",
        )
    return "OK", f"{len(rows)} row(s), all traced back to admin_id={expected_admin_id}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--expected-admin-id",
        type=int,
        default=None,
        help=(
            "The one admin_id this project should contain data for "
            "(Step E of docs/PROVISIONING.md). Omit to assert the project "
            "is still completely empty (Step D, before first registration)."
        ),
    )
    args = parser.parse_args()

    supabase = get_supabase_client()
    expected_admin_id = args.expected_admin_id

    results = []
    status, detail = _check_admins_table(supabase, expected_admin_id)
    results.append(("admins", status, detail))

    for table_name in DIRECT_ADMIN_TABLES:
        status, detail = _check_direct_table(supabase, table_name, expected_admin_id)
        results.append((table_name, status, detail))

    for table_name, (fk_column, parent_table, parent_id_column) in FK_SCOPED_TABLES.items():
        status, detail = _check_fk_scoped_table(
            supabase, table_name, fk_column, parent_table, parent_id_column, expected_admin_id
        )
        results.append((table_name, status, detail))

    for table_name in UNSCOPED_LEGACY_TABLES:
        rows = _fetch_all(supabase, table_name)
        results.append((table_name, "INFO", f"{len(rows)} row(s) - legacy table, not asserted"))

    print(f"{'TABLE':<24}{'STATUS':<8}DETAIL")
    print("-" * 70)
    any_failure = False
    for table_name, status, detail in results:
        if status == "FAIL":
            any_failure = True
        print(f"{table_name:<24}{status:<8}{detail}")

    print("-" * 70)
    if any_failure:
        print(
            "FAIL - this project contains data that doesn't match the "
            "expected single library. Double-check SUPABASE_URL/"
            "SUPABASE_SECRET_KEY in this deployment's .env before going "
            "live - see docs/PROVISIONING.md."
        )
        return 1

    print("PASS - this project's data is consistent with one clean library.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
