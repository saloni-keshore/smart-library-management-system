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

## Database connection — `database/db.py`

```python
BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "library.db"

def get_connection():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.row_factory = sqlite3.Row
    return connection
```

- The path is anchored to the `database/` folder itself (via `__file__`), so it works regardless of the process's current working directory.
- `row_factory = sqlite3.Row` lets calling code do dict-like (`row["column"]`) and index-like access.
- **`PRAGMA foreign_keys = ON` is never set per-connection.** It only appears at the top of `database/schema.sql`, which is executed once by `database/seed.py`'s `initialize_database()`. Regular request-time connections opened via `get_connection()` do **not** enforce foreign keys. This is a deliberate-looking but undocumented tradeoff — see [04_DATABASE_SCHEMA.md](04_DATABASE_SCHEMA.md) for the practical implications.
- There is no connection pooling; every route opens and closes its own `sqlite3.Connection` per request.

## Request lifecycle (typical feature route)

1. Request hits a blueprint route (no global auth middleware).
2. Route checks `if "admin_id" not in session: return redirect("/")` manually (this exact snippet is repeated in nearly every route function across every blueprint — not factored into a decorator or `before_request` hook).
3. Route opens a connection via `get_connection()`, or calls into a `database/*_queries.py` module (some blueprints use raw SQL inline instead, see [05_ROUTES_REFERENCE.md](05_ROUTES_REFERENCE.md) for which) — as of 2026-07-24, `routes/auth.py` (ADR-16), `routes/setting.py` (ADR-17 for `security_settings()`'s password branch; ADR-24 for every other Settings sub-page), `routes/enquiries.py` (ADR-18), `routes/student.py` (ADR-19), `routes/membership.py` (ADR-20), `routes/payment.py`'s `collect()` only (ADR-21), `routes/cashbook.py` (via `database/cashbook_queries.py`/`database/audit_queries.py`, ADR-22), and `routes/dashboard.py`/`routes/membership_distribution.py`/`routes/notification.py` (ADR-23) are the exceptions: they call `database/supabase_client.py`'s `get_supabase_client()` (directly or via a `database/*_queries.py` module), since `admins` reads/writes for login/register/forgot-password, Settings' password change and (as of ADR-24) every other Settings table, all of Enquiries, all of Students, all of Memberships, `collect()`'s `memberships.paid_amount`/`pending_amount` update, `cashbook`/`audit_log`, and every analytics read of `students`/`enquiries`/`memberships` now go to Supabase (PostgreSQL), not SQLite. `routes/enquiries.py`, `routes/student.py`, `routes/membership.py`, and `routes/payment.py` still also call `get_connection()` — not for the reads/writes just described, but to keep a SQLite mirror in sync for the still-unmigrated `payments` table's readers (`routes/payment.py`'s `index()`, `database/payment_queries.py`'s receipt-fallback branch, `utils/charts.py`'s `generate_revenue_chart()`, `routes/student.py`'s own `view()`). `routes/setting.py` also still calls `get_connection()`, but only for `backup_create()`'s whole-file SQLite copy and `data_backup()`'s `db_size` display — not for any table read/write.
4. Route renders a template that `{% extends "layouts/base.html" %}`, or redirects (POST/Redirect/GET pattern is used consistently after form submissions).
5. `inject_notification_summary` context processor runs on every render, populating the navbar bell independent of what the route itself passed in.

## Session/auth model

- Flask's default signed-cookie session (server-side `SECRET_KEY` signs it; no server-side session store).
- Session keys used: `admin_id`, `username`, plus a short-lived `membership_change_summary` (set by `routes/setting.py`, popped on the next GET — a one-shot flash-like pattern for showing a "what changed" diff after a settings save).
- No password reset tokens, no "remember me", no CSRF protection library in use (no Flask-WTF/csrf token references found in templates or routes).
- Passwords are hashed with Werkzeug's `generate_password_hash`/`check_password_hash` (in `routes/auth.py`).

## Cross-cutting patterns worth knowing before editing routes

- **Auth check duplication:** the `if "admin_id" not in session` guard is copy-pasted into every route rather than centralized (e.g. via a decorator or `before_request`). Adding a new route means remembering to paste this in.
- **Two data-access styles coexist:** some blueprints write raw SQL directly in the route function; others (`cashbook`, `business_intelligence`, `setting`) delegate to a dedicated `database/*_queries.py` module. See [09_DEPENDENCY_MAP.md](09_DEPENDENCY_MAP.md). `auth` is a third, newer style as of 2026-07-23: it queries Supabase's PostgREST client directly in the route function (no query module yet either), the same "inline" shape as the first group, just against a different backend — see ADR-16. `setting` picked up a small slice of this same third style the same day (ADR-17): `security_settings()`'s password-change branch calls `get_supabase_client()` directly, inline, while every other function in that file still delegates to a `database/*_queries.py` module as before — as of 2026-07-24 (ADR-24), those delegated-to modules (`settings_queries`/`receipt_settings_queries`/`notification_settings_queries`/`membership_settings_queries`/`backup_queries`/`security_settings_queries`) are all Supabase-backed too, so `setting` keeps its "delegate to a query module" shape unchanged, just with every one of those modules now on the new backend; `backup_export_csv()` picked up the ADR-17-style inline `get_supabase_client()` call for its `students` read. `enquiries`, `student`, and `membership` all moved fully into the third style the same day too (ADR-18/ADR-19/ADR-20) — every function calls `get_supabase_client()` directly, inline, though all three also fall back to raw SQL (`get_connection()`) to keep a SQLite mirror in sync for the still-unmigrated `payments` table's readers (and, for `student`, to read `payments` itself in `view()`; `membership` still calls into `database/membership_queries.py`/`database/payment_queries.py` for shared logic). `payment` picked up the same slice of the third style the same day too (ADR-21): only `collect()` calls `get_supabase_client()` directly, inline, for its `memberships` read/update, then falls back to `get_connection()` to mirror that same update into SQLite and to call `database/payment_queries.py`'s `record_payment()` (unchanged, still SQLite-only); `index()` is untouched and stays 100% raw SQL against SQLite. `dashboard`, `notification`, and `membership_distribution` — previously the canonical example of the first ("raw SQL inline") style — moved to a fourth shape as of 2026-07-23 (ADR-23): they call `database/membership_queries.py`'s shared `get_memberships_for_admin()`/`get_admin_students()` helpers (themselves Supabase-backed) instead of writing their own SQL, for everything except the handful of `payments`-dependent reads each still has (documented per-function in each file). `notification` now has no SQLite dependency left at all; `dashboard`/`membership_distribution` still call `get_connection()` for their remaining `payments`-only reads.
- **Server-rendered chart images vs. client-rendered charts:** the Dashboard and Membership Distribution pages call into `utils/charts.py`, which queries the DB itself and writes a PNG to `static/charts/` as a side effect; the template then just displays that static image. Cashbook and Business Intelligence instead pass JSON-ish data into the template (`window.cashbookChartData`, `window.biChartData`) and render with Chart.js in the browser. These are two different, non-interchangeable charting approaches living side by side — see [07_STATIC_ASSETS.md](07_STATIC_ASSETS.md) and [08_UTILS_SERVICES_MODELS.md](08_UTILS_SERVICES_MODELS.md).
