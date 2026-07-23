# Troubleshooting Guide

Common issues, why they happen in this specific codebase, and how to fix or work around them.

## `ModuleNotFoundError: No module named 'matplotlib'` (or `numpy`)

**Cause (historical — resolved, verified 2026-07-22):** `requirements.txt` used to list only `Flask`/`Werkzeug` while `utils/charts.py` imports `matplotlib`/`numpy`. `requirements.txt` now includes both (`matplotlib>=3.7.0`, `numpy>=1.26.0`) — TD-8 in [11_FUTURE_WORK.md](11_FUTURE_WORK.md) is Resolved.
**If you still see this:** your virtualenv predates the fix — re-run `pip install -r requirements.txt`, don't hand-`pip install` just the two packages (the pinned versions matter).
**Where it surfaces (if it recurs):** any request to `GET /dashboard` or `GET /membership-distribution/` — both call into `utils/charts.py` synchronously, so the request itself 500s.

## Dashboard/Distribution charts show stale or another admin's data

**Cause:** `utils/charts.py` writes to fixed, shared filenames (`static/charts/revenue.png`, `membership.png`, `membership_distribution_donut.png`) regardless of which admin triggered generation. The chart only regenerates when the Dashboard or Distribution route actually runs — it isn't recomputed on every static-file request. Between two different admins' page loads, one can briefly see the other's chart.
**Fix (short-term):** reload the page again as the affected admin — it self-corrects the moment their own dashboard route runs.
**Fix (real):** namespace the output filename by `admin_id` (`revenue_{admin_id}.png`) in `utils/charts.py`, and update the three template components that reference the static path. Tracked as [11_FUTURE_WORK.md](11_FUTURE_WORK.md) TD-1.

## Dashboard/Membership Distribution/Cashbook/BI show different "revenue" or "collection rate" numbers

**Cause (historical, fixed 2026-07-21):** before this date, "Total Revenue" (Dashboard), "Revenue Collected" (Membership Distribution), and "Pending Fees" (Dashboard/Cashbook) were each computed by a separate copy of the same SQL/Python logic, and the Business Health Score's fee-collection component was accidentally dividing fee-specific pending amounts by *all* Cashbook income (including non-fee categories like Donation/Library Fine/Book Sale) instead of fee revenue only — see the 2026-07-21 "Financial system audit" entry in [CHANGELOG.md](CHANGELOG.md) and ADR-11 in [DECISIONS.md](DECISIONS.md).
**If you see a mismatch now:** it's not this bug reappearing by coincidence — check whether someone reintroduced a local copy of the revenue/pending-fee query instead of calling `database/cashbook_queries.py`'s `get_total_fee_revenue()`/`get_pending_fees()`. A genuine, *expected* difference is Cashbook's "Total Income (All Time)" reading higher than "Total Revenue"/"Revenue Collected" elsewhere — that's non-fee manual income (donations, fines, book sales) correctly included in Cashbook's broader total and correctly excluded from fee-specific figures.
**Where it surfaces:** `routes/dashboard.py`, `routes/membership_distribution.py`, `database/bi_queries.py`'s `get_business_health_score`.

## A membership shows "Active" on one page and "Expired" on another

**Cause (historical, fixed 2026-07-21):** `memberships.membership_status` never auto-flips to `'Expired'` when `end_date` passes — it only changes when a renewal explicitly marks the old row Expired. Every page that shows membership status has to combine the raw column with a date check itself, and before this date `routes/membership.py`'s `/memberships` list did not — it showed the raw column with no date comparison at all, while Dashboard/Student profile/Membership Distribution/Notifications all correctly recomputed it. See TD-6 in [11_FUTURE_WORK.md](11_FUTURE_WORK.md) and ADR-12 in [DECISIONS.md](DECISIONS.md).
**If you see a mismatch now:** check whether a new call site reads `m.membership_status` directly instead of `database/membership_queries.py`'s `EFFECTIVE_STATUS_SQL`/`get_effective_status()`. All five current call sites (`routes/membership.py`, `routes/dashboard.py`, `routes/student.py`, `routes/membership_distribution.py`, `routes/notification.py`) go through that module now — don't reintroduce a raw `m.membership_status` read for anything user-facing.
**Where it surfaces:** anywhere a membership's status is displayed or counted.

