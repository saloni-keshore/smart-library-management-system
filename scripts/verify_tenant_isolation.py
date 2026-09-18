"""Row-Level Security proof for a shared multi-tenant Supabase project (ADR-75).

This app moved from "one admin per Supabase project" (ADR-53) to a shared
database where many libraries self-register and are isolated from each
other by Postgres Row-Level Security, not merely by every query
remembering an `.eq("admin_id", ...)` filter. This script proves the RLS
policies themselves are doing the work - the one thing application-level
tests can't show, because they always go through routes/database query
functions that already filter correctly.

`tests/test_08_cross_tenant_isolation.py` is this script's complement: it
drives the real Flask app as two logged-in tenants and checks that neither
can view/edit/delete the other's records through the UI/routes - i.e. it
catches an application-code bug (a route or query helper that forgot to
scope by admin_id). This script instead builds a tenant-scoped Supabase
client directly (database.supabase_client.build_tenant_client()) and
queries a table with NO admin_id filter at all - if any row belonging to
the *other* seeded tenant comes back, RLS itself has failed, independent
of whether the application code above it is written correctly. Both checks
matter; neither replaces the other.

This script MUTATES data: it creates two throwaway admin accounts, seeds a
representative row in several tenant-owned tables for each, then deletes
both accounts and everything they own via rpc_delete_tenant_data() at the
end. Never point it at a project already holding real library data - only
a disposable dev/test Supabase project (same convention as
tests/conftest.py's warning about the pytest suite).

Usage (from the repository root, with a disposable dev project's .env or
.env.test already in place):

    python scripts/verify_tenant_isolation.py

Exits 0 if every check passes, 1 otherwise.
"""

import secrets
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from werkzeug.security import generate_password_hash  # noqa: E402

from database.supabase_client import (  # noqa: E402
    build_tenant_client,
    get_service_role_client,
)

# Tables checked directly for RLS denial - a representative spread across
# both "always had a direct admin_id column" (enquiries, students,
# cashbook, library_settings) and "only got one via the ADR-75 backfill"
# (memberships, payments), since those two groups have different FK shapes.
CHECKED_TABLES = ["enquiries", "students", "memberships", "payments", "cashbook", "library_settings"]


def _rand_suffix():
    return secrets.token_hex(4)


_ID_RETRIES = 6


def _insert_with_next_id(service_client, table, id_column, row):
    """Local copy of database/id_sequence.py's insert_with_next_id(), for use
    outside a Flask request context (this script has none, so it can't call
    get_supabase_client()). enquiries.enquiry_id and students.student_id have
    identity sequences that trail ordinary usage (ADR-15/TD-78) - every real
    route already assigns MAX(id)+1 itself instead of trusting the sequence;
    this script must do the same rather than relying on the table's default,
    or it collides with existing rows on any project that already has data."""
    from postgrest.exceptions import APIError

    last_error = None
    for _ in range(_ID_RETRIES):
        top = (
            service_client.table(table)
            .select(id_column)
            .order(id_column, desc=True)
            .limit(1)
            .execute()
        )
        next_id = (top.data[0][id_column] + 1) if top.data else 1
        try:
            return service_client.table(table).insert({**row, id_column: next_id}).execute().data[0]
        except APIError as error:
            details = error.args[0] if error.args else ""
            code = details.get("code") if isinstance(details, dict) else str(details)
            if "23505" not in (code or ""):
                raise
            last_error = error
    raise last_error


