# Provisioning a new library

## Overview

Under the pilot-phase deployment model (2026-08-21, ADR-53), **every library is one fully independent app deployment plus one fully independent Supabase project.** There is no shared schema, no `firm_id`/`organization_id`/tenant column, and no Admin/Reception role system anywhere in this codebase — each library's `admins` table has exactly one admin account, and that admin sees only what lives in that library's own Supabase project.

Because of this, cross-library data leakage is not an application-isolation question — it's a **deployment/configuration correctness** question: did this deployment get pointed at *this* library's Supabase project, using *this* library's own `.env`, and nothing borrowed from another library? Every step below exists to make that answer verifiably "yes" before real data goes into a new library's environment.

This is a manual checklist/runbook, not automation — the app has no `exec_sql`/DDL RPC and no direct-Postgres path (ADR-14), so schema setup on a fresh Supabase project has to be run by hand in the SQL Editor either way.

## Prerequisites

- **Python 3.11 or newer.** Verified during this session: a clean `pip install -r requirements.txt` fails on Python 3.10 (`contourpy==1.3.3 Requires-Python >=3.11` — a transitive `matplotlib` dependency, used by `utils/charts.py`) and succeeds cleanly on 3.11. This wasn't documented anywhere before now.
- The ability to create a virtual environment.
- Access to create a new Supabase project (a Supabase account with project-creation permission).
- This repository, checked out fresh or already available locally.

## Step A — Provision the Supabase project

1. Create a new Supabase project for this library. Note its Project URL and its **service-role** secret key (Project Settings → API) — this app uses the service-role key, not the anon key (see `database/supabase_client.py` and `docs/DECISIONS.md` ADR-2).
2. Open the SQL Editor on this new project and run `database/supabase_migration.sql` in full, exactly once. It's wrapped in its own `BEGIN;`/`COMMIT;`, so it applies atomically.
   - **Run this only once against a given project.** The `expenses` table is created with a plain `CREATE TABLE` (not `IF NOT EXISTS`) — re-running the script against a project it's already been applied to will fail on that line.
3. **Grant the service-role key privileges on the tables just created (TD-69).** A newly created Supabase project does not reliably auto-grant the service-role-equivalent API key access to tables created by hand in the SQL Editor — without this step, every table read fails with Postgres error `42501 permission denied for table ...`, which `scripts/verify_schema.py` reports as `ERROR` (not `MISSING`), making the real cause non-obvious. In the same SQL Editor, run:

   ```sql
   GRANT USAGE ON SCHEMA public TO service_role;
   GRANT ALL ON ALL TABLES IN SCHEMA public TO service_role;
   GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO service_role;
   ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO service_role;
   ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO service_role;
   ```

4. From the repository root, with `SUPABASE_URL`/`SUPABASE_SECRET_KEY` for *this* project set in your shell environment (or a temporary `.env`), run:

   ```
   python scripts/verify_schema.py
   ```

   Confirm it reports `PASS` and every table as `OK` before continuing. If anything is `MISSING`, re-check step 2 — in particular `ai_center_settings`, `panda_conversations`, and `panda_messages` are the tables most likely to be skipped by an incomplete run (TD-53/TD-55). If every table instead reports `ERROR` with a `42501 permission denied` detail, re-check step 3.

## Step B — Configure the deployment

1. Create this library's own deployment directory (a fresh clone/copy of this repository, or its own directory in whatever hosting setup you use) — **never** share a directory, virtual environment, or `.env` file with another library's deployment.
2. Copy `.env.example` to `.env` **inside this deployment's own directory**. Set:
   - `SUPABASE_URL` / `SUPABASE_SECRET_KEY` — from Step A, this library's project only.
   - `SECRET_KEY` — generate a fresh one per deployment, e.g. `python -c "import secrets; print(secrets.token_urlsafe(32))"`. Do not reuse another deployment's key.
   - `APP_ENV=production`, `SESSION_COOKIE_SECURE=true`, `SESSION_LIFETIME_MINUTES`, `LOG_LEVEL` — these are deployment-tier settings, not per-library secrets; copy them from `.env.example`'s defaults unless you have a specific reason to change them.
   - Omit `DATABASE_PATH` — it's a legacy/unused setting from before the app moved fully to Supabase (ADR-32).
3. **Confirm there is no other `.env` file anywhere above this deployment's directory in the filesystem.** `python-dotenv`'s `load_dotenv()` (used by both `config.py` and `database/supabase_client.py`) walks upward through parent directories looking for a `.env` if this deployment's own is missing or misnamed — it does not fail loudly, it silently uses whatever `.env` it finds first, which could belong to a different library entirely if multiple deployments live under a shared parent folder. Keep each library's deployment in a directory tree where its own `.env` is the *only* one in that ancestor path.

## Step C — Install and serve

1. Create a virtual environment for this deployment and run `pip install -r requirements.txt` (this includes `waitress`).
2. Start the app: `waitress-serve --call wsgi:create_app`, behind HTTPS (via whatever reverse proxy/TLS termination your hosting setup uses).

## Step D — Verify isolation before go-live

1. Check this deployment's log file (`instance/smart-library.log`, or console output on first run) for the line `Connected Supabase project: ...<last-24-chars-of-URL>` and visually confirm it matches the project you created in Step A, not any other library's.
2. Run:

   ```
   python scripts/verify_tenant_isolation.py
   ```

   Before any admin has registered, every table should report `OK`/empty. If anything reports `FAIL`, stop — this project is not clean (most likely: the wrong `SUPABASE_URL`/`SUPABASE_SECRET_KEY` was configured in Step B.2, pointing at a project that already has another library's data in it).

## Step E — Register the first real admin

1. Open the running app in a browser and use the on-screen registration form to create this library's one admin account (registration is only available while `admins` is empty, or in test mode — see `routes/auth.py`).
2. Log in and confirm the Dashboard loads.
3. Re-run the isolation check, now scoped to the one admin that should exist:

   ```
   python scripts/verify_tenant_isolation.py --expected-admin-id <the new admin_id>
   ```

   Confirm `PASS`.

## Sign-off checklist

Before handing a new library environment over for real use, confirm every box:

- [ ] Step A: `database/supabase_migration.sql` applied once to this library's own, dedicated Supabase project.
- [ ] Step A: the `GRANT`/`ALTER DEFAULT PRIVILEGES` statements (TD-69) were run against this project.
- [ ] Step A: `scripts/verify_schema.py` reports `PASS` (all tables `OK`, including `ai_center_settings`/`panda_conversations`/`panda_messages`).
- [ ] Step B: this deployment has its own `.env`, with this library's own `SUPABASE_URL`/`SUPABASE_SECRET_KEY` and a freshly generated `SECRET_KEY`.
- [ ] Step B: no other `.env` exists anywhere above this deployment's directory.
- [ ] Step C: `pip install -r requirements.txt` succeeded; the app boots via `waitress-serve --call wsgi:create_app`.
- [ ] Step D: the startup log's `Connected Supabase project: ...` line matches the intended project.
- [ ] Step D: `scripts/verify_tenant_isolation.py` reports `PASS` before first admin registration.
- [ ] Step E: the first (and only) admin account for this library was created through the running app's registration form, not seeded directly into the database.
- [ ] Step E: `scripts/verify_tenant_isolation.py --expected-admin-id <id>` reports `PASS` after registration.
- [ ] A quick manual pass through Dashboard, Students, Memberships, Payments, Cashbook, Business Intelligence, AI Center, and Panda, confirming each loads without error for the new admin.
