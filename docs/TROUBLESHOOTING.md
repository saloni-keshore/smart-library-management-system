# Troubleshooting Guide

Common issues, why they happen in this specific codebase, and how to fix or work around them.

## `ModuleNotFoundError: No module named 'matplotlib'` (or `numpy`)

**Cause:** `requirements.txt` only lists `Flask` and `Werkzeug`, but `utils/charts.py` imports `matplotlib` and `numpy`. A fresh `pip install -r requirements.txt` doesn't install them.
**Fix:** `pip install matplotlib numpy`, then add both to `requirements.txt` (see [11_FUTURE_WORK.md](11_FUTURE_WORK.md) TD-8).
**Where it surfaces:** any request to `GET /dashboard` or `GET /membership-distribution/` — both call into `utils/charts.py` synchronously, so the request itself 500s.

## Dashboard/Distribution charts show stale or another admin's data

**Cause:** `utils/charts.py` writes to fixed, shared filenames (`static/charts/revenue.png`, `membership.png`, `membership_distribution_donut.png`) regardless of which admin triggered generation. The chart only regenerates when the Dashboard or Distribution route actually runs — it isn't recomputed on every static-file request. Between two different admins' page loads, one can briefly see the other's chart.
**Fix (short-term):** reload the page again as the affected admin — it self-corrects the moment their own dashboard route runs.
**Fix (real):** namespace the output filename by `admin_id` (`revenue_{admin_id}.png`) in `utils/charts.py`, and update the three template components that reference the static path. Tracked as [11_FUTURE_WORK.md](11_FUTURE_WORK.md) TD-1.

## Logged out unexpectedly / "please log in again" loops

**Cause:** Flask's session cookie is signed with `SECRET_KEY` (set in `app.py` from the `SECRET_KEY` env var, defaulting to a fixed literal string). If the env var changes between process restarts, every existing session cookie fails to validate and is treated as empty.
**Check:** is `SECRET_KEY` set in the environment, and is it stable across restarts? In `debug=True` dev mode, the auto-reloader restarts the *same* process config, so this is usually only an issue across full manual restarts with a different environment.

## Cross-admin data appears (Admin A sees Admin B's students/memberships/cashbook rows)

**Cause:** there is no framework-level tenant isolation — every query must manually filter by `admin_id` (directly, or via a join to a table that has it, e.g. `memberships`/`payments` via `students.admin_id`). This is a manual convention (ADR-2 in [DECISIONS.md](DECISIONS.md)), not something SQLite or Flask enforces.
**Diagnose:** find the query responsible and check it has a `WHERE admin_id = ?` (or the equivalent join filter). Compare against the patterns in [04_DATABASE_SCHEMA.md](04_DATABASE_SCHEMA.md)'s "Multi-tenant summary" table.
**Note:** `cashbook.admin_id` and `expenses.admin_id` have **no FK constraint** (added via `ALTER TABLE`, which SQLite can't constrain) — nothing stops a bad insert from writing a nonexistent or wrong `admin_id` at the database level; the application layer is the only guard.

## `sqlite3.OperationalError: database is locked`

**Cause:** `database/db.py`'s `get_connection()` opens a brand-new SQLite connection per request with no pooling. SQLite allows only one writer at a time; under concurrent write-heavy load (e.g. two admins submitting payments simultaneously, or a long-running read holding a transaction open), a writer can time out waiting for the lock.
**Fix:** at current single-admin-at-a-time scale this is unlikely; if it starts happening, look for a connection that isn't being closed promptly (missing `conn.close()` after an early return) before assuming it's a concurrency ceiling that needs WAL mode or a connection pool.

## A `migrate_*.py` script errors with "table already exists" or a column mismatch

**Cause:** there's no migration runner or version table — each script guards itself independently (`PRAGMA table_info` checks, `IF NOT EXISTS`), and correctness depends on running the right scripts in the right order on a fresh vs. existing database. The `transactions` table specifically is defined with two different shapes in `schema.sql` and `migrate_transactions.py` (see [04_DATABASE_SCHEMA.md](04_DATABASE_SCHEMA.md) and TD-2) — whichever runs first "wins".
**Fix:** before running any migration script against an existing `library.db`, check the table's actual current shape with `PRAGMA table_info(<table>)` in a SQLite shell rather than assuming either source file is authoritative.

## Editing a Cashbook entry fails / the Edit button doesn't work for some rows

**Cause:** by design, `routes/cashbook.py`'s `edit_transaction()` refuses to update any `cashbook` row whose `source` isn't exactly `"Cashbook Manual Entry"` — rows created automatically from Memberships/Payments (`source` values like `"Payments"`, `"Admission Fee"`, `"Membership Renewal"`) are intentionally read-only in this view (ADR-4 in [DECISIONS.md](DECISIONS.md)).
**Fix:** correct the underlying membership/payment record instead — the cashbook row is derived from it, not independently editable.

## Uploaded logo/signature/stamp doesn't display after saving Library Profile

**Cause:** uploaded files are saved to `static/uploads/settings/{field}_{admin_id}_{secure_filename}` and the DB stores the path *relative to `static/`* (e.g. `uploads/settings/logo_1_foo.png`). If the path in `library_settings.logo_path` doesn't start with `uploads/settings/`, `url_for('static', filename=...)` will build a broken URL.
**Check:** inspect `library_settings.logo_path` for the affected admin directly, and confirm the file actually exists at `static/<that path>`.

## Sidebar badge counts (enquiries/students/memberships/payments) show blank or zero

**Cause:** `templates/layouts/sidebar.html` references `enquiries_new_count`, `students_new_today_count`, `memberships_expiring_soon_count`, `payments_pending_count`, but no route or context processor currently supplies them (Known Technical Debt item TD-15) — this isn't a bug you introduced, it's a pre-existing gap.
**Fix:** wire these into `app.py`'s existing `inject_notification_summary`-style context processor pattern, or remove the badge markup until it's built.

## New admin-scoped table/feature leaks across tenants immediately after adding it

**Cause:** almost certainly a missing `admin_id` filter on a new query, or a new table created without an `admin_id` column at all.
**Fix:** follow the `enquiries`/`students` pattern from day one (direct `admin_id` column + FK), not the `cashbook`/`expenses` pattern (retrofitted via `ALTER TABLE`, no FK possible) — see ADR-2 in [DECISIONS.md](DECISIONS.md).

## A Jinja `BuildError: Could not build url for endpoint '...'`

**Cause:** cross-blueprint redirects/links use `url_for('<blueprint>.<function>')` strings, not Python imports — renaming a blueprint or a route function breaks these silently until the URL is actually requested. See [09_DEPENDENCY_MAP.md](09_DEPENDENCY_MAP.md)'s "Cross-blueprint references" section for the known list of these couplings before renaming anything in `routes/student.py`, `routes/membership.py`, `routes/cashbook.py`, or `routes/setting.py`.
