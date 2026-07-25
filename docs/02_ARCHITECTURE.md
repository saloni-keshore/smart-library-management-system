# Architecture

## App bootstrap — `app.py`

`create_app()` is a factory function:

1. Instantiates `Flask(__name__)`.
2. Sets `app.config["SECRET_KEY"]` from the `SECRET_KEY` env var, defaulting to the literal string `"smart_library_secret"`.
3. Registers 13 blueprints with no `url_prefix` argument at registration time — each blueprint defines its own prefix internally (or none, for `auth` and `dashboard`):
   `auth_bp, dashboard_bp, enquiry_bp, student_bp, membership_bp, payment_bp, cashbook_bp, report_bp, setting_bp, notification_bp, membership_analytics_bp, membership_distribution_bp, business_intelligence_bp`
4. Registers one `@app.context_processor`, `inject_notification_summary`: if `"admin_id"` is not in `session`, injects `nav_notifications=None`; otherwise calls `get_notification_summary(session["admin_id"])` (defined in `routes/notification.py`) so the navbar bell (`components/notification_dropdown.html`) has data on every page.

There are **no** `before_request`/`after_request` hooks and **no** custom error handlers (no 404/500 pages) — Flask's defaults apply everywhere.

Module-level `app = create_app()`; run via:
```python
if __name__ == "__main__":
    app.run(debug=True)
```
`debug=True` is hardcoded (not conditional on an env var), and no host/port override is set (defaults to `127.0.0.1:5000`).

## Config — `config.py` (currently dead code)

Defines `Config` (base: `SECRET_KEY` from env, `DEBUG = False`), `DevelopmentConfig(Config)` (`DEBUG = True`), and `ProductionConfig(Config)` (`DEBUG = False`). **None of these classes are imported anywhere in `app.py`** — `app.py` sets `SECRET_KEY` directly instead. This is unused scaffolding; see [11_FUTURE_WORK.md](11_FUTURE_WORK.md).

## Database connection — `database/supabase_client.py`

**As of 2026-07-25 (ADR-32, Phase 11), this is the only database access layer in the app** — `database/db.py` (the SQLite `get_connection()`/`initialize_database()` module this section used to document), `database/schema.sql`, `database/seed.py`, `database/init_db.py`, and every `database/migrate_*.py` script were deleted outright once the incremental table-by-table migration (ADR-16 through ADR-31) reached its last table. See [DECISIONS.md](DECISIONS.md) for the full migration history.

```python
@lru_cache
def get_supabase_client():
    return create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)
```

- A single client instance is created once (`functools.lru_cache`) and reused across requests — unlike SQLite's per-request connection, this is a plain HTTP client wrapper (PostgREST over HTTPS), not a stateful connection that needs opening/closing per request.
- Reads `SUPABASE_URL`/`SUPABASE_SECRET_KEY` from the environment (via `.env` in development); raises `RuntimeError` if either is unset.
- No connection pooling concerns apply the way they did for SQLite (see the now-resolved "`database is locked`" entry in [TROUBLESHOOTING.md](TROUBLESHOOTING.md)) — Supabase/PostgREST handles concurrent requests server-side.
- Foreign keys, uniqueness, and `NOT NULL` constraints are enforced by Postgres itself, per `database/supabase_migration.sql` — unlike SQLite's `PRAGMA foreign_keys = ON` (never actually set per-connection in the old code), Postgres FKs are always enforced. See [04_DATABASE_SCHEMA.md](04_DATABASE_SCHEMA.md).

## Request lifecycle (typical feature route)