## Changing Settings → Membership Settings' plan fee/days has no effect on a new membership

**Cause (historical, fixed 2026-07-21):** `routes/membership.py`'s `create()`/`renew()` never read `membership_settings` — the Create/Renew forms' plan-duration/fee auto-fill was hardcoded in each template's inline `<script>`. See TD-7 in [11_FUTURE_WORK.md](11_FUTURE_WORK.md) and the 2026-07-21 "Membership workflow audit" entry in [CHANGELOG.md](CHANGELOG.md).
**If it still has no effect now:** confirm the admin has actually saved Settings → Membership Settings at least once for their account (`get_membership_settings(admin_id)` returns `None` until then, in which case Create/Renew fall back to the same 30/90/180/365-day, ₹0-fee defaults shown on the settings form itself — not a bug, just an unconfigured account). Also remember the auto-filled amount is editable, not enforced — a manually-changed `paid_amount`/`due_amount` is expected to stick even if it doesn't match the configured plan fee (e.g. a discount).
**Where it surfaces:** `templates/memberships/create.html`, `templates/memberships/renew.html`.

## Disabling a Notification Settings reminder toggle doesn't stop that reminder from appearing

**Cause:** `routes/notification.py`'s `get_notification_summary()` always computes the same fixed today/tomorrow/3-day/expired buckets for the navbar bell and Notifications page — it does not read `reminder_7_days`/`reminder_3_days`/`reminder_1_day`/`notify_on_expiry_day`/`notify_after_expiry` from Settings → Notification Settings. This is TD-28 in [11_FUTURE_WORK.md](11_FUTURE_WORK.md), still open — not something to "fix" by checking your config, the toggles genuinely have no effect on this yet.
**Where it surfaces:** `components/notification_dropdown.html`, `templates/notification/index.html`.

## Logged out unexpectedly / "please log in again" loops

**Cause:** Flask's session cookie is signed with `SECRET_KEY` (set in `app.py` from the `SECRET_KEY` env var, defaulting to a fixed literal string). If the env var changes between process restarts, every existing session cookie fails to validate and is treated as empty.
**Check:** is `SECRET_KEY` set in the environment, and is it stable across restarts? In `debug=True` dev mode, the auto-reloader restarts the *same* process config, so this is usually only an issue across full manual restarts with a different environment.

## Cross-admin data appears (Admin A sees Admin B's students/memberships/cashbook rows)