def _seed_tenant(service_client, label):
    """Creates one throwaway admin plus one row in each of CHECKED_TABLES,
    using the service-role client (bypasses RLS - this is setup, not the
    thing being tested). Returns the new admin_id."""

    suffix = _rand_suffix()
    admin_row = service_client.table("admins").insert({
        "full_name": f"RLS Check {label}",
        "username": f"rls_check_{label}_{suffix}",
        "mobile": "9" + suffix.ljust(9, "0")[:9],
        "email": f"rls_check_{label}_{suffix}@example.com",
        "password": generate_password_hash("RlsCheck123"),
        "role": "Admin",
    }).execute().data[0]
    admin_id = admin_row["admin_id"]

    enquiry = _insert_with_next_id(service_client, "enquiries", "enquiry_id", {
        "admin_id": admin_id,
        "full_name": f"Secret Enquiry {label}",
        "mobile": "8" + suffix.ljust(9, "0")[:9],
        "purpose": "Study",
        "preferred_shift": "Morning",
    })

    student = _insert_with_next_id(service_client, "students", "student_id", {
        "admin_id": admin_id,
        "enquiry_id": enquiry["enquiry_id"],
        "full_name": f"Secret Student {label}",
        "mobile": "7" + suffix.ljust(9, "0")[:9],
        "join_date": date.today().isoformat(),
        "status": "Active",
    })

    membership = _insert_with_next_id(service_client, "memberships", "membership_id", {
        "admin_id": admin_id,
        "student_id": student["student_id"],
        "plan_name": "Custom",
        "joining_date": date.today().isoformat(),
        "end_date": date.today().isoformat(),
        "total_fee": 500,
        "paid_amount": 500,
    })

    _insert_with_next_id(service_client, "payments", "payment_id", {
        "admin_id": admin_id,
        "membership_id": membership["membership_id"],
        "student_id": student["student_id"],
        "payment_mode": "Cash",
        "amount_paid": 500,
    })

    _insert_with_next_id(service_client, "cashbook", "entry_id", {
        "admin_id": admin_id,
        "type": "Income",
        "description": f"Secret Cashbook {label}",
        "amount": 500,
        "entry_date": date.today().isoformat(),
        "category": "Membership Fee",
    })

    _insert_with_next_id(service_client, "library_settings", "setting_id", {
        "admin_id": admin_id,
        "library_name": f"Secret Library {label}",
        "phone": "9" + suffix.ljust(9, "0")[:9],
    })

    return admin_id


def _assert_rls_denies_wrong_tenant(admin_id_a, admin_id_b):
    """The core proof: query every checked table as tenant A, with NO
    admin_id filter in the query at all, and confirm not one of tenant B's
    seeded rows comes back. If this ever fails, RLS is not enforcing
    isolation - only application code is, which is exactly the gap ADR-75
    closes."""

    client_a = build_tenant_client(admin_id_a)
    failures = []
    own_row_missing = []

    for table in CHECKED_TABLES:
        rows = client_a.table(table).select("admin_id").execute().data or []
        seen_admin_ids = {r["admin_id"] for r in rows}

        if admin_id_b in seen_admin_ids:
            failures.append(f"{table}: tenant B's row was visible to tenant A's client")
        if admin_id_a not in seen_admin_ids:
            # Not itself a leak, but means this check proved nothing for
            # this table - the client might be misconfigured rather than
            # RLS actually working.
            own_row_missing.append(table)

    return failures, own_row_missing


def _cleanup(admin_id_a, admin_id_b):
    """Deletes both seeded tenants via their own rpc_delete_tenant_data()
    RPC - exercising the real deletion path (ADR-76) as a side effect,
    rather than hand-rolling a second delete-order implementation here."""

    for admin_id in (admin_id_a, admin_id_b):
        try:
            build_tenant_client(admin_id).rpc("rpc_delete_tenant_data", {}).execute()
        except Exception as exc:  # noqa: BLE001 - best-effort cleanup, report and continue
            print(f"WARNING: cleanup failed for admin_id={admin_id}: {exc}")


def main():
    service_client = get_service_role_client()

    print("Seeding two throwaway tenants...")
    admin_id_a = _seed_tenant(service_client, "a")
    admin_id_b = _seed_tenant(service_client, "b")
    print(f"  tenant A admin_id={admin_id_a}, tenant B admin_id={admin_id_b}")

    try:
        failures, own_row_missing = _assert_rls_denies_wrong_tenant(admin_id_a, admin_id_b)
    finally:
        print("Cleaning up seeded tenants...")
        _cleanup(admin_id_a, admin_id_b)

    print()
    print(f"{'TABLE':<24}RESULT")
    print("-" * 60)
    any_failure = bool(failures)
    for table in CHECKED_TABLES:
        if any(table in f for f in failures):
            print(f"{table:<24}FAIL - tenant B's row was visible")
        elif table in own_row_missing:
            print(f"{table:<24}INCONCLUSIVE - tenant A's own row wasn't returned either")
        else:
            print(f"{table:<24}OK - RLS correctly hid tenant B's row")
    print("-" * 60)

    if failures:
        print("FAIL - Row-Level Security did not isolate tenants. Details:")
        for f in failures:
            print(f"  - {f}")
        return 1

    if own_row_missing:
        print(
            "INCONCLUSIVE - some tables never returned even the querying "
            "tenant's own row, so this run didn't actually prove RLS works "
            "for them. Check database/supabase_client.py's build_tenant_client() "
            "and that database/supabase_rls_migration.sql has been applied."
        )
        return 1

    print("PASS - Row-Level Security correctly isolated both tenants on every checked table.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