1. Request hits a blueprint route (no global auth middleware).
2. Route checks `if "admin_id" not in session: return redirect("/")` manually (this exact snippet is repeated in nearly every route function across every blueprint — not factored into a decorator or `before_request` hook).
3. Route calls into a `database/*_queries.py` module, or queries `database/supabase_client.py`'s `get_supabase_client()` directly inline (some blueprints use one style, some the other — see [05_ROUTES_REFERENCE.md](05_ROUTES_REFERENCE.md) and [09_DEPENDENCY_MAP.md](09_DEPENDENCY_MAP.md) for which). This reached its current, final shape incrementally: `routes/auth.py` (ADR-16), `routes/setting.py` (ADR-17/ADR-24), `routes/enquiries.py` (ADR-18), `routes/student.py` (ADR-19), `routes/membership.py` (ADR-20), `routes/payment.py` (ADR-21/ADR-25), `routes/cashbook.py` (ADR-22), `routes/dashboard.py`/`routes/membership_distribution.py`/`routes/notification.py` (ADR-23/ADR-25) each cut over from raw SQLite to Supabase in turn, then each one's now-redundant SQLite mirror-write was removed outright once nothing needed it anymore (ADR-26 through ADR-31) — see [DECISIONS.md](DECISIONS.md) for the full trail. **As of 2026-07-25 (ADR-32, Phase 11), every route in the app queries Supabase exclusively** — there is no SQLite connection anywhere in the request lifecycle, and no `database/db.py` for one to come from.
4. Route renders a template that `{% extends "layouts/base.html" %}`, or redirects (POST/Redirect/GET pattern is used consistently after form submissions).
5. `inject_notification_summary` context processor runs on every render, populating the navbar bell independent of what the route itself passed in.

## Session/auth model

- Flask's default signed-cookie session (server-side `SECRET_KEY` signs it; no server-side session store).
- Session keys used: `admin_id`, `username`, plus a short-lived `membership_change_summary` (set by `routes/setting.py`, popped on the next GET — a one-shot flash-like pattern for showing a "what changed" diff after a settings save).
- No password reset tokens, no "remember me", no CSRF protection library in use (no Flask-WTF/csrf token references found in templates or routes).
- Passwords are hashed with Werkzeug's `generate_password_hash`/`check_password_hash` (in `routes/auth.py`).

## Cross-cutting patterns worth knowing before editing routes

- **Auth check duplication:** the `if "admin_id" not in session` guard is copy-pasted into every route rather than centralized (e.g. via a decorator or `before_request`). Adding a new route means remembering to paste this in.
- **Two data-access styles coexist (both against Supabase now, formerly against SQLite):** some blueprints query `database/supabase_client.py`'s `get_supabase_client()` directly inline in the route function; others (`cashbook`, `business_intelligence`, `setting`) delegate to a dedicated `database/*_queries.py` module. See [09_DEPENDENCY_MAP.md](09_DEPENDENCY_MAP.md). This split predates the migration (it used to be "raw SQL inline" vs. "delegate to a query module" against SQLite) and survived it unchanged in shape, just against a new backend: `auth` was the first to move (ADR-16, inline), followed by `setting` (ADR-17 for `security_settings()`'s password branch, ADR-24 for everything else, keeping its "delegate to a query module" shape throughout — those modules just became Supabase-backed), `enquiries`/`student`/`membership` (ADR-18/19/20, inline), `payment` (ADR-21 for `collect()`, ADR-25 for `index()`, inline plus `database/payment_queries.py`), and `dashboard`/`notification`/`membership_distribution` (ADR-23/25, via `database/membership_queries.py`'s shared helpers rather than each writing its own query). Every one of these routes used to also fall back to `get_connection()` to keep a SQLite mirror-write current for whichever other, not-yet-migrated modules still needed it — as of 2026-07-25 (ADR-32, Phase 11), that fallback is gone everywhere: no route or query module calls `get_connection()` for anything, because `database/db.py` no longer exists. See [DECISIONS.md](DECISIONS.md)'s ADR-26 through ADR-32 for how each mirror was removed in turn.
- **Server-rendered chart images vs. client-rendered charts:** the Dashboard and Membership Distribution pages call into `utils/charts.py`, which queries the DB itself and writes a PNG to `static/charts/` as a side effect; the template then just displays that static image. Cashbook and Business Intelligence instead pass JSON-ish data into the template (`window.cashbookChartData`, `window.biChartData`) and render with Chart.js in the browser. These are two different, non-interchangeable charting approaches living side by side — see [07_STATIC_ASSETS.md](07_STATIC_ASSETS.md) and [08_UTILS_SERVICES_MODELS.md](08_UTILS_SERVICES_MODELS.md).
