# Architecture

## App bootstrap — `app.py`

`create_app(test_config=None)` is a factory function:

1. Instantiates `Flask(__name__)`.
2. Reads `APP_ENV` (default `"production"`) and applies `DevelopmentConfig` or `ProductionConfig` from `config.py` via `app.config.from_object(...)` — this is also where `.env` gets loaded, since importing `config` triggers its module-level `load_dotenv()`. If `test_config` is passed, it's merged in with `app.config.update(test_config)`.
3. If `SECRET_KEY` is still unset after that and the app isn't in testing mode, raises `RuntimeError("SECRET_KEY must be set before starting the application.")` — there is no hardcoded fallback secret; a missing `.env`/env var is a hard startup failure by design. In testing mode only, falls back to the literal `"test-secret-key"`.
4. Calls `_configure_logging(app)` — attaches a `RotatingFileHandler` (1MB × 5 backups) writing to `<instance_path>/smart-library.log`, skipped when `app.testing`.
5. Registers 13 blueprints with no `url_prefix` argument at registration time — each blueprint defines its own prefix internally (or none, for `auth` and `dashboard`):
   `auth_bp, dashboard_bp, enquiry_bp, student_bp, membership_bp, payment_bp, cashbook_bp, report_bp, setting_bp, notification_bp, membership_analytics_bp, membership_distribution_bp, business_intelligence_bp`
6. Registers a `before_request` hook (`enforce_request_security`) that stamps a CSRF token and, for `POST`/`PUT`/`PATCH`/`DELETE`, validates it (400 on failure); an `after_request` hook (`set_security_headers`) that sets `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, and (on HTTPS requests) `Strict-Transport-Security`; a context processor injecting `csrf_token`; and error handlers for 400/404/405/413/500, each rendering `templates/errors/error.html`.
7. Registers a second `@app.context_processor`, `inject_notification_summary`: if `"admin_id"` is not in `session`, injects `nav_notifications=None`; otherwise calls `get_notification_summary(session["admin_id"])` (defined in `routes/notification.py`) so the navbar bell (`components/notification_dropdown.html`) has data on every page.

Run via:
```python
if __name__ == "__main__":
    create_app().run()
```
No `debug=True` and no host/port override — defaults to `127.0.0.1:5000` with debug mode off unless `DevelopmentConfig` (`APP_ENV=development`) is selected.

## Config — `config.py`

Defines `Config` (base: `SECRET_KEY`, `SESSION_COOKIE_SECURE`, `PERMANENT_SESSION_LIFETIME`, `MAX_CONTENT_LENGTH`, `CSRF_ENABLED`, `ENABLE_SELF_SERVICE_PASSWORD_RESET`, `LOG_LEVEL` — all sourced from env vars with defaults), `DevelopmentConfig(Config)` (`DEBUG = True`, `SESSION_COOKIE_SECURE = False`), and `ProductionConfig(Config)` (`DEBUG = False`, `TESTING = False`). `app.py`'s `create_app()` selects one via `app.config.from_object(DevelopmentConfig if environment == "development" else ProductionConfig)`, keyed off `APP_ENV`. `config.py` also calls `load_dotenv()` at import time — it's the app's single `.env`-loading entry point, imported before any route module reads `os.environ`. **As of 2026-09-09 (ADR-69):** local dev, Render, and Vercel all point `SUPABASE_URL`/`SUPABASE_SECRET_KEY` at one shared project (local dev is just another host). The `pytest` suite is the exception — `tests/conftest.py` calls `load_dotenv(<repo root>/.env.test, override=True)` *before* it imports `config`/`app`, so a git-ignored `.env.test` (dedicated throwaway project) wins over `.env` for the suite only; without one, tests use `.env`.

## Database connection — `database/supabase_client.py`

**As of 2026-07-25 (ADR-32, Phase 11), this is the only database access layer in the app** — `database/db.py` (the SQLite `get_connection()`/`initialize_database()` module this section used to document), `database/schema.sql`, `database/seed.py`, `database/init_db.py`, and every `database/migrate_*.py` script were deleted outright once the incremental table-by-table migration (ADR-16 through ADR-31) reached its last table. See [DECISIONS.md](DECISIONS.md) for the full migration history.

```python
@lru_cache
def get_supabase_client():
    return create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)
```

- A single client instance is created once (`functools.lru_cache`) and reused across requests — unlike SQLite's per-request connection, this is a plain HTTP client wrapper (PostgREST over HTTPS), not a stateful connection that needs opening/closing per request.
- Reads `SUPABASE_URL`/`SUPABASE_SECRET_KEY` from the environment (via `.env` in development); raises `RuntimeError` if either is unset. Because the client is `@lru_cache`d and reads `os.environ` on first call, anything that needs a different project (the test suite — see `.env.test` under "Config") must set those vars *before* this module is first imported.
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
- **All charts render client-side with Chart.js (as of 2026-08-28, ADR-56):** every charting page — Dashboard, Membership Distribution, Cashbook, Business Intelligence — now builds a `{labels, datasets}` payload in the route (`utils/chart_data.py`'s `build_*_chart_data()` for Dashboard/Distribution; `routes/business_intelligence.py`/`routes/cashbook.py`'s `_build_*_chart()` for the rest), passes it to the template as a `window.*` global, and renders in the browser with Chart.js from the jsdelivr CDN. The old split (Dashboard/Distribution used server-side matplotlib PNGs written to `static/charts/` via `utils/charts.py`) is gone: `utils/charts.py`, `matplotlib`, and `numpy` were removed so the app fits a read-only serverless filesystem, and the shared-PNG-filename cross-tenant leak (TD-1) went with them. See [07_STATIC_ASSETS.md](07_STATIC_ASSETS.md) and [08_UTILS_SERVICES_MODELS.md](08_UTILS_SERVICES_MODELS.md).