**Cause:** there is no framework-level tenant isolation — every query must manually filter by `admin_id` (directly, or via a join to a table that has it, e.g. `memberships`/`payments` via `students.admin_id`). This is a manual convention (ADR-2 in [DECISIONS.md](DECISIONS.md)), not something SQLite or Flask enforces.
**Diagnose:** find the query responsible and check it has a `WHERE admin_id = ?` (or the equivalent join filter). Compare against the patterns in [04_DATABASE_SCHEMA.md](04_DATABASE_SCHEMA.md)'s "Multi-tenant summary" table.
**Note:** `cashbook.admin_id` and `expenses.admin_id` have **no FK constraint** (added via `ALTER TABLE`, which SQLite can't constrain) — nothing stops a bad insert from writing a nonexistent or wrong `admin_id` at the database level; the application layer is the only guard.

## `sqlite3.OperationalError: database is locked`

**Cause:** `database/db.py`'s `get_connection()` opens a brand-new SQLite connection per request with no pooling. SQLite allows only one writer at a time; under concurrent write-heavy load (e.g. two admins submitting payments simultaneously, or a long-running read holding a transaction open), a writer can time out waiting for the lock. **Concretely happened, not just theoretical:** `routes/student.py`'s `edit()` had no `try/except` around its `UPDATE` — an unhandled `sqlite3.IntegrityError` (from a duplicate-mobile edit) left that request's connection un-closed, and the *next* request from anyone, on any route, that needed a write hit "database is locked" until the leaked connection was garbage-collected. Fixed 2026-07-22 (QA & Validation Sprint) — see [CHANGELOG.md](CHANGELOG.md).
**Fix:** at current single-admin-at-a-time scale a genuine concurrency ceiling is unlikely; look first for a connection that isn't being closed promptly — specifically, an unhandled exception between `get_connection()` and `conn.close()`/`conn.commit()` in any route (grep for `cursor.execute` calls with no surrounding `try/except` near a write) — before assuming it's a concurrency ceiling that needs WAL mode or a connection pool.

## A `migrate_*.py` script errors with "table already exists" or a column mismatch

**Cause:** there's no migration runner or version table — each script guards itself independently (`PRAGMA table_info` checks, `IF NOT EXISTS`), and correctness depends on running the right scripts in the right order on a fresh vs. existing database. The `transactions` table specifically is defined with two different shapes in `schema.sql` and `migrate_transactions.py` (see [04_DATABASE_SCHEMA.md](04_DATABASE_SCHEMA.md) and TD-2) — whichever runs first "wins".
**Fix:** before running any migration script against an existing `library.db`, check the table's actual current shape with `PRAGMA table_info(<table>)` in a SQLite shell rather than assuming either source file is authoritative.

## Editing a Cashbook entry fails / the Edit button doesn't work for some rows

**Cause:** by design, `routes/cashbook.py`'s `edit_transaction()` refuses to update any `cashbook` row whose `source` isn't exactly `"Cashbook Manual Entry"` — rows created automatically from Memberships/Payments (`source` values like `"Payments"`, `"Admission Fee"`, `"Membership Renewal"`) are intentionally read-only in this view (ADR-4 in [DECISIONS.md](DECISIONS.md)).
**Fix:** correct the underlying membership/payment record instead — the cashbook row is derived from it, not independently editable.

## Uploaded logo/signature/stamp doesn't display after saving Library Profile

**Cause:** uploaded files are saved to `static/uploads/settings/{field}_{admin_id}_{secure_filename}` and the DB stores the path *relative to `static/`* (e.g. `uploads/settings/logo_1_foo.png`). If the path in `library_settings.logo_path` doesn't start with `uploads/settings/`, `url_for('static', filename=...)` will build a broken URL.
**Check:** inspect `library_settings.logo_path` for the affected admin directly, and confirm the file actually exists at `static/<that path>`.

## Settings → Receipt Settings redirects straight back to Library Profile

**Cause:** by design — `routes/setting.py`'s `receipt_settings()` reuses the same `library_settings` row as Library Profile and only supports `UPDATE`, not insert (ADR-7 in [DECISIONS.md](DECISIONS.md)). If that admin hasn't saved a Library Profile yet, there's no row for it to update, so it redirects to `library_profile` with a flash message instead of erroring.
**Fix:** save Library Profile (name/owner/phone are required there) at least once, then Receipt Settings becomes reachable.

## Receipt numbers don't match what I configured in Settings → Receipt Settings

**Cause (pre-2026-07-22):** `routes/membership.py`/`routes/payment.py` generated receipt numbers with their own inline `REC-YYYYMMDD-...` formula and never read `library_settings.receipt_prefix`/`next_receipt_number` at all (TD-22). Fixed 2026-07-22 (ADR-13) — every payment-creating route now calls `database/payment_queries.py`'s `generate_receipt_number()`, which does read them.
**If you still see this after 2026-07-22:** confirm a `library_settings` row exists for that admin (Library Profile must be saved at least once — see the Receipt Settings entry above); with no row, receipt numbers fall back to a `LIB-01001`-style count-based sequence instead of the configured prefix/number.

## A payment/membership save fails with a red "database error" flash message and nothing was saved

**Cause:** as of 2026-07-22 (ADR-13), `routes/payment.py`'s `collect()` and `routes/membership.py`'s `create()`/`renew()` wrap their payment-recording sequence in `try/except sqlite3.Error: conn.rollback()`. This is the intended, safe failure mode — previously the same underlying error (most likely a `receipt_number` `UNIQUE` collision) would raise an uncaught `sqlite3.IntegrityError` and produce Flask's default error page instead of a usable message.
**Fix:** retry the submission — `conn.rollback()` guarantees the membership/payment/cashbook rows from the failed attempt were not partially written, so retrying is safe. If it fails repeatedly for the same admin, inspect `library_settings.next_receipt_number` for that admin directly; a manually edited/duplicated value could be colliding with an existing `payments.receipt_number`.

## Settings → Notification Settings redirects me to Library Profile

**Cause:** same reason as Receipt Settings above — `routes/setting.py`'s `notification_settings()` also reuses the `library_settings` row and only supports `UPDATE`, not insert (ADR-8 in [DECISIONS.md](DECISIONS.md)). If that admin hasn't saved a Library Profile yet, there's no row for it to update, so it redirects to `library_profile` with a flash message instead of erroring.
**Fix:** save Library Profile (name/owner/phone are required there) at least once, then Notification Settings becomes reachable. Note this is unrelated to Data & Backup or Security Settings, which use their own `backup_log`/`security_settings` tables and have no such prerequisite (ADR-9).

## Sidebar badge counts (enquiries/students/memberships/payments) show blank or zero

**Cause:** `templates/layouts/sidebar.html` references `enquiries_new_count`, `students_new_today_count`, `memberships_expiring_soon_count`, `payments_pending_count`, but no route or context processor currently supplies them (Known Technical Debt item TD-15) — this isn't a bug you introduced, it's a pre-existing gap.
**Fix:** wire these into `app.py`'s existing `inject_notification_summary`-style context processor pattern, or remove the badge markup until it's built.

## New admin-scoped table/feature leaks across tenants immediately after adding it

**Cause:** almost certainly a missing `admin_id` filter on a new query, or a new table created without an `admin_id` column at all.
**Fix:** follow the `enquiries`/`students` pattern from day one (direct `admin_id` column + FK), not the `cashbook`/`expenses` pattern (retrofitted via `ALTER TABLE`, no FK possible) — see ADR-2 in [DECISIONS.md](DECISIONS.md).

## Settings → Membership Settings won't save / 500s on submit

**Cause (historical, fixed 2026-07-22):** `database/membership_settings_queries.py`'s `save_membership_settings()` `INSERT` statement declared 14 columns but its `VALUES(...)` clause had only 13 `?` placeholders — `sqlite3.OperationalError: 13 values for 14 columns` on every single save attempt, with no `try/except` anywhere to catch it. See [CHANGELOG.md](CHANGELOG.md).
**If you still see this:** you're on a version of the code from before this fix — pull the latest `database/membership_settings_queries.py`.

## `/membership-analytics/` crashes or shows a completely blank page

**Cause (historical, fixed 2026-07-22):** `routes/membership_analytics.py` called `render_template("membership/analytics.html")` — that path doesn't exist (`templates/membership/`, singular, was never a real directory). The route now redirects to Membership Distribution instead of rendering anything (see PF-2 in [11_FUTURE_WORK.md](11_FUTURE_WORK.md)).
**If you still see this:** you're on a version of the code from before this fix.

## Editing a student's mobile number crashes

**Cause (historical, fixed 2026-07-22):** `routes/student.py`'s `edit()` had no `try/except` around its `UPDATE` — setting a mobile number already used by another student of the same admin violates `students`' `UNIQUE(mobile, admin_id)` and raised an unhandled `sqlite3.IntegrityError`. See the "database is locked" entry above for the follow-on effect this had on unrelated requests, and [CHANGELOG.md](CHANGELOG.md) for the fix.
**If you still see this:** you're on a version of the code from before this fix.

## Downloading a backup gives you more data than expected

**Cause — this is a live, unresolved issue, not a historical one (TD-32 in [11_FUTURE_WORK.md](11_FUTURE_WORK.md), Critical, Open):** `POST /settings/backup/create` copies and serves the entire shared `database/library.db` file, not a per-admin export. Any admin who clicks "Create Backup" downloads every other admin's students/enquiries/memberships/payments/cashbook/audit-log rows, plus the full `admins` table (usernames, mobiles, bcrypt password hashes) for every account in the system — not just their own.
**This is not a bug to "fix" by changing your usage** — it's a real defect in `routes/setting.py`'s `backup_create()`. Treat any existing downloaded backup file as containing every tenant's data, and restrict who can reach Settings → Data & Backup until this is addressed (a real per-admin export, or a role-gated permission system — see PF-4, which doesn't exist yet).

