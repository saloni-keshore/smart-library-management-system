"""Pre-go-live schema check for one Supabase project (TD-53/TD-55, ADR-53).

Every pilot library, under the one-deployment-per-library model, gets its
own fresh Supabase project. `database/supabase_migration.sql` creates every
table this app needs when run once in that project's SQL Editor - but this
app has no exec_sql/DDL RPC and no direct-Postgres path (ADR-14), so nothing
in the codebase can *verify* the script was actually run, or run in full,
except by trying to read each table it should have created.

This script does that: for every table the app depends on, it issues a
read-only, zero-row existence probe (`select(...).limit(1)`) against
whichever Supabase project this process's SUPABASE_URL/SUPABASE_SECRET_KEY
currently point to (the same client the app itself uses -
database/supabase_client.py) and reports OK / MISSING / ERROR per table.

Usage (from the repository root, with this deployment's own .env already in
place - see docs/PROVISIONING.md):

    python scripts/verify_schema.py

Exits 0 if every table is reachable, 1 otherwise - safe to use as a go-live
gate, not just an interactive check.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from postgrest.exceptions import APIError  # noqa: E402

from database.supabase_client import get_supabase_client  # noqa: E402


# Every table database/supabase_migration.sql creates, in the order it
# creates them. `settings`, `expenses`, and `transactions` are legacy/unused
# by any live code path (confirmed during the pre-deployment audit) but are
# still listed here - a missing legacy table isn't a functional problem, but
# an operator should still see it reported rather than silently skipped.
ALL_TABLES = [
    "admins",
    "settings",
    "enquiries",
    "students",
    "memberships",
    "payments",
    "cashbook",
    "expenses",
    "transactions",
    "audit_log",
    "library_settings",
    "membership_settings",
    "backup_log",
    "security_settings",
    "ai_center_settings",
    "panda_conversations",
    "panda_messages",
]

# These four need a manual CREATE TABLE/ALTER TABLE step even on a project
# that already ran the base migration (TD-53/TD-55/TD-58/ADR-53) - flagged
# explicitly in the report below since they're the tables most likely to be
# missing on an otherwise-working project.
KNOWN_MANUAL_STEP_TABLES = {
    "ai_center_settings",
    "panda_conversations",
    "panda_messages",
}


def _probe_table(supabase, table_name):
    try:
        resp = (
            supabase.table(table_name)
            .select("*", count="exact", head=True)
            .limit(1)
            .execute()
        )
        return "OK", resp.count if resp.count is not None else 0
    except APIError as error:
        details = error.args[0] if error.args else ""
        code = details.get("code") if isinstance(details, dict) else str(details)
        if code and "PGRST205" in code:
            return "MISSING", None
        return "ERROR", str(details)


def main():
    supabase = get_supabase_client()

    results = []
    for table_name in ALL_TABLES:
        status, detail = _probe_table(supabase, table_name)
        results.append((table_name, status, detail))

    print(f"{'TABLE':<24}{'STATUS':<10}DETAIL")
    print("-" * 60)
    any_problem = False
    for table_name, status, detail in results:
        if status == "OK":
            print(f"{table_name:<24}{status:<10}{detail} row(s)")
        elif status == "MISSING":
            any_problem = True
            note = " (manual CREATE TABLE step required)" if table_name in KNOWN_MANUAL_STEP_TABLES else ""
            print(f"{table_name:<24}{status:<10}table not found{note}")
        else:
            any_problem = True
            print(f"{table_name:<24}{status:<10}{detail}")

    print("-" * 60)
    if any_problem:
        print(
            "FAIL - one or more tables are missing or unreachable. Run "
            "database/supabase_migration.sql (and any manual ALTER/CREATE "
            "steps documented inline in that file) against this project "
            "before go-live. See docs/PROVISIONING.md."
        )
        return 1

    print("PASS - every table is reachable on this Supabase project.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
