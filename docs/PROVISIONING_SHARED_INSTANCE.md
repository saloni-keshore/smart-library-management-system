# Provisioning the shared instance (current model, ADR-75)

## Overview

As of 2026-09-16 (ADR-75), this app runs as a **shared-database, self-service multi-tenant SaaS**: one Supabase project holds every library (tenant), isolated from each other by Postgres Row-Level Security (RLS) — not by each library getting its own deployment/project (that older model, ADR-53, is documented separately in [PROVISIONING.md](PROVISIONING.md) and remains valid only for pilot libraries already running under it).

This is the runbook for standing up the shared instance itself (a one-time job per environment — production, and optionally a separate staging/dev project, ADR-69) — **not** something a new library's operator has to do. Once the shared instance exists, a new library onboards by opening the running app and using its self-service registration form; there is no per-library deployment, no per-library Supabase project, and no operator-run schema step for that library.

This is still a manual checklist, not automation — the app has no `exec_sql`/DDL RPC and no direct-Postgres path (ADR-14), so schema setup is run by hand in the SQL Editor either way.

## Step A — Provision (or reuse) the shared Supabase project

1. Create a Supabase project for the shared instance (or reuse an existing one — e.g. the project ADR-69 already designated as the local-dev/Render/Vercel shared project). Note its Project URL, its **anon/publishable** key, its **service-role** key, and its **JWT secret** (Project Settings → API → JWT Settings).
2. Open the SQL Editor and run `database/supabase_migration.sql` in full, exactly once (same as the legacy model's Step A — see [PROVISIONING.md](PROVISIONING.md) for the base-schema grants/verification steps, which are unchanged here). Confirm `python scripts/verify_schema.py` reports `PASS` before continuing.
3. **Run `database/supabase_rls_migration.sql` in full, exactly once, AFTER step 2 above.** Read the file's own header comment before running it — it's ordered in sections (`1a` schema/backfill, `1b`/`1c` RLS + bootstrap RPCs, then the ADR-76 data-lifecycle RPCs) and is idempotent (safe to re-run), but enabling RLS before the `1a` backfill commits would make every existing `memberships`/`payments`/`membership_charges`/`panda_messages` row invisible to everyone at once (`NULL admin_id` never matches `current_admin_id()`). On a project with no pre-existing data (a fresh shared instance) this ordering concern doesn't apply in practice, but run the file as one script, don't split it across sessions.
4. **Run `database/supabase_security_fixes_migration.sql` in full, exactly once, AFTER step 3 above — required, not optional, even on a brand-new project (ADR-77).** This is not an optional patch for existing deployments only: it redefines `current_admin_id()`, `rpc_login_lookup()`, and `rpc_reset_password()` from the versions `supabase_rls_migration.sql` just created, closing an identity-check bypass in `rpc_reset_password`, an unconditional password-hash exposure in `rpc_login_lookup`, and a gap that let an already-archived admin's live session keep RLS access. `routes/auth.py`'s `login()`/`forgot_password()` call the **new** RPC signatures unconditionally (2-arg `rpc_login_lookup`, 4-arg `rpc_reset_password`) — skip this step and login/forgot-password break outright with a `PGRST202 could not find function` error, not a security-only gap. Idempotent, same conventions as its sibling; ends with a `NOTIFY pgrst, 'reload schema'` so PostgREST picks up the new signatures without a project restart (a full project restart is only needed if a call still 404s/`PGRST202`s afterward — see ADR-77 in [DECISIONS.md](DECISIONS.md)).
5. From the repository root, with this project's env vars set, run:

   ```
   python scripts/verify_tenant_isolation.py
   ```

   It takes **no arguments** — unlike the legacy model's `--expected-admin-id` usage, it doesn't check "how many admins exist"; it seeds two disposable throwaway tenants, proves RLS itself (not application code) blocks a cross-tenant read on a representative set of tables, then deletes both seeded tenants via `rpc_delete_tenant_data()`. Confirm it reports `PASS`. This script mutates data (safely, cleaning up after itself) — never point it at a project already holding real library data that you can't afford a transient blip on.
6. Then run:

   ```
   python scripts/verify_security_fixes.py
   ```

   Also **no arguments**. Proves all three ADR-77 fixes against this project specifically — that `rpc_reset_password` rejects a mismatched identity, that `rpc_login_lookup` never returns a raw password hash and the old single-arg signature is gone, and that an archived admin's already-issued session loses access immediately. Confirm it reports `PASS` before treating step 4 as done. Like the isolation script, it only ever creates/deletes its own throwaway `secfix_*` admin accounts — safe to run against a project with real tenants.

## Step B — Configure the deployment

Same as the legacy model's Step B ([PROVISIONING.md](PROVISIONING.md)) with **two additional required env vars**:

- `SUPABASE_ANON_KEY` — the anon/publishable key from Step A. Used for every per-request client, tenant-scoped or pre-login (`database/supabase_client.py`'s `build_anon_client()`/`build_tenant_client()`) — RLS only actually applies when the client authenticates as `anon`/`authenticated`, never the service-role key.
- `SUPABASE_JWT_SECRET` — the JWT secret from Step A. Signs the short-lived (~60s), per-request tenant JWT `build_tenant_client(admin_id)` mints, carrying the custom `admin_id` claim `current_admin_id()` (defined in `database/supabase_rls_migration.sql`, redefined by `database/supabase_security_fixes_migration.sql` to also require `status = 'active'` — ADR-77) reads to enforce every RLS policy. Never expose this value to a client or log it.

`SUPABASE_SECRET_KEY` is still required, but as of ADR-75 its role is narrowed to offline scripts/tooling (`scripts/*.py`, `tests/conftest.py`'s assertion helpers) — `database/supabase_client.py`'s `get_service_role_client()` is the only thing that reads it; no route or `database/*_queries.py` module uses it any more, since it bypasses RLS entirely.

## Step C — Install and serve

Unchanged from the legacy model — see [PROVISIONING.md](PROVISIONING.md) Step C. `waitress` handles the app's multi-threading; `build_tenant_client()` builds a brand-new client per request specifically because a shared/cached client would be a data race under that concurrency model (see ADR-75).

**Running the pytest suite:** unchanged guidance (ADR-69) — never point `.env` at a project holding real library data. `.env.test` needs the same two new variables (`SUPABASE_ANON_KEY`/`SUPABASE_JWT_SECRET`) alongside `SUPABASE_URL`/`SUPABASE_SECRET_KEY`, and that dedicated test project needs **all three** of `database/supabase_migration.sql`, `database/supabase_rls_migration.sql`, **and `database/supabase_security_fixes_migration.sql`** applied (Step A above), not just the base schema. **The third file is not optional for a green test run (ADR-77):** every test that logs in — `tests/test_01_auth.py` and every other suite that authenticates a test client first — goes through `routes/auth.py`'s `login()`, which calls the 2-arg `rpc_login_lookup(p_identifier, p_password)`. If the `.env.test` project only has the base + RLS migrations applied, that call 404s with `PGRST202` (the old 1-arg signature is all that project still has) and every auth-dependent test fails, not just the ones specifically about security. Re-run `python scripts/verify_security_fixes.py` against the `.env.test` project too after applying it, same as production.

## Step D — A new library self-registers (replaces the legacy model's "Step E: register the first admin")

There is no operator step here. A new library's admin:

1. Opens the running app and uses the on-screen registration form (`/register`) — always available, no "initial setup only" gate (ADR-75 removed it).
2. Registration goes through one `SECURITY DEFINER` RPC (`rpc_register_admin`), which checks username/mobile uniqueness **across every tenant** (deliberate — `admins` is the shared tenant root) and inserts the row, atomically, from the anon-role pre-login client.
3. They log in and see only their own library's data from the first request onward — enforced by RLS, not by anything the operator configured per-library.

If you want to *prove* isolation for this specific new tenant beyond what Step A's project-wide check already covered, there's no per-admin equivalent of the legacy model's old `--expected-admin-id` re-check — `scripts/verify_tenant_isolation.py` proves the RLS mechanism works in general (via its own throwaway tenants), not that one particular admin_id is correctly isolated; `tests/test_08_cross_tenant_isolation.py` is the app-level (routes/UI) complement, also not scoped to one live admin.

## Decommissioning an existing legacy (ADR-53) pilot deployment into the shared instance

An existing pilot library, still running its own standalone deployment + Supabase project under [PROVISIONING.md](PROVISIONING.md), moves to the shared instance like this — there is no automated migration/import tooling:

1. On the **old** deployment: Settings → Data & Backup → Create Backup (download and keep the JSON export), then Settings → Data & Backup → Danger Zone → **Permanently Delete My Library** (or **Archive**, if you want a fallback window before committing to delete — see ADR-76). Both require a fresh backup taken within the last 24 hours, the account's username typed back, and the current password.
2. On the **shared instance**: self-register a new admin account (Step D above) for the same library.
3. Manually re-enter the library's ongoing data (Library Profile, Membership Settings, current students/memberships) — the exported JSON from step 1 is for the admin's own records, **not** a re-import format; no code path reads it back in. This is a deliberate scope limitation, tracked as a Planned Feature (PF-10 in [11_FUTURE_WORK.md](11_FUTURE_WORK.md)) if an automated import is ever built.
4. Decommission the old standalone deployment/Supabase project once satisfied the new one is correct.

## Sign-off checklist

- [ ] Step A: `database/supabase_migration.sql` applied once; `scripts/verify_schema.py` reports `PASS`.
- [ ] Step A: `database/supabase_rls_migration.sql` applied once, in full, after the base migration.
- [ ] Step A: `database/supabase_security_fixes_migration.sql` applied once, in full, after the RLS migration — **required on every project, including a brand-new one (ADR-77); login/forgot-password break outright without it, not just a security gap.**
- [ ] Step A: `python scripts/verify_tenant_isolation.py` (no arguments) reports `PASS`.
- [ ] Step A: `python scripts/verify_security_fixes.py` (no arguments) reports `PASS`.
- [ ] Step B: `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `SUPABASE_ANON_KEY`, `SUPABASE_JWT_SECRET` are all set for this deployment.
- [ ] Step C: `pip install -r requirements.txt` succeeded; the app boots via `waitress-serve --call wsgi:create_app`.
- [ ] Step D: a real self-registration through `/register` was tested end-to-end (register → login → Dashboard loads).
- [ ] A quick manual pass through Dashboard, Students, Memberships, Payments, Cashbook, Business Intelligence, AI Center, Panda, and Settings → Data & Backup (including that the Danger Zone's confirmation gate actually blocks an incomplete submission), confirming each loads without error.
