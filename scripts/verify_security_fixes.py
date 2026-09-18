"""Proof for the three fixes in database/supabase_security_fixes_migration.sql
(ADR-77), run against a live Supabase project - same convention as
scripts/verify_tenant_isolation.py: throwaway admin accounts only, cleaned
up (or left archived+data-wiped, never left as a live extra login) at the
end. Never touches an existing admin_id, so it's safe to run against
smart-library-pilot-asti without affecting saloni (admin_id=2) or any real
account - it only ever creates and deletes accounts of its own.

Usage (from the repository root, with .env pointed at the project the
migration was just applied to):

    python scripts/verify_security_fixes.py

Exits 0 if every check passes, 1 otherwise.
"""

import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from postgrest.exceptions import APIError  # noqa: E402
from werkzeug.security import check_password_hash, generate_password_hash  # noqa: E402

from database.supabase_client import (  # noqa: E402
    build_anon_client,
    build_tenant_client,
    get_service_role_client,
)

_checks = []


def _check(name, condition, detail=""):
    _checks.append((name, bool(condition), detail))
    status = "OK" if condition else "FAIL"
    print(f"  [{status}] {name}" + (f" - {detail}" if detail and not condition else ""))


def _rand_suffix():
    return secrets.token_hex(4)


def _seed_admin(service_client, label, password="SeedPass123", full_name=None):
    """Inserts a throwaway admin directly (service-role, bypasses RLS - this
    is setup) with a legacy werkzeug-scrypt hash, matching the format every
    real pre-fix account is still in. Returns (admin_id, username, mobile,
    full_name, password)."""
    suffix = _rand_suffix()
    username = f"secfix_{label}_{suffix}"
    mobile = "9" + suffix.ljust(9, "0")[:9]
    full_name = full_name or f"SecFix {label.title()} {suffix}"
    row = service_client.table("admins").insert({
        "full_name": full_name,
        "username": username,
        "mobile": mobile,
        "email": f"{username}@example.com",
        "password": generate_password_hash(password),
        "role": "Admin",
    }).execute().data[0]
    return row["admin_id"], username, mobile, full_name, password


def _cleanup(service_client, admin_ids):
    for admin_id in admin_ids:
        try:
            # library_settings.admin_id FKs to admins - delete any seeded
            # child row first (only check_archived_session_access seeds
            # one; a no-op delete for every other caller) so the admins
            # delete below doesn't fail on a foreign-key violation.
            service_client.table("library_settings").delete().eq("admin_id", admin_id).execute()
            service_client.table("admins").delete().eq("admin_id", admin_id).execute()
        except Exception as exc:  # noqa: BLE001 - best-effort cleanup, report and continue
            print(f"WARNING: cleanup failed for admin_id={admin_id}: {exc}")


def check_reset_password_identity_bypass(service_client, anon_client):
    print("\n[1] rpc_reset_password() identity-bypass fix")
    admin_id, username, mobile, full_name, password = _seed_admin(service_client, "reset")
    try:
        # Attacker knows the admin_id (e.g. sequential/guessable) but not
        # the real full_name/mobile - this must be rejected now.
        bypassed = False
        try:
            anon_client.rpc("rpc_reset_password", {
                "p_admin_id": admin_id,
                "p_full_name": "Totally Wrong Name",
                "p_mobile": "9999999999",
                "p_new_password_hash": generate_password_hash("HackedPass123"),
            }).execute()
            bypassed = True
        except APIError:
            pass
        _check(
            "wrong identity is rejected (RPC raises, no update)",
            not bypassed,
            "call succeeded with mismatched full_name/mobile" if bypassed else "",
        )

        # This account is still on a legacy (werkzeug-scrypt) hash, which
        # rpc_login_lookup can't verify itself - it returns legacy_hash
        # unconditionally for this format (see the migration file's
        # comments), so check it here with check_password_hash exactly as
        # routes/auth.py's login() does, rather than trusting a row came
        # back at all.
        login_resp = anon_client.rpc(
            "rpc_login_lookup", {"p_identifier": username, "p_password": password}
        ).execute()
        original_pw_intact = (
            bool(login_resp.data)
            and login_resp.data[0].get("legacy_hash")
            and check_password_hash(login_resp.data[0]["legacy_hash"], password)
        )
        _check("original password still works after rejected reset", original_pw_intact)

        # Correct identity must still succeed.
        anon_client.rpc("rpc_reset_password", {
            "p_admin_id": admin_id,
            "p_full_name": full_name,
            "p_mobile": mobile,
            "p_new_password_hash": generate_password_hash("NewGoodPass123"),
        }).execute()
        relogin = anon_client.rpc(
            "rpc_login_lookup", {"p_identifier": username, "p_password": "NewGoodPass123"}
        ).execute()
        reset_worked = (
            bool(relogin.data)
            and relogin.data[0].get("legacy_hash")
            and check_password_hash(relogin.data[0]["legacy_hash"], "NewGoodPass123")
        )
        _check("correct identity legitimately resets password", reset_worked)
    finally:
        _cleanup(service_client, [admin_id])