## Changed my password in Settings but can't log in with it (or vice versa)

**Cause (historical — fixed 2026-07-23, same day as ADR-17):** between ADR-16 (2026-07-23, `routes/auth.py`'s Supabase cutover) and ADR-17 (later the same day), `routes/auth.py`'s `login()`/`forgot_password()` read/wrote `admins.password` in **Supabase**, while `routes/setting.py`'s `security_settings()` (Settings → Security Settings → Change Password) still read/wrote the **SQLite** copy of the same column — a deliberate, scoped consequence of migrating the auth module first, tracked as TD-35. `security_settings()`'s password branch now also uses `database/supabase_client.py`, the same Supabase copy `login()`/`forgot_password()` use — TD-35 is `Resolved`, and a password change via either path is immediately visible to the other.
**If you still see this:** you're on a version of `routes/setting.py` from before ADR-17 — pull the latest. Both `/forgot-password` and Settings → Security Settings now write the same Supabase `admins.password`.

## A newly registered admin gets `sqlite3.IntegrityError: FOREIGN KEY constraint failed` on Enquiries/Students/Settings/Audit Log

**Cause (historical — fixed 2026-07-23, same day as the auth cutover):** 7 tables enforce a real SQLite foreign key back to `admins.admin_id` (`database/db.py` sets `PRAGMA foreign_keys = ON` on every connection): `enquiries`, `students`, `audit_log` (written from Cashbook/Membership/Payment), and `library_settings`/`membership_settings`/`backup_log`/`security_settings` (all four owned by `routes/setting.py`). When `routes/auth.py`'s `register()` was first migrated to write only to Supabase, a brand-new admin existed there but not in SQLite — the moment they used any of those seven features, the SQLite insert failed the FK check. Caught live by running the full test suite (74 failures, all tracing back to a newly-registered test admin). Fixed the same session: `register()` now mirror-inserts the identical row (same `admin_id`) into SQLite immediately after the Supabase insert succeeds, rolling back the Supabase row if the SQLite insert fails.
**If you still see this:** you're on a version of `routes/auth.py` from before this fix — pull the latest. If it recurs after that, check whether something is creating admin rows in Supabase directly (e.g. the Supabase dashboard, a script) rather than through `register()` — those would bypass the mirror-insert entirely.

## `routes/auth.py`/`routes/setting.py` returns a 500 / unhandled `postgrest.exceptions.APIError` on login, register, forgot-password, or Security Settings password change

**Cause:** `database/supabase_client.py`'s `get_supabase_client()` raises `RuntimeError` (not `APIError`) if `SUPABASE_URL`/`SUPABASE_SECRET_KEY` aren't set — check `.env` first. If those are set, both `routes/auth.py` (ADR-16) and `routes/setting.py`'s `security_settings()` password branch (ADR-17, 2026-07-23) wrap every Supabase call that carries user-controlled input in `try/except APIError` (added specifically because Supabase's Cloudflare-fronted edge network was observed to 403-block PostgREST `.eq()`/`.select()` GET requests whose query string looks like a SQL-injection payload, e.g. contains `DROP TABLE` — a failure mode SQLite's parameterized queries never had). A 500 here means either a genuinely new, unhandled Supabase error shape, or a code path that doesn't yet have the `try/except` — compare against ADR-16/ADR-17 in [DECISIONS.md](DECISIONS.md) for which calls are covered.
**Where it surfaces:** `POST /`, `POST /register`, `POST /forgot-password`, `POST /settings/security` (`form_type=password`).

## A Jinja `BuildError: Could not build url for endpoint '...'`

**Cause:** cross-blueprint redirects/links use `url_for('<blueprint>.<function>')` strings, not Python imports — renaming a blueprint or a route function breaks these silently until the URL is actually requested. See [09_DEPENDENCY_MAP.md](09_DEPENDENCY_MAP.md)'s "Cross-blueprint references" section for the known list of these couplings before renaming anything in `routes/student.py`, `routes/membership.py`, `routes/cashbook.py`, or `routes/setting.py`.
