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

## Panda shows "Something went wrong reaching Panda" or "Chat history isn't available yet."

**Cause (historical, fixed 2026-08-20):** both are generic, misleading text for the same underlying condition — the admin's session had lapsed (expired, or the cookie was cleared) by the time the widget sent the request. Before the fix, `static/js/panda.js` couldn't tell a real "something went wrong reaching Panda" (a genuine network error) apart from a plain `401 Unauthorized`, and couldn't handle app.py's app-wide `enforce_request_security()` CSRF guard rejecting a `POST` with an HTML error page (not JSON) before the request ever reached `panda/routes.py`. See the 2026-08-20 CHANGELOG entry and TD-64 in [11_FUTURE_WORK.md](11_FUTURE_WORK.md).
**If you see this now:** it means the session really has lapsed — refresh the page and log in again; the tables/feature are fine (verify directly: `panda_conversations`/`panda_messages` exist and are queryable via `database/panda_queries.py`, distinct from `CHAT_UNAVAILABLE_RESPONSE`'s "isn't set up yet" 503, which only fires if those tables genuinely don't exist).
**Where it surfaces:** the Panda chat widget on any authenticated page, most often after the browser tab has sat open past `PERMANENT_SESSION_LIFETIME` (60 minutes by default, `config.py`).

## Cross-admin data appears (Admin A sees Admin B's students/memberships/cashbook rows)

**Cause:** there is no framework-level tenant isolation — every query must manually filter by `admin_id` (directly, or via a join to a table that has it, e.g. `memberships`/`payments` via `students.admin_id`). This is a manual convention (ADR-2 in [DECISIONS.md](DECISIONS.md)), not something SQLite or Flask enforces.
**Diagnose:** find the query responsible and check it has a `WHERE admin_id = ?` (or the equivalent join filter). Compare against the patterns in [04_DATABASE_SCHEMA.md](04_DATABASE_SCHEMA.md)'s "Multi-tenant summary" table.
**Note:** `cashbook.admin_id` and `expenses.admin_id` used to have no FK constraint under SQLite; as of 2026-07-25 (ADR-32), the app runs entirely on Supabase (PostgreSQL), where every FK defined in `database/supabase_migration.sql` is enforced by the database itself — the manual "every query must filter by `admin_id`" convention above is still the actual isolation mechanism (Postgres FKs only guard referential integrity, not tenant isolation), it just no longer has SQLite's `ALTER TABLE`-can't-constrain caveat.

## `sqlite3.OperationalError: database is locked` / a `migrate_*.py` script errors (historical — not applicable since 2026-07-25)

**No longer possible:** as of 2026-07-25 (ADR-32, Phase 11), SQLite was removed from the app entirely — `database/db.py`, `database/schema.sql`, and every `database/migrate_*.py` script were deleted, and no route or query module opens a SQLite connection anywhere. These failure modes (SQLite's single-writer lock; migration scripts stepping on each other's schema changes) cannot occur anymore. If you're seeing a *connection* error against the current app, it will come from Supabase/PostgREST instead — check `database/supabase_client.py`'s `get_supabase_client()` raising `RuntimeError` for missing `SUPABASE_URL`/`SUPABASE_SECRET_KEY`, or a `postgrest.exceptions.APIError` from the request itself (see the "Unhandled `postgrest.exceptions.APIError`" entry below). Kept here as a historical record in case you're debugging an old deployment that predates ADR-32.

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

## Downloading a backup gives you more data than expected (historical — fixed 2026-07-25)

**Cause (historical, fixed 2026-07-25, ADR-32, TD-32 now `Resolved`):** `POST /settings/backup/create` used to copy and serve the entire shared `database/library.db` file, not a per-admin export. Any admin who clicked "Create Backup" downloaded every other admin's students/enquiries/memberships/payments/cashbook/audit-log rows, plus the full `admins` table (usernames, mobiles, bcrypt password hashes) for every account in the system — not just their own. Removing SQLite entirely (Phase 11) forced a rebuild of this feature: `backup_create()` now calls `_collect_admin_backup_data(admin_id)`, which queries every admin-scoped Supabase table filtered to the requesting admin only, and downloads a JSON export instead of a `.db` file.
**If you still see over-broad data in a backup:** you're on a version of `routes/setting.py` from before ADR-32 — pull the latest. Any backup file downloaded before 2026-07-25 should still be treated as containing every tenant's data.

## Changed my password in Settings but can't log in with it (or vice versa)

**Cause (historical — fixed 2026-07-23, same day as ADR-17):** between ADR-16 (2026-07-23, `routes/auth.py`'s Supabase cutover) and ADR-17 (later the same day), `routes/auth.py`'s `login()`/`forgot_password()` read/wrote `admins.password` in **Supabase**, while `routes/setting.py`'s `security_settings()` (Settings → Security Settings → Change Password) still read/wrote the **SQLite** copy of the same column — a deliberate, scoped consequence of migrating the auth module first, tracked as TD-35. `security_settings()`'s password branch now also uses `database/supabase_client.py`, the same Supabase copy `login()`/`forgot_password()` use — TD-35 is `Resolved`, and a password change via either path is immediately visible to the other.
**If you still see this:** you're on a version of `routes/setting.py` from before ADR-17 — pull the latest. Both `/forgot-password` and Settings → Security Settings now write the same Supabase `admins.password`.

## A newly registered admin gets `sqlite3.IntegrityError: FOREIGN KEY constraint failed` on Enquiries/Students/Settings/Audit Log

**Cause (historical — fixed 2026-07-23, same day as the auth cutover):** 7 tables enforce a real SQLite foreign key back to `admins.admin_id` (`database/db.py` sets `PRAGMA foreign_keys = ON` on every connection): `enquiries`, `students`, `audit_log` (written from Cashbook/Membership/Payment), and `library_settings`/`membership_settings`/`backup_log`/`security_settings` (all four owned by `routes/setting.py`). When `routes/auth.py`'s `register()` was first migrated to write only to Supabase, a brand-new admin existed there but not in SQLite — the moment they used any of those seven features, the SQLite insert failed the FK check. Caught live by running the full test suite (74 failures, all tracing back to a newly-registered test admin). Fixed the same session: `register()` now mirror-inserts the identical row (same `admin_id`) into SQLite immediately after the Supabase insert succeeds, rolling back the Supabase row if the SQLite insert fails.
**If you still see this:** you're on a version of `routes/auth.py` from before this fix — pull the latest. If it recurs after that, check whether something is creating admin rows in Supabase directly (e.g. the Supabase dashboard, a script) rather than through `register()` — those would bypass the mirror-insert entirely.

## `routes/auth.py`/`routes/setting.py`/`routes/enquiries.py`/`routes/student.py`/`routes/membership.py`/`routes/payment.py` returns a 500 / unhandled `postgrest.exceptions.APIError` on login, register, forgot-password, Security Settings password change, Enquiries add/edit/delete/view, Students index/admission/view/edit, Memberships index/create/renew, or Payments collect

**Cause:** `database/supabase_client.py`'s `get_supabase_client()` raises `RuntimeError` (not `APIError`) if `SUPABASE_URL`/`SUPABASE_SECRET_KEY` aren't set — check `.env` first. If those are set, `routes/auth.py` (ADR-16), `routes/setting.py`'s `security_settings()` password branch (ADR-17), `routes/enquiries.py` (ADR-18), `routes/student.py` (ADR-19), `routes/membership.py`/`database/membership_queries.py`'s `get_active_membership()` (ADR-20), and `routes/payment.py`'s `collect()` (ADR-21, all 2026-07-23) each wrap every Supabase call that carries user-controlled input in `try/except APIError` (added specifically because Supabase's Cloudflare-fronted edge network was observed to 403-block PostgREST `.eq()`/`.select()` GET requests whose query string looks like a SQL-injection payload, e.g. contains `DROP TABLE` — a failure mode SQLite's parameterized queries never had). A 500 here means either a genuinely new, unhandled Supabase error shape, or a code path that doesn't yet have the `try/except` — compare against ADR-16/ADR-17/ADR-18/ADR-19/ADR-20/ADR-21 in [DECISIONS.md](DECISIONS.md) for which calls are covered.
**Where it surfaces:** `POST /`, `POST /register`, `POST /forgot-password`, `POST /settings/security` (`form_type=password`), `GET /enquiries/`, `POST /enquiries/add`, `GET/POST /enquiries/edit/<id>`, `GET/POST /enquiries/delete/<id>`, `GET /enquiries/view/<id>`, `GET /students/`, `GET/POST /students/admission/<id>`, `GET /students/view/<id>`, `GET/POST /students/edit/<id>`, `GET /memberships/`, `GET/POST /memberships/create/<id>`, `GET/POST /memberships/renew/<id>`, `GET/POST /payments/collect/<id>`.

## A membership's `paid_amount`/`pending_amount` on the Memberships page (Supabase) looked stale right after collecting a payment on the Payments page

**Cause — historical, fixed 2026-07-23 (ADR-21), TD-37 now `Resolved`:** between ADR-20 and ADR-21, `routes/membership.py`'s `index()` read `memberships` from **Supabase**, but `routes/payment.py`'s `collect()` (unmigrated at the time) still wrote the pending-balance update (`paid_amount`/`pending_amount`) to the **SQLite** mirror only. A payment collected via `/payments/collect/<id>` updated the SQLite copy correctly (and everything that reads SQLite — `routes/dashboard.py`, `routes/membership_distribution.py`, `routes/notification.py`, the Student detail page — saw it immediately), but Supabase's copy of that same row kept the pre-payment `paid_amount`/`pending_amount` until the next time `routes/membership.py`'s `create()`/`renew()` wrote that row (which doesn't happen from a payment collection). Fixed when `routes/payment.py` was migrated (ADR-21): `collect()` now updates `paid_amount`/`pending_amount` in Supabase first, then mirrors the identical update into SQLite for the modules above that still need it.
**If you still see this:** you're on a version of `routes/payment.py` from before ADR-21 — pull the latest.

## Enquiries list/detail used to show "Interested" (or the pre-admission status) after a student was just admitted

**Cause — historical, fixed 2026-07-23 (ADR-19), TD-36 now `Resolved`:** between ADR-18 and ADR-19, `routes/enquiries.py`'s `index()`/`edit()`/`view()` read `enquiries.status` from **Supabase**, while `routes/student.py`'s `admission()` (unmigrated at the time) still ran `UPDATE enquiries SET status='Admitted' ...` against the **SQLite** mirror only — so a just-admitted enquiry kept showing its pre-admission status and an "Admission" action instead of the "Admitted" badge. Fixed when `routes/student.py` was migrated (ADR-19): `admission()` now updates `enquiries.status` via `database/supabase_client.py`'s `get_supabase_client()`, the same copy `routes/enquiries.py` reads, instead of the SQLite mirror.
**If you still see this:** you're on a version of `routes/student.py` from before ADR-19 — pull the latest.

## A Jinja `BuildError: Could not build url for endpoint '...'`

**Cause:** cross-blueprint redirects/links use `url_for('<blueprint>.<function>')` strings, not Python imports — renaming a blueprint or a route function breaks these silently until the URL is actually requested. See [09_DEPENDENCY_MAP.md](09_DEPENDENCY_MAP.md)'s "Cross-blueprint references" section for the known list of these couplings before renaming anything in `routes/student.py`, `routes/membership.py`, `routes/cashbook.py`, or `routes/setting.py`.