def check_login_lookup_hash_exposure(service_client, anon_client):
    print("\n[2] rpc_login_lookup() hash-exposure fix")
    admin_id, username, mobile, full_name, password = _seed_admin(service_client, "hash")
    try:
        wrong = anon_client.rpc(
            "rpc_login_lookup", {"p_identifier": username, "p_password": "WrongPass999"}
        ).execute()
        # Legacy-format accounts still return the hash once (documented,
        # shrinking exposure) - the real assertion is that it disappears
        # after one successful login, checked below. Confirm no *raw*
        # scrypt column named "password" is exposed - only "legacy_hash".
        if wrong.data:
            _check(
                "response never contains a 'password' field",
                "password" not in wrong.data[0],
            )

        correct = anon_client.rpc(
            "rpc_login_lookup", {"p_identifier": username, "p_password": password}
        ).execute()
        _check(
            "correct password returns exactly one matching row",
            bool(correct.data) and correct.data[0]["admin_id"] == admin_id,
        )

        # Simulate the login route's upgrade step.
        build_tenant_client(admin_id).rpc(
            "rpc_migrate_password_hash", {"p_plain_password": password}
        ).execute()

        migrated_row = service_client.table("admins").select("password").eq("admin_id", admin_id).execute().data[0]
        _check(
            "stored hash is now bcrypt-format after migration",
            migrated_row["password"].startswith("$2"),
        )

        post_migration = anon_client.rpc(
            "rpc_login_lookup", {"p_identifier": username, "p_password": password}
        ).execute()
        _check(
            "post-migration correct login returns admin_id with no legacy_hash",
            bool(post_migration.data)
            and post_migration.data[0]["admin_id"] == admin_id
            and not post_migration.data[0].get("legacy_hash"),
        )

        post_migration_wrong = anon_client.rpc(
            "rpc_login_lookup", {"p_identifier": username, "p_password": "WrongAgain999"}
        ).execute()
        _check(
            "post-migration wrong password returns no row and no hash at all",
            not post_migration_wrong.data,
        )

        # Attempting to call the OLD single-arg signature must fail outright
        # - it should no longer exist.
        old_sig_still_callable = True
        try:
            anon_client.rpc("rpc_login_lookup", {"p_identifier": username}).execute()
        except APIError:
            old_sig_still_callable = False
        _check("old single-arg rpc_login_lookup(text) signature is gone", not old_sig_still_callable)
    finally:
        _cleanup(service_client, [admin_id])


def _insert_with_next_id(service_client, table, id_column, row):
    """Same MAX(id)+1 pattern as scripts/verify_tenant_isolation.py's local
    helper - enquiries/students/library_settings identity sequences trail
    real usage (ADR-15/TD-78), so trusting the column default risks a
    primary-key collision against a project with existing data."""
    top = service_client.table(table).select(id_column).order(id_column, desc=True).limit(1).execute()
    next_id = (top.data[0][id_column] + 1) if top.data else 1
    return service_client.table(table).insert({**row, id_column: next_id}).execute().data[0]


def check_archived_session_access(service_client):
    print("\n[3] archived-session access fix")
    admin_id, username, mobile, full_name, password = _seed_admin(service_client, "archive")
    try:
        # Seed one real row so "before" is meaningfully non-empty - an
        # empty result is ambiguous (RLS denial vs. just no data).
        _insert_with_next_id(service_client, "library_settings", "setting_id", {
            "admin_id": admin_id,
            "library_name": f"SecFix Archive Check {username}",
            "phone": mobile,
        })

        tenant_client = build_tenant_client(admin_id)
        before = tenant_client.table("library_settings").select("admin_id").execute()
        _check(
            "active admin's tenant client can read its own seeded row",
            bool(before.data) and before.data[0]["admin_id"] == admin_id,
        )

        # Archive via the same RPC routes/setting.py uses (ADR-76) - the
        # admin is still active at the moment this call is made.
        tenant_client.rpc("rpc_archive_tenant", {}).execute()

        status_row = service_client.table("admins").select("status").eq("admin_id", admin_id).execute().data[0]
        _check("admin row status is now 'archived'", status_row["status"] == "archived")

        # Reuse the SAME already-issued tenant client/JWT (simulating a
        # session that predates the archive) to prove current_admin_id()
        # itself now denies access, not just a route-level check - its own
        # seeded row (proven readable above) must now be invisible.
        after_settings = tenant_client.table("library_settings").select("admin_id").execute()
        _check(
            "already-issued session can no longer read its own seeded row after archive",
            after_settings.data == [],
        )

        # The same session can no longer self-manage its own account either
        # (rpc_delete_tenant_data/rpc_archive_tenant both key off
        # current_admin_id(), which is now NULL for this session).
        self_delete_blocked = False
        try:
            tenant_client.rpc("rpc_delete_tenant_data", {}).execute()
        except APIError:
            self_delete_blocked = True
        _check(
            "archived session can no longer call rpc_delete_tenant_data on itself",
            self_delete_blocked,
        )

        anon_client = build_anon_client()
        login_attempt = anon_client.rpc(
            "rpc_login_lookup", {"p_identifier": username, "p_password": password}
        ).execute()
        _check(
            "rpc_login_lookup still reports status='archived' for a fresh login attempt",
            bool(login_attempt.data) and login_attempt.data[0]["status"] == "archived",
        )
    finally:
        # The admin's own session can no longer delete itself (proven
        # above) - clean up with the service-role client instead.
        _cleanup(service_client, [admin_id])


def main():
    service_client = get_service_role_client()
    anon_client = build_anon_client()

    print("Running security-fix verification against the live project...")
    check_reset_password_identity_bypass(service_client, anon_client)
    check_login_lookup_hash_exposure(service_client, anon_client)
    check_archived_session_access(service_client)

    print("\n" + "-" * 70)
    failed = [c for c in _checks if not c[1]]
    for name, ok, detail in _checks:
        mark = "PASS" if ok else "FAIL"
        print(f"{mark:<5} {name}")
    print("-" * 70)

    if failed:
        print(f"FAIL - {len(failed)} of {len(_checks)} checks failed.")
        return 1

    print(f"PASS - all {len(_checks)} checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
