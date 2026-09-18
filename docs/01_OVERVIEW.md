# Overview

## What this is

Smart Library App is a Flask web application for managing a coaching-center / reading-library business: student enquiries and admissions, membership plans and renewals, fee payments, a cashbook (income/expense ledger), and a business-intelligence dashboard on top of that financial data.

It is **multi-tenant**: every logged-in admin only ever sees their own data. Isolation is enforced by an `admin_id` column (directly or via join) on nearly every query — see [04_DATABASE_SCHEMA.md](04_DATABASE_SCHEMA.md).

## Tech stack (actual, as installed)

- **Backend:** Flask (`requirements.txt` pins only `Flask>=2.3.0` and `Werkzeug>=2.3.0`)
- **Database:** Supabase (PostgreSQL), accessed via the `supabase-py` PostgREST client (`database/supabase_client.py`); no ORM, `.eq()`/`.in_()`-filtered queries in `database/*_queries.py` modules or inline in routes. **As of 2026-07-25 (ADR-32, Phase 11), Supabase is the only database in the app** — SQLite (`database/db.py`, `database/schema.sql`, and every `database/migrate_*.py` script) was removed entirely once the incremental table-by-table migration (ADR-16 through ADR-31, tracked in [DECISIONS.md](DECISIONS.md)) reached its last table (`admins`). See [DECISIONS.md](DECISIONS.md) for the full migration history and [MIRROR_TRACKER.md](MIRROR_TRACKER.md) for how each table's SQLite mirror was removed.
- **Templates:** Jinja2 (bundled with Flask)
- **Frontend:** Bootstrap 5.3.7 + Bootstrap Icons 1.11.3 (via CDN), Chart.js 4.4.4 (via CDN — all charts render client-side), Google Fonts "Poppins"
- **Charts:** every charting page (Dashboard, Membership Distribution, Cashbook, Business Intelligence) builds a `{labels, datasets}` payload server-side and renders it in the browser with Chart.js. There is no server-side image generation — `utils/charts.py`/`matplotlib`/`numpy` were removed 2026-08-28 (ADR-56) so the app runs on a read-only serverless filesystem; `utils/chart_data.py` holds the Dashboard/Distribution payload builders.

There is no ORM and no build step for CSS/JS (plain hand-authored files served directly from `static/`). Supabase's schema lives in `database/supabase_migration.sql`, hand-maintained (no migrations framework/runner) — see [04_DATABASE_SCHEMA.md](04_DATABASE_SCHEMA.md).

## Running it locally

```
pip install -r requirements.txt
# Set SUPABASE_URL / SUPABASE_SECRET_KEY (e.g. via .env) - see database/supabase_client.py
python app.py                  # runs with debug=True on the Flask default port (5000)
```

`app.py` selects `config.py`'s `DevelopmentConfig`/`ProductionConfig` via `APP_ENV` (default `production`, debug off); importing `config` also loads `.env` via `python-dotenv`'s `load_dotenv()` (see [02_ARCHITECTURE.md](02_ARCHITECTURE.md)).

## Multi-tenancy model

**As of 2026-09-16 (ADR-75), this is a shared-database, self-service multi-tenant SaaS** — many libraries (tenants) coexist in one Supabase project, isolated from each other by Postgres **Row-Level Security (RLS)**, not by application code alone. This reverses ADR-53's "one deployment + one Supabase project per library" pilot model for any *new* deployment; an existing pilot library provisioned under that older model keeps working exactly as documented in [PROVISIONING.md](PROVISIONING.md) until it's deliberately decommissioned (see below).

- One `admins` row = one tenant/owner of a library. Registration (`routes/auth.py`'s `register()`) is **always open** — there is no "first admin only" gate any more.
- Session holds `admin_id` and `username` after login. Every request gets its own Supabase client (`app.py`'s `attach_tenant_supabase_client` before_request hook, `database/supabase_client.py`'s `build_tenant_client(admin_id)`), carrying a freshly signed, short-lived JWT with a custom `admin_id` claim — never a shared/cached client, never the service-role key (which would bypass RLS entirely).
- Every feature route checks the caller is logged in before doing anything, via a shared `@login_required` decorator (`utils/security.py`, new — see [11_FUTURE_WORK.md](11_FUTURE_WORK.md) TD-19, now Resolved) instead of the old copy-pasted inline check. This check is app-layer defense-in-depth on top of RLS, not the thing that actually makes another tenant's data inaccessible.
- Data isolation is enforced **twice, in depth**: application code still filters most queries by `admin_id` (unchanged convention, see ADR-2), and — new as of ADR-75 — Postgres itself refuses to return or write a row whose `admin_id` doesn't match the requesting JWT's claim, via a `tenant_isolation` RLS policy on every one of the app's 16 tenant-owned tables (`database/supabase_rls_migration.sql`). A query that forgets its `admin_id` filter today fails closed (an empty result, not a cross-tenant leak) rather than actually exposing another library's data — RLS is the real enforcement mechanism, the application-level filter is defense-in-depth on top of it, not the other way around.
- An admin account can be **archived** (deactivated, login refused, data untouched) or **permanently deleted** (every row across every table, one atomic transaction) by its own owner via Settings → Data & Backup's Danger Zone — see ADR-76 and [11_FUTURE_WORK.md](11_FUTURE_WORK.md) PF-9/PF-10 for what's deliberately not built yet (reactivating an archived account; importing an exported backup into a new tenant).
- See ADR-75/ADR-76 in [DECISIONS.md](DECISIONS.md), the "Multi-tenant (`admin_id`) summary" table in [04_DATABASE_SCHEMA.md](04_DATABASE_SCHEMA.md), and [PROVISIONING_SHARED_INSTANCE.md](PROVISIONING_SHARED_INSTANCE.md) for the new deployment runbook.

## Feature areas (see [10_FEATURE_MODULES.md](10_FEATURE_MODULES.md) for full walkthroughs)

| Feature | Status |
|---|---|
| Auth (login/register/forgot password) | Implemented |
| Dashboard (KPIs, charts, quick actions) | Implemented |
| Enquiries | Implemented |
| Students / Admissions | Implemented |
| Memberships (create/renew) | Implemented |
| Membership Distribution (plan analytics) | Implemented |
| Membership Analytics (`/membership-analytics/`) | Route exists, renders a template shell with **no data** — effectively a stub |
| Payments (collect fee) | Implemented |
| Cashbook (ledger, manual entries, audit log) | Implemented |
| Business Intelligence (health score, growth, action items) | Implemented |
| Notifications (expiry buckets) | Implemented |
| Settings → Library Profile | Implemented |
| Settings → Membership Settings | Implemented |
| Settings → Receipt Settings | Implemented (configuration only — no PDF/print/email yet) |
| Settings → Notification Settings | Implemented (reminder-rule/channel/quiet-hours/dashboard-display preferences; `dash_show_pending_fees` and the navbar-bell toggles are wired, the rest are save-only — no SMS/Email/WhatsApp dispatch exists) |
| Settings → Staff & User Access | Placeholder ("Coming Soon" — still single-admin) |
| Settings → Data & Backup | Implemented (manual Export CSV / Create Backup only — no scheduled backups) |
| Settings → Security Settings | Implemented (password change is fully enforced; session timeout / remember-me / login-notification preferences are persisted but not enforced) |
| Reports (`/reports/`) | Deprecated redirect shim → Business Intelligence |
