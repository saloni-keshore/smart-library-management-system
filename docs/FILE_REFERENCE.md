# File Reference

Per-file cards for every important source file: **Purpose**, **Responsibilities**, **Functions/Classes**, **Files it depends on**, **Files that depend on it**, **Future modification notes**.

"Depends on" / "depended on by" are drawn from a grep of every `import`/`from` statement in the project (verified 2026-07-20, see [DIAGRAMS.md](DIAGRAMS.md) for the same data as a graph) — cross-blueprint `url_for` couplings (runtime-only, not imports) are noted separately where relevant. If you add or remove an import, update the two matching cards (both sides of the edge) in the same change.

---

## Root

### `app.py`
- **Purpose:** Flask application factory and process entry point.
- **Responsibilities:** Create the Flask app, set `SECRET_KEY`, register all 13 blueprints, define the one global context processor that feeds both the navbar notification bell and the navbar's notification-display preferences on every page.
- **Functions/Classes:** `create_app()`; module-level `app = create_app()`; module constant `DEFAULT_NAV_NOTIFICATION_PREFS` (all four flags `True`); no classes. Inline `inject_notification_summary()` registered via `@app.context_processor` — now also computes `nav_notification_prefs` (a dict of `dash_show_badge_count`/`dash_show_expiry_today`/`dash_show_expiry_tomorrow`/`dash_show_overdue`, read via `get_notification_settings_cached(admin_id)` and defaulting to `DEFAULT_NAV_NOTIFICATION_PREFS` when there's no session or no `library_settings` row yet) alongside the existing `nav_notifications`.
- **Depends on:** `routes.auth`, `routes.dashboard`, `routes.enquiries`, `routes.student`, `routes.membership`, `routes.payment`, `routes.cashbook`, `routes.report`, `routes.setting`, `routes.notification` (also imports `get_notification_summary`), `routes.membership_analytics`, `routes.membership_distribution`, `routes.business_intelligence`, `database.notification_settings_queries.get_notification_settings_cached`.
- **Depended on by:** nothing imports `app.py` — it's the process entry point (`python app.py`); `templates/components/notification_dropdown.html` consumes both `nav_notifications` and `nav_notification_prefs` from this context processor.
- **Future modification notes:** This is the right place to add a centralized auth-check decorator/`before_request` hook (currently duplicated in nearly every route — see [Known Technical Debt](11_FUTURE_WORK.md)), to wire in `config.py` (currently unused), to add 404/500 error handlers, and to make `debug=True` conditional on an environment variable before any real deployment. If you add more dashboard-display toggles to Notification Settings that should also affect the navbar, extend `nav_notification_prefs`/`DEFAULT_NAV_NOTIFICATION_PREFS` here rather than reading settings again from inside the template. Uses `get_notification_settings_cached()` (not the raw `get_notification_settings()`) specifically because `routes/dashboard.py` also needs the same admin's row on the same `/dashboard` request — the `_cached` wrapper memoizes on `flask.g` so that's one query, not two (fixed 2026-07-21, see [CHANGELOG.md](CHANGELOG.md)). If you add a third call site within a request, it gets the dedup for free; don't call the raw `get_notification_settings()` directly from route/context-processor code.

### `config.py`
- **Purpose:** Intended centralized environment configuration. **Currently dead code** — not imported anywhere.
- **Responsibilities (as designed, unused):** Supply `SECRET_KEY`/`DEBUG` per environment.
- **Functions/Classes:** `Config` (base), `DevelopmentConfig(Config)`, `ProductionConfig(Config)`.
- **Depends on:** `os` only.
- **Depended on by:** nothing.
- **Future modification notes:** Either wire it into `app.py` via `app.config.from_object(...)` selected by an env var, or delete it — leaving it unused invites a future contributor to edit it and wonder why nothing changes.

---

## `database/`

### `database/db.py`
- **Purpose:** The single shared SQLite connection factory.
- **Responsibilities:** Resolve `library.db`'s absolute path (anchored to `database/` via `__file__`, independent of CWD), open a connection, set `row_factory = sqlite3.Row`.
- **Functions/Classes:** `get_connection()`. Module constants `BASE_DIR`, `DATABASE_PATH`.
- **Depends on:** `sqlite3`, `pathlib.Path`.
- **Depended on by:** `database/audit_queries.py`, `database/bi_queries.py`, `database/cashbook_queries.py`, `database/membership_settings_queries.py`, `database/settings_queries.py`, `utils/charts.py`, `routes/dashboard.py`, `routes/membership.py`, `routes/membership_distribution.py`, `routes/notification.py`, `routes/payment.py`, `routes/student.py`, `routes/setting.py` (all routes except `security_settings()`'s password branch — see below), `routes/enquiries.py` (as a SQLite mirror-write target, not the source of truth — see below and its own card). Also imported by every `migrate_*.py` script and `database/migrate.py`, but via the bare `from db import get_connection` form rather than `from database.db import get_connection` — an inconsistent import style that only works because those scripts are always run standalone (Known Technical Debt item TD-21). `routes/auth.py`'s `login()`/`forgot_password()` no longer use this as of 2026-07-23 (ADR-16) — but `register()` still does, as a one-table mirror-insert bridge (see its own card below, and TD-35). `routes/setting.py`'s `security_settings()` password-change branch also stopped using this as of 2026-07-23 (ADR-17) — every other function in that file still does. `routes/enquiries.py` stopped using this for reads as of the same day (ADR-18) — Supabase is now the source of truth for `enquiries`, and this is used only to keep a SQLite mirror in sync (`add()`/`edit()`/`delete()`) and to look up `students` (unmigrated) for `index()`/`view()`.
- **Future modification notes:** `PRAGMA foreign_keys = ON` is **not** set here — it only runs once at schema-init time inside `schema.sql`. If you need FK enforcement at runtime, add `connection.execute("PRAGMA foreign_keys = ON")` here (test this doesn't break any existing insert order first). No connection pooling exists; every request opens/closes its own connection — fine at current scale, worth revisiting under real concurrent load.

### `database/schema.sql`
- **Purpose:** Full DDL — source of truth for creating every table from scratch.
- **Responsibilities:** Define `admins`, `settings` (legacy/unused), `enquiries`, `students`, `memberships`, `payments`, `cashbook` (+ inline `ALTER TABLE` extensions), `expenses` (unused), `transactions` (⚠ conflicting second definition also exists in `migrate_transactions.py`), `audit_log`, `library_settings` (now including the 19 Notification Settings columns — reminder rules, channels, quiet hours, dashboard-display flags), `membership_settings` (with a comment noting `reminder_days`/`send_reminders` are superseded/unused), `backup_log` (new, one row per admin), `security_settings` (new, one row per admin). Sets `PRAGMA foreign_keys = ON;` at the top.
- **Functions/Classes:** N/A (pure SQL).
- **Depends on:** nothing (plain SQL file).
- **Depended on by:** `database/seed.py` (executed via `executescript()`).
- **Future modification notes:** Full column-level detail in [04_DATABASE_SCHEMA.md](04_DATABASE_SCHEMA.md). When adding a table here, also add a corresponding `migrate_*.py` script for existing installs that already ran an older version of this file — `schema.sql` alone won't retrofit an existing `library.db`.

### `database/supabase_migration.sql`
- **Purpose:** Hand-translated PostgreSQL equivalent of `schema.sql`, meant to be pasted into the Supabase SQL Editor to create the same schema on Supabase.
- **Responsibilities:** Define the same 14 tables as `schema.sql` (`admins`, `settings`, `enquiries`, `students`, `memberships`, `payments`, `cashbook` (+ its 6 `ALTER TABLE` columns folded in), `expenses`, `transactions`, `audit_log`, `library_settings`, `membership_settings`, `backup_log`, `security_settings`) in PostgreSQL syntax, wrapped in `BEGIN;`/`COMMIT;`. `AUTOINCREMENT` → `GENERATED BY DEFAULT AS IDENTITY`; `REAL` → `DOUBLE PRECISION`; no `PRAGMA`.
- **Functions/Classes:** N/A (pure SQL).
- **Depends on:** nothing (plain SQL file); mirrors `database/schema.sql`.
- **Depended on by:** nothing yet — not executed by any script or route. Intended to be run manually, once, in the Supabase SQL Editor.
- **Future modification notes:** See ADR-14 and TD-34. Any table/column/constraint change made to `schema.sql` must be mirrored here by hand (and vice versa) until the app actually cuts over to Supabase — there is no automated sync between the two files.

### `database/supabase_client.py`
- **Purpose:** The single shared Supabase (PostgREST) client factory — the Supabase equivalent of `database/db.py`'s `get_connection()`, for modules that have been cut over off SQLite.
- **Responsibilities:** Read `SUPABASE_URL`/`SUPABASE_SECRET_KEY` from the environment (via `python-dotenv`'s `load_dotenv()`, same variables `test_supabase.py`/`database/migrate_to_supabase.py` already use), raise `RuntimeError` if either is missing, and construct one `supabase.Client`. Unlike `get_connection()` (a new SQLite connection per call), the client is cached process-wide with `functools.lru_cache(maxsize=1)` since it's a plain HTTP client wrapper, not a stateful DB connection.
- **Functions/Classes:** `get_supabase_client()`.
- **Depends on:** `python-dotenv`, `supabase` (already in `requirements.txt`), `.env` (`SUPABASE_URL`/`SUPABASE_SECRET_KEY`).
- **Depended on by:** `routes/auth.py` (as of 2026-07-23 — see ADR-16); `routes/setting.py`'s `security_settings()` password-change branch only (as of 2026-07-23 — see ADR-17); `routes/enquiries.py` (as of 2026-07-23 — see ADR-18, source of truth for `enquiries`); `tests/conftest.py`'s `get_admin_by_username()`/`get_enquiry_by_id()` helpers, `tests/test_01_auth.py`, `tests/test_02_enquiry.py`.
- **Future modification notes:** This is the first reusable app-facing Supabase client — as more modules are cut over from SQLite (per the incremental migration plan in ADR-16), they should import `get_supabase_client()` from here rather than each rolling their own `create_client(...)` call. `routes/setting.py`'s `security_settings()` is the second consumer (ADR-17), `routes/enquiries.py` the third (ADR-18), both reusing the same cached instance. `database/migrate_to_supabase.py` deliberately keeps its own separate `get_supabase_client()` (it's a standalone script, not part of the running app) — don't merge the two.

### `database/migrate_to_supabase.py`
- **Purpose:** One-time data migration — copies every row from `database/library.db` (SQLite) into the PostgreSQL tables created by `database/supabase_migration.sql` on Supabase, preserving primary key values.
- **Responsibilities:** For each of the 14 tables, in FK-safe order (`TABLES_IN_ORDER`, mirroring `supabase_migration.sql`'s creation order): check the table actually exists in SQLite via `sqlite_master` first, logging and skipping (not erroring) any that don't -- real `library.db` files don't always have every table `schema.sql` defines (e.g. `expenses`, see TD-3); read all SQLite rows; pre-flight-abort the whole run if *any* destination table already has data (prevents duplicate imports); sanitize every DATE/TIMESTAMP column (`TEMPORAL_COLUMNS`) on the in-memory copy of each row — empty strings, and case-insensitive `"none"`/`"null"`, and any value that isn't a valid ISO date/datetime become `NULL`, each correction logged with its table/primary key/column (`library.db` itself is never touched); insert the sanitized rows via the Supabase Python client, preserving explicit PKs (works because `schema.sql`'s identity columns are `GENERATED BY DEFAULT`, not `GENERATED ALWAYS` — see ADR-14); verify the Supabase row count matches SQLite's, stopping immediately on any mismatch; attempt to reset that table's identity sequence via an optional `migrate_reset_identity_sequence` RPC, printing the equivalent manual `setval(...)` SQL at the end for any table where that RPC isn't present (see ADR-15). Prints a full per-table report (including a "Sanitized" column and count) plus a full sanitization log, and exits non-zero if any table fails verification. Never writes to `library.db`.
- **Functions/Classes:** `get_sqlite_connection`, `get_supabase_client`, `sqlite_table_exists`, `fetch_sqlite_rows`, `sanitize_temporal_value`, `sanitize_temporal_columns`, `get_remote_count`, `preflight_check`, `insert_rows`, `try_reset_sequence`, `manual_setval_sql`, `print_report`, `print_sanitization_log`, `run`, `main`; `MigrationError` (control-flow exception for a clean abort).
- **Depends on:** `sqlite3`, `python-dotenv`, `supabase`/`postgrest` (already in `requirements.txt`), `.env` (`SUPABASE_URL`/`SUPABASE_SECRET_KEY`, same variables as `test_supabase.py`), `database/library.db`, and implicitly `database/supabase_migration.sql` (must already be applied on the Supabase side before this script is run).
- **Depended on by:** run manually, once (`python database/migrate_to_supabase.py`); nothing imports it.
- **Future modification notes:** Does not touch `routes/`, `database/db.py`, or the SQLite schema — the Flask app keeps reading/writing SQLite until a separate connection-layer cutover happens. If a new table is added to `schema.sql`/`supabase_migration.sql`, add it to `TABLES_IN_ORDER` here too, in FK-safe position.

### `database/seed.py`
- **Purpose:** Despite its name, this does **not** insert sample/seed data — it (re)creates the schema.
- **Responsibilities:** Open `library.db`, run `schema.sql` via `executescript()`, commit.
- **Functions/Classes:** `initialize_database()`.
- **Depends on:** `sqlite3`, `pathlib.Path`, `werkzeug.security.generate_password_hash` (imported but **never used** — dead import).
- **Depended on by:** run manually (`python database/seed.py`); nothing imports it.
- **Future modification notes:** Either rename to reflect what it actually does (`init_db.py`) or add real seed-data insertion and keep the name. Remove the dead `generate_password_hash` import either way.

### `database/migrate.py`
- **Purpose:** The original multi-tenant retrofit migration.
- **Responsibilities:** Add `admin_id` to `enquiries` (idempotent column check); recreate `students` with `admin_id` + `UNIQUE(mobile, admin_id)` (create-new/copy/drop/rename), backfilling existing rows to the first admin found.
- **Functions/Classes:** top-level procedural script (check the file directly for exact function boundaries — no exported functions consumed elsewhere).
- **Depends on:** `db.get_connection` (bare import — only resolves when run standalone as `python database/migrate.py`, since Python adds the invoked script's own directory to `sys.path[0]`).
- **Depended on by:** nothing (run manually, once, on legacy databases).
- **Future modification notes:** This was a one-time retrofit; don't reuse this pattern for new tables — start new admin-scoped tables with `admin_id` + FK from day one instead (see ADR-2 in [DECISIONS.md](DECISIONS.md)).

### `database/migrate_audit_log.py`
- **Purpose:** Creates the `audit_log` table.
- **Responsibilities:** `CREATE TABLE IF NOT EXISTS audit_log (...)`.
- **Depends on:** `db.get_connection` (bare import, standalone-only).
- **Depended on by:** nothing (run manually).
- **Future modification notes:** Fully idempotent; safe to re-run.

### `database/migrate_backfill_cashbook_payments.py`
- **Purpose:** One-off **data** backfill (not a schema change) — creates missing `cashbook` rows for historical `payments` that predate the cashbook feature.
- **Responsibilities:** Join `payments`/`students`/`memberships`, detect payments with no matching `cashbook` row, insert one via `insert_income_entry`, classifying category by position (Admission Fee / Membership Renewal / Membership Fee).
- **Depends on:** `database.db.get_connection`, `database.cashbook_queries.insert_income_entry` (this script is the one exception that uses the full `database.db`/`database.cashbook_queries` package-qualified imports plus manual `sys.path` setup, rather than the bare `db` import the other migration scripts use).
- **Depended on by:** nothing (run manually, once).
- **Future modification notes:** Effectively idempotent (dedupes via an existence check) but not guaranteed — if you re-run it against a DB that already has some but not all backfilled entries, verify the matching heuristic (admin_id/person/amount/entry_date) still holds before trusting it blindly.

### `database/migrate_cashbook_ledger.py`
- **Purpose:** Adds `cashbook.reference_id` and `cashbook.source` columns.
- **Responsibilities:** `PRAGMA table_info` guard, then `ALTER TABLE cashbook ADD COLUMN ...` for each.
- **Depends on:** `db.get_connection` (bare import, standalone-only).
- **Depended on by:** nothing (run manually).
- **Future modification notes:** Fully idempotent; safe to re-run. `source` is a load-bearing value elsewhere — `"Cashbook Manual Entry"` is the literal string `routes/cashbook.py` checks to allow edits (see ADR-4 in [DECISIONS.md](DECISIONS.md)); don't rename it without updating that check.

### `database/migrate_library_settings.py`
- **Purpose:** Creates the `library_settings` table (without `receipt_footer` — added later separately).
- **Depends on:** `db.get_connection` (bare import, standalone-only).
- **Depended on by:** nothing (run manually).
- **Future modification notes:** Fully idempotent (`IF NOT EXISTS`).

### `database/migrate_settings_receipt_footer.py`
- **Purpose:** Adds `library_settings.receipt_footer` column.
- **Depends on:** `db.get_connection` (bare import, standalone-only).
- **Depended on by:** nothing (run manually).
- **Future modification notes:** Fully idempotent (`PRAGMA table_info` guard).

### `database/migrate_membership_setting.py`
- **Purpose:** Creates the `membership_settings` table.
- **Responsibilities:** If the table already exists, validates its columns against an `EXPECTED_COLUMNS` set and raises `RuntimeError` if incompatible; otherwise `CREATE TABLE IF NOT EXISTS`.
- **Functions/Classes:** `run()`; module constant `EXPECTED_COLUMNS`.
- **Depends on:** `db.get_connection` (bare import, standalone-only).
- **Depended on by:** nothing (run manually).
- **Future modification notes:** The compatibility guard here is the most defensive of all the migration scripts — a good template to follow for future ones instead of a bare `CREATE TABLE IF NOT EXISTS`.

### `database/migrate_receipt_settings.py`
- **Purpose:** Adds receipt numbering/branding/printing columns to the existing `library_settings` table (no new table).
- **Responsibilities:** `ALTER TABLE ADD COLUMN` for `receipt_prefix`, `next_receipt_number`, `auto_increment_receipt`, `print_logo`, `print_stamp`, `print_signature`, `paper_size`, `auto_print`, `auto_email`, `open_pdf_after_save`, `duplicate_copy` — one at a time, each checked against `PRAGMA table_info` first.
- **Functions/Classes:** `run()`; module constant `NEW_COLUMNS` (name → SQL type/default).
- **Depends on:** `db.get_connection` (bare import, standalone-only).
- **Depended on by:** nothing (run manually).
- **Future modification notes:** Follows the same idempotent single-column-ALTER pattern as `migrate_settings_receipt_footer.py` — reuse it if more `library_settings` columns are added later rather than introducing a new migration-runner convention.

### `database/migrate_notification_settings.py`
- **Purpose:** Adds the 19 reminder-rule/channel/quiet-hours/dashboard-display columns to the existing `library_settings` table (no new table).
- **Responsibilities:** `ALTER TABLE ADD COLUMN` for `reminder_7_days`, `reminder_3_days`, `reminder_1_day`, `notify_on_expiry_day`, `notify_after_expiry`, `notify_in_app`, `notify_sms`, `notify_email`, `notify_whatsapp`, `quiet_hours_enabled`, `quiet_hours_start`, `quiet_hours_end`, `quiet_hours_allow_critical`, `dash_show_badge_count`, `dash_show_expiry_today`, `dash_show_expiry_tomorrow`, `dash_show_overdue`, `dash_show_pending_fees`, `dash_show_new_admissions` — one at a time, each checked against `PRAGMA table_info` first.
- **Functions/Classes:** `run()`; module constant `NEW_COLUMNS` (name → SQL type/default).
- **Depends on:** `db.get_connection` (bare import, standalone-only).
- **Depended on by:** nothing (run manually).
- **Future modification notes:** Same idempotent single-column-ALTER pattern as `migrate_receipt_settings.py` — reuse it for any further `library_settings` additions.

### `database/migrate_backup_log.py`
- **Purpose:** Creates the `backup_log` table.
- **Responsibilities:** If the table already exists, validates its columns against an `EXPECTED_COLUMNS` set and raises `RuntimeError` if incompatible; otherwise `CREATE TABLE IF NOT EXISTS`.
- **Functions/Classes:** `run()`; module constant `EXPECTED_COLUMNS`.
- **Depends on:** `db.get_connection` (bare import, standalone-only).
- **Depended on by:** nothing (run manually).
- **Future modification notes:** Follows the same defensive compatibility-guard pattern as `migrate_membership_setting.py`.

### `database/migrate_security_settings.py`
- **Purpose:** Creates the `security_settings` table.
- **Responsibilities:** Same compatibility-guard pattern as `migrate_backup_log.py`, then `CREATE TABLE IF NOT EXISTS security_settings (...)`.
- **Functions/Classes:** `run()`; module constant `EXPECTED_COLUMNS`.
- **Depends on:** `db.get_connection` (bare import, standalone-only).
- **Depended on by:** nothing (run manually).
- **Future modification notes:** Follows the same defensive compatibility-guard pattern as `migrate_membership_setting.py`/`migrate_backup_log.py`.

### `database/migrate_transactions.py`
- **Purpose:** Creates a `transactions` table — ⚠ with a **different shape** than the one also defined in `schema.sql` (see [04_DATABASE_SCHEMA.md](04_DATABASE_SCHEMA.md) and Known Technical Debt item TD-2).
- **Depends on:** `db.get_connection` (bare import, standalone-only).
- **Depended on by:** nothing — and notably, **no route or query module reads/writes the `transactions` table at all**.
- **Future modification notes:** Reconcile with `schema.sql`'s definition or delete both — don't build new functionality on this table until the ambiguity is resolved.

### `database/audit_queries.py`
- **Purpose:** Append-only audit trail for cashbook financial changes.
- **Responsibilities:** Write an audit row inside the same transaction as the cashbook change it documents; read recent audit history for display.
- **Functions/Classes:** `log_entry(cursor, admin_id, entry_id, action, details)` (takes an existing cursor, does not open/close its own connection); `get_recent_audit_log(admin_id, limit=15)` (opens its own connection, left-joins `admins` for `performed_by`).
- **Depends on:** `database.db.get_connection` (used by `get_recent_audit_log` only).
- **Depended on by:** `database/cashbook_queries.py` (`log_entry`, called from `insert_transaction`, `insert_income_entry`, `update_manual_transaction`), `routes/cashbook.py` (`get_recent_audit_log`).
- **Future modification notes:** Keep `log_entry`'s "takes a cursor, doesn't commit" contract intact — it's what guarantees an audit row can never exist without its corresponding change. Don't add a `conn.commit()` inside it.

### `database/bi_queries.py`
- **Purpose:** Business-intelligence aggregation layer built on top of `cashbook_queries`.
- **Responsibilities:** Compute revenue growth, retention, health score, top categories, action items, and activity timeline — all admin-scoped.
- **Functions/Classes:** `last_n_months(n=6)`, `get_monthly_new_memberships(admin_id)`, `get_membership_retention(admin_id)`, `get_upcoming_expiries(admin_id, days=7)`, `get_revenue_growth(admin_id)`, `classify_revenue_health(growth_pct)`, `classify_expense_health(admin_id)`, `get_business_health_score(admin_id)`, `_rank_categories(totals, limit=5)`, `get_top_revenue_sources(admin_id, limit=5)`, `get_top_expense_categories(admin_id, limit=5)`, `get_action_items(admin_id)`, `get_business_timeline(admin_id, limit=8)`.
- **Depends on:** `database.db.get_connection`, `database.cashbook_queries` (`get_monthly_income`, `get_monthly_expense`, `get_income_category_totals`, `get_expense_category_totals`, `get_pending_fees`, `get_total_fee_revenue`).
- **Depended on by:** `routes/business_intelligence.py`.
- **Future modification notes:** `get_business_health_score`'s weighting (30% growth / 30% expense discipline / 20% fee collection / 20% renewal rate) is a business decision, not a technical one — if it changes, document the new weights and rationale in [DECISIONS.md](DECISIONS.md), not just here. The fee-collection component's `billable` denominator uses `get_total_fee_revenue()` (Payments-sourced), **not** `get_total_income()` — see ADR-11 in [DECISIONS.md](DECISIONS.md) for why blending non-fee Cashbook income (donations, fines, book sales) into that ratio was a bug, fixed 2026-07-21.

### `database/cashbook_categories.py`
- **Purpose:** Single source of truth for category/payment-method constant lists.
- **Responsibilities:** None beyond holding data — no DB access, no functions.
- **Functions/Classes:** none — module-level lists `AUTO_CATEGORIES`, `MANUAL_INCOME_CATEGORIES`, `MANUAL_EXPENSE_CATEGORIES`, `ALL_CATEGORIES`, `PAYMENT_METHODS`.
- **Depends on:** nothing.
- **Depended on by:** `routes/cashbook.py`, `routes/dashboard.py`.
- **Future modification notes:** If you add a new manual category here, it immediately becomes selectable in both the Cashbook and Dashboard quick-add forms — no other code change needed. Keep `AUTO_CATEGORIES` (Admission Fee, Membership Fee, Membership Renewal) in sync with the literal strings passed to `record_payment()` in `database/payment_queries.py`. `PAYMENT_METHODS` now includes `"Card"` (fixed 2026-07-22, Payment Workflow Audit) — the Payment Collect / Membership Create / Membership Renew forms have offered "Card" as a `payment_mode` option since before this list existed, but this list (which drives Cashbook's payment-method filter dropdown and its manual-entry validation, `payment_method not in PAYMENT_METHODS`) didn't include it, so a Card payment could be recorded but never filtered to in Cashbook. If you add another payment mode to those three forms, add it here in the same commit.

### `database/cashbook_queries.py`
- **Purpose:** Core admin-isolated data-access layer for the financial ledger. The largest and most-depended-on query module.
- **Responsibilities:** Manual + automatic transaction inserts/updates, all aggregate reads (totals, monthly series, category breakdowns, payment-method distribution, cash balance, pagination/filtering for the ledger view).
- **Functions/Classes:** `_generate_reference_id(cursor, prefix)`, `get_recent_transactions(admin_id, limit=10)`, `insert_transaction(admin_id, transaction_type, category, person, description, amount, payment_method, entry_date)`, `insert_income_entry(conn, admin_id, category, person, description, amount, payment_method, entry_date, source, reference_prefix="PAY", payment_id=None)`, `get_transaction_by_id(admin_id, entry_id)`, `update_manual_transaction(admin_id, entry_id, category, person, description, amount, payment_method, entry_date)`, `_get_total_by_type`, `get_total_income`, `get_total_expense`, `_get_today_total_by_type`, `get_today_income`, `get_today_expense`, `get_pending_fees(admin_id)`, `get_today_fee_collection(admin_id)` (added 2026-07-21), `get_total_fee_revenue(admin_id)`, `_monthly_totals_by_type`, `get_monthly_income`, `get_monthly_expense`, `get_monthly_profit`, `_category_totals_by_type`, `get_income_category_totals`, `get_expense_category_totals`, `get_payment_method_distribution(admin_id)`, `get_cash_balance(admin_id)`, `get_todays_transaction_count(admin_id)`, `get_cashbook_ledger(admin_id, search=None, date_from=None, date_to=None, transaction_type=None, category=None, payment_method=None, source=None, page=1, per_page=10)`.
- **Depends on:** `database.db.get_connection`, `database.audit_queries.log_entry`.
- **Depended on by:** `database/bi_queries.py`, `routes/business_intelligence.py` (direct import of `get_monthly_income`/`get_monthly_expense`), `routes/cashbook.py` (nearly every function), `database/payment_queries.py` (`insert_income_entry`, added 2026-07-22 — see below), `routes/dashboard.py` (`get_pending_fees`, `get_total_fee_revenue`, `get_today_fee_collection`, added 2026-07-21), `routes/membership_distribution.py` (`get_pending_fees`, `get_total_fee_revenue`, added 2026-07-21).
- **Future modification notes:** `insert_income_entry` takes a caller-supplied `conn` deliberately (so it composes atomically with the membership/payment insert that triggered it) — don't change it to open its own connection, that would break the all-or-nothing transaction guarantee described in ADR and [10_FEATURE_MODULES.md](10_FEATURE_MODULES.md). As of 2026-07-22, `routes/membership.py`/`routes/payment.py` no longer call this directly — they go through `database/payment_queries.py`'s `record_payment()`, which is the only caller that passes `payment_id` (see ADR-12 in [DECISIONS.md](DECISIONS.md)); `routes/cashbook.py`'s manual entries still call this without a `payment_id` (correctly — a manual entry has no originating payment). `update_manual_transaction` intentionally scopes its `WHERE` clause to `source = 'Cashbook Manual Entry'` — preserve that guard (ADR-4). `get_total_fee_revenue(admin_id)`/`get_today_fee_collection(admin_id)` (SUM of `payments.amount_paid`, all-time and today respectively) are the single source of truth for "money collected from students" — Dashboard's "Total Revenue"/"Today's Collection", Membership Distribution's "Revenue Collected", and the BI health score's collection component all call these instead of re-deriving them; both are deliberately **narrower** than `get_total_income()`/`get_today_income()` (which also include non-fee Cashbook categories like Donation/Library Fine/Book Sale) — don't merge the two families (ADR-11). `get_cashbook_ledger`'s `source = "Automatic"` filter uses `OR c.source IS NULL` to include pre-`migrate_cashbook_ledger.py` legacy rows — SQL's `NULL != 'x'` is `NULL`, not true, so without that clause those rows silently vanish from both the "Automatic" and "Manual" filters (fixed 2026-07-21).

### `database/membership_settings_queries.py`
- **Purpose:** Get/upsert per-admin membership plan pricing and policy configuration.
- **Responsibilities:** One row per `admin_id`.
- **Functions/Classes:** `get_membership_settings(admin_id)`, `save_membership_settings(admin_id, data)` (upsert via `INSERT ... ON CONFLICT(admin_id) DO UPDATE`). As of 2026-07-21, the INSERT/UPDATE column list no longer includes `reminder_days`/`send_reminders` — those fields are intentionally omitted so saving Membership Settings leaves any existing values on those (now-unused) columns untouched instead of overwriting them with stale form data (reminder ownership moved to Notification Settings, see ADR-8 in [DECISIONS.md](DECISIONS.md)).
- **Depends on:** `database.db.get_connection`.
- **Depended on by:** `routes/setting.py`.
- **Fixed 2026-07-22 (QA & Validation Sprint):** `save_membership_settings()`'s `INSERT` declared 14 columns (`admin_id` + 13 data fields) but its `VALUES(...)` clause had only 13 `?` placeholders — every single save of Settings → Membership Settings raised `sqlite3.OperationalError: 13 values for 14 columns` and was silently swallowed by nothing (no try/except existed around the call in `routes/setting.py`), surfacing as an unhandled 500. This was not an edge case — it reproduced on every valid save, with any values. See [CHANGELOG.md](CHANGELOG.md).
- **Future modification notes:** As of 2026-07-21, `get_membership_settings(admin_id)` **is** consumed by `routes/membership.py`'s `create()`/`renew()` (via `database/membership_queries.py`'s `get_plan_pricing`/`get_admission_fee` — TD-7 partially resolved, see [CHANGELOG.md](CHANGELOG.md)) for plan duration/fee/admission-fee. `late_fee_per_day`, `renewal_grace_days`, `auto_expiry` and `allow_early_renewal` remain unconsumed — there is no late-fee line item, grace-window enforcement, auto-expiry job, or early-renewal block anywhere in the app yet (see TD-7's updated note in [11_FUTURE_WORK.md](11_FUTURE_WORK.md)). Don't re-add `reminder_days`/`send_reminders` to the INSERT/UPDATE column list (see TD-23) — that concept now lives exclusively in `database/notification_settings_queries.py`.

### `database/membership_queries.py`
- **Purpose:** Shared, admin-isolated data access for the Membership workflow (Create/Renew/status/counts) — added 2026-07-21 to stop the "is this membership still active" logic drifting across files (TD-6).
- **Responsibilities:** The single definition of "effective status" (raw `membership_status` combined with `end_date` vs. today) in both SQL (`EFFECTIVE_STATUS_SQL`) and Python (`get_effective_status`) form; the single definition of "days until expiry" (`DAYS_LEFT_SQL`); the guard that stops a student ending up with two simultaneously-`Active` membership rows (`get_active_membership`); the shared active/expired count query used by both Dashboard and Membership Distribution (`get_membership_counts`); and the Membership Settings → plan pricing bridge used by Create/Renew (`get_plan_pricing`, `get_admission_fee`).
- **Functions/Classes:** `EFFECTIVE_STATUS_SQL` (module constant, a `CASE` SQL fragment expecting a `memberships m` alias in scope), `DAYS_LEFT_SQL` (module constant), `get_effective_status(membership_status, end_date)`, `get_active_membership(student_id)`, `get_membership_counts(admin_id)`, `PLAN_SETTING_PREFIX`/`DEFAULT_PLAN_DAYS`/`DEFAULT_PLAN_FEES`/`DEFAULT_ADMISSION_FEE` (module constants), `get_plan_pricing(settings)`, `get_admission_fee(settings)`.
- **Depends on:** `database.db.get_connection`.
- **Depended on by:** `routes/membership.py` (`index()`, `create()`, `renew()`), `routes/dashboard.py` (`get_membership_counts`, `DAYS_LEFT_SQL`), `routes/membership_distribution.py` (`get_membership_counts`, `get_effective_status`, `DAYS_LEFT_SQL`), `routes/student.py` (`EFFECTIVE_STATUS_SQL`), `routes/notification.py` (`DAYS_LEFT_SQL`).
- **Future modification notes:** `EFFECTIVE_STATUS_SQL` must be interpolated (f-string), never passed as a bind parameter — it's a raw SQL fragment, not a value. When selecting it alongside `m.*` under the alias `membership_status`, list it **before** `m.*` in the `SELECT` — `sqlite3.Row` resolves a duplicate column name to whichever occurrence came first in the `SELECT` list (verified empirically), so the wrong order silently makes the raw, possibly-stale column win instead of the computed one. If `late_fee_per_day`/`renewal_grace_days`/`auto_expiry`/`allow_early_renewal` are ever wired in, this is the natural home for that logic too, alongside `get_plan_pricing`.

### `database/payment_queries.py`
- **Purpose:** Single source of truth for recording a payment — added 2026-07-22 (Payment Workflow Audit) to stop `routes/membership.py` (`create`/`renew`) and `routes/payment.py` (`collect`) each inlining their own `INSERT INTO payments` and their own receipt-number formula, which had already drifted into two incompatible formats and never read the receipt numbering configured in Settings → Receipt Settings (TD-22).
- **Responsibilities:** Allocate a globally unique, sequential receipt number for an admin from `library_settings.receipt_prefix`/`next_receipt_number`, advancing that counter in the same transaction as the payment (`generate_receipt_number`); insert the `payments` row and its matching automatic Cashbook Income entry — with the new `payment_id` link — as one unit (`record_payment`).
- **Functions/Classes:** `generate_receipt_number(conn, admin_id)`, `_receipt_number_taken(cursor, receipt_number)` (added 2026-07-22), `record_payment(conn, admin_id, membership_id, student_id, student_name, payment_mode, amount, remarks, category, description, source)`.
- **Depends on:** `database.cashbook_queries.insert_income_entry`.
- **Depended on by:** `routes/payment.py` (`collect()`), `routes/membership.py` (`create()`, `renew()`).
- **Fixed 2026-07-22 (QA & Validation Sprint):** `payments.receipt_number` is `UNIQUE` **globally** (across every admin), but both branches of `generate_receipt_number()` computed `number`/`sequence` from only *this* admin's own counter or payment count — every admin defaults to prefix `"LIB"` until they customize it, so any two admins reaching the same sequence position (trivially, both admins' very first receipt) generated the identical string and the second one's `INSERT` raised an unhandled `sqlite3.IntegrityError`, silently discarded by `routes/membership.py`/`routes/payment.py`'s `except sqlite3.Error` as "Could not create this membership due to a database error." Reproduced directly against the live DB with two freshly-registered admins. Fix: both branches now call `_receipt_number_taken()` and skip forward past any number already claimed by *any* admin before returning it — verified with a two-admin regression test (`tests/test_09_full_workflow_chain.py::test_receipt_numbers_globally_unique_across_two_fresh_admins`). See [CHANGELOG.md](CHANGELOG.md).
- **Future modification notes:** `generate_receipt_number` always advances `next_receipt_number`, regardless of `library_settings.auto_increment_receipt` — there is no manual-receipt-number entry field anywhere in the UI, so turning that toggle off with the old "don't advance" semantics would make every payment after the first for that admin fail on the `payments.receipt_number UNIQUE` constraint. The toggle is still saved/displayed by Receipt Settings but doesn't change this function's behavior (see ADR-12 in [DECISIONS.md](DECISIONS.md)) — if a manual-entry UI is ever built, that's when the toggle should start being honored here. The no-settings-row fallback (count of existing `LIB-%` receipts + 1001) only runs for an admin who hasn't created a Library Profile yet; once they do, every subsequent payment uses the persisted counter. `record_payment()` does not call `conn.commit()`/`conn.close()` — callers own the transaction (matches `insert_income_entry`'s existing contract) and are expected to wrap the call in `try/except sqlite3.Error` + `conn.rollback()` so a failed payment (e.g. an unlikely receipt-number collision) never leaves a partial `payments`/`cashbook` write — see `routes/payment.py`/`routes/membership.py`.

### `database/notification_settings_queries.py`
- **Purpose:** Reusable, admin-isolated data access for Settings → Notification Settings.
- **Responsibilities:** Reads and writes the same `library_settings` row as `settings_queries.py`/`receipt_settings_queries.py` — there is no separate notification-settings table. Update-only (no insert path): the row must already exist from Library Profile. Single owner of reminder/channel/quiet-hours/dashboard-display behavior — see ADR-8 in [DECISIONS.md](DECISIONS.md).
- **Functions/Classes:** `get_notification_settings(admin_id)` (`SELECT * FROM library_settings`, returns `None` if no row exists), `get_notification_settings_cached(admin_id)` (added 2026-07-21 — identical result, memoized on `flask.g` for the lifetime of one request), `save_notification_settings(admin_id, data)` (plain `UPDATE` of the 19 reminder/channel/quiet-hours/dashboard columns, not upsert).
- **Depends on:** `database.db.get_connection`, `flask.g`.
- **Depended on by:** `routes/setting.py` (`notification_settings()`, and also called from `membership_settings()` to feed the read-only reminder summary — uses the raw `get_notification_settings()`, fine since it's the only settings-related query on that request), `routes/dashboard.py` (`dashboard()`, for `dash_show_pending_fees` — uses `get_notification_settings_cached()`), `app.py` (`inject_notification_summary()`, for `nav_notification_prefs` — uses `get_notification_settings_cached()`).
- **Future modification notes:** Deliberately has no insert/upsert path, matching `receipt_settings_queries.py`'s pattern — the route enforces that a `library_settings` row already exists first. `get_notification_settings_cached()` exists because `app.py`'s global context processor runs on every authenticated page, and `routes/dashboard.py` independently needed the same row on `/dashboard` — before 2026-07-21 that was 2 identical `SELECT`s per dashboard load (confirmed via query-count instrumentation, see [CHANGELOG.md](CHANGELOG.md)). Any new call site that needs this admin's settings within a request should use the `_cached` variant, not the raw one — the raw one is still correct to call from a context with no other caller on the same request (e.g. `routes/setting.py`).

### `database/backup_queries.py`
- **Purpose:** Admin-isolated data access for Settings → Data & Backup.
- **Responsibilities:** One row per `admin_id` in `backup_log`, tracking the most recent manual backup taken. Kept separate from `library_settings` so a backup can be recorded before a Library Profile row exists (see ADR-9 in [DECISIONS.md](DECISIONS.md)).
- **Functions/Classes:** `get_backup_info(admin_id)` (`SELECT * FROM backup_log`, returns `None` if no backup has ever been taken), `record_backup(admin_id, backup_filename)` (upsert via `INSERT ... ON CONFLICT(admin_id) DO UPDATE`, stamps `last_backup_at = CURRENT_TIMESTAMP`).
- **Depends on:** `database.db.get_connection`.
- **Depended on by:** `routes/setting.py` (`data_backup()`, `backup_create()`).
- **Future modification notes:** No automatic/scheduled backup job exists yet (PF-5) — `record_backup()` is only ever called from the manual `backup_create()` route handler. If a scheduled backup job is added later, this is the function it should call to keep `backup_log` consistent with manual backups.

### `database/security_settings_queries.py`
- **Purpose:** Admin-isolated data access for Settings → Security Settings.
- **Responsibilities:** One row per `admin_id` in `security_settings`. Kept separate from `library_settings` for the same reason as `backup_queries.py` (see ADR-9).
- **Functions/Classes:** `get_security_settings(admin_id)` (`SELECT * FROM security_settings`; returns the module-level `DEFAULTS` dict, not `None`, when no row exists yet), `save_security_settings(admin_id, data)` (upsert via `INSERT ... ON CONFLICT(admin_id) DO UPDATE`). Module constant `DEFAULTS`.
- **Depends on:** `database.db.get_connection`.
- **Depended on by:** `routes/setting.py` (`security_settings()`).
- **Future modification notes:** Password change itself is handled inline in `routes/setting.py`'s `security_settings()` against the `admins` table, not through this module — this module only covers `session_timeout_minutes`/`remember_me_enabled`/`login_notifications_enabled`, none of which are currently enforced anywhere (TD-26). Returning `DEFAULTS` instead of `None` means callers don't need a "does a row exist" branch the way `get_notification_settings`/`get_receipt_settings` callers do — keep that contract if you add more security preferences.

### `database/settings_queries.py`
- **Purpose:** Admin-isolated CRUD for the Library Profile settings page.
- **Responsibilities:** One `library_settings` row per admin, including logo/stamp/signature path bookkeeping.
- **Functions/Classes:** `get_library_settings(admin_id)`, `create_library_settings(admin_id, data)`, `update_library_settings(admin_id, data)`, `save_library_settings(admin_id, data)` (upsert wrapper), `clear_library_logo(admin_id)`.
- **Depends on:** `database.db.get_connection`.
- **Depended on by:** `routes/setting.py`.
- **Future modification notes:** File-path resolution (keep old / new upload / clear) is the *caller's* (`routes/setting.py`) responsibility, not this module's — keep that separation if you add new uploadable fields (e.g. a future receipt-footer image).

### `database/receipt_settings_queries.py`
- **Purpose:** Admin-isolated read/update access for the Receipt Settings page.
- **Responsibilities:** Reads and writes the same `library_settings` row as `settings_queries.py` — there is no separate receipt-settings table. Update-only (no insert path): the row must already exist from Library Profile.
- **Functions/Classes:** `get_receipt_settings(admin_id)` (`SELECT * FROM library_settings`, same query shape as `get_library_settings`), `save_receipt_settings(admin_id, data)` (plain `UPDATE`, not upsert).
- **Depends on:** `database.db.get_connection`.
- **Depended on by:** `routes/setting.py`.
- **Future modification notes:** Deliberately has no insert/upsert path (ADR — see [DECISIONS.md](DECISIONS.md)); the route enforces that a `library_settings` row already exists before this module is ever called. If receipt settings ever need to exist independently of a library profile, this module (and the route's guard) is what to change.

---

## `routes/`

### `routes/auth.py`
- **Purpose:** Login, registration, logout, password reset.
- **Responsibilities:** The only entry points that don't require an existing session; sets `session["admin_id"]`/`session["username"]` on success.
- **Functions/Classes:** `login()`, `logout()`, `register()`, `forgot_password()`, `validate_password(password)`.
- **Depends on:** `database.supabase_client.get_supabase_client` (as of 2026-07-23 — was `database.db.get_connection`, see ADR-16) for all three routes; `database.db.get_connection` still, for `register()` only (mirror-insert bridge, see below); `postgrest.exceptions.APIError`, `sqlite3.Error`; `werkzeug.security` (`generate_password_hash`, `check_password_hash`).
- **Depended on by:** `app.py` (registers `auth_bp`); referenced at runtime via `url_for('auth.logout')` from `templates/layouts/navbar.html`; `routes/setting.py` imports `validate_password` from here for its Security Settings password-change form (that form now also writes `admins.password` via Supabase, same as this module — as of 2026-07-23, ADR-17, closing TD-35).
- **Future modification notes:** `register()` hardcodes `role="Admin"` while the schema default is lowercase `'admin'` (Known Technical Debt item TD-13) — fix the casing before anything starts branching on `role`. As of 2026-07-23 (ADR-16), `admins` reads/writes for login/register/forgot-password primarily go through Supabase (`database.supabase_client.get_supabase_client()`), using `.eq()` filters (never raw string interpolation, so still immune to actual SQL injection) instead of parameterized `sqlite3` queries. Every Supabase call that carries user-controlled input is wrapped in `try/except APIError`, degrading to the same user-facing outcome as "no match found" (login/forgot-password) or a generic "Something went wrong" flash (register) — added because PostgREST encodes `.eq()`/`.select()` filter values into the request's GET query string, and Supabase's Cloudflare-fronted edge network was observed (live, via the test suite's SQL-injection-payload tests) to return an HTTP 403 WAF block for adversarial-looking query strings (e.g. containing `DROP TABLE`) before the request ever reaches Postgres — a new failure mode SQLite never had, since `sqlite3`'s bound parameters never touch a URL. Without the `try/except`, that 403 would surface as an unhandled `postgrest.exceptions.APIError` (500), a regression from SQLite's graceful "Invalid username" handling for the same adversarial input. **`register()` is the one exception that still touches SQLite directly:** after the Supabase insert succeeds, it mirrors the same row — same `admin_id` (taken from the Supabase insert's returned row), `full_name`, `username`, `mobile`, `email`, hashed `password`, `role` — into SQLite's `admins` table via `get_connection()`, rolling back the Supabase insert (`.delete().eq("admin_id", ...)`) if the SQLite insert raises `sqlite3.Error`. This exists solely because 7 other tables still enforce real SQLite foreign keys back to `admins.admin_id` (`database/db.py` sets `PRAGMA foreign_keys = ON` on every connection, verified directly against `database/schema.sql`): `enquiries` (`routes/enquiries.py`), `students` (`routes/student.py`), `audit_log` (written transitively from `routes/cashbook.py`, `routes/membership.py`, *and* `routes/payment.py` — all three eventually call `database/audit_queries.py`'s `log_entry()`), and `library_settings`/`membership_settings`/`backup_log`/`security_settings` (all four owned by `routes/setting.py`) — without the mirror, a brand-new admin would get `sqlite3.IntegrityError: FOREIGN KEY constraint failed` the instant they touched any of those features (this was caught live by running the full test suite, not by auth's own tests alone — see the 2026-07-23 changelog entry). `cashbook`/`expenses` also have an `admin_id` column but no FK (added via `ALTER TABLE`, which SQLite can't constrain), so they're not part of this dependency. Delete this mirror-insert once all 7 of those tables are migrated to Supabase too (migrating `routes/setting.py` alone only closes 4 of the 7) — don't keep it as permanent behavior. **Update (2026-07-23, ADR-17):** `routes/setting.py`'s `security_settings()` now updates `admins.password` via Supabase too (`database.supabase_client.get_supabase_client()`), the same copy `forgot_password()` writes — the password-value half of the split described above is closed (TD-35 `Resolved`). This mirror-insert bridge itself is unaffected: it exists for `admin_id` row *existence*, not `password`. **Update (2026-07-23, ADR-18):** `routes/enquiries.py`'s `enquiries` table also migrated to Supabase, but this did not shrink the 7-table list above — `enquiries` needed its own `add()`/`edit()`/`delete()` SQLite mirror (not a one-shot bridge like this one), because `routes/student.py`'s `admission()` still reads the enquiry row and inserts against a real SQLite FK. All 7 tables still require `register()`'s mirror-insert; only once `students` (the natural next slice) and the remaining 5 are migrated too can it be deleted.

### `routes/dashboard.py`
- **Purpose:** Main authenticated landing page — KPIs, charts, recent activity.
- **Responsibilities:** Aggregate counts/totals across students/memberships/payments/enquiries; trigger chart (re)generation; fetch this admin's notification settings to decide whether to show the "Pending Fees" stat card.
- **Functions/Classes:** `dashboard()` — now also calls `get_notification_settings_cached(admin_id)` and passes `dash_show_pending_fees` (bool, defaults `True` if no `library_settings` row exists yet) into the template context.
- **Depends on:** `database.db.get_connection`, `utils.charts` (`generate_revenue_chart`, `generate_membership_chart`), `database.cashbook_categories` (constants for the quick-add modal), `database.notification_settings_queries.get_notification_settings_cached`, `database.cashbook_queries` (`get_pending_fees`, `get_total_fee_revenue`, `get_today_fee_collection`, added 2026-07-21), `database.membership_queries` (`get_membership_counts`, `DAYS_LEFT_SQL`, added 2026-07-21).
- **Depended on by:** `app.py` (registers `dashboard_bp`); linked from `layouts/sidebar.html` and various "back to dashboard" redirects (e.g. `routes/cashbook.py`'s optional `redirect_to`).
- **Future modification notes:** Regenerates both chart PNGs on every single page load (not cached) — if dashboard load time ever becomes a concern, this is the place to add a cache/staleness check. `dash_show_pending_fees` is the only Notification Settings dashboard toggle currently wired to a real widget — `dash_show_new_admissions` has no matching card yet (TD-25 in [11_FUTURE_WORK.md](11_FUTURE_WORK.md)); if you build one, follow this same pattern. "Total Revenue", "Pending Fees" and "Today's Collection" all call `cashbook_queries` (`get_total_fee_revenue`/`get_pending_fees`/`get_today_fee_collection`) instead of duplicating that SQL inline (fixed 2026-07-21, see [CHANGELOG.md](CHANGELOG.md)) — don't reintroduce a local copy of any of the three. Active/Expired Memberships now calls `database.membership_queries.get_membership_counts()` (fixed 2026-07-21 — TD-6) instead of running its own `COUNT(DISTINCT CASE ...)` query; `routes/membership_distribution.py` calls the exact same function, so don't reintroduce a local copy here either. Upcoming Expiries' "days left" column now uses the shared `DAYS_LEFT_SQL` constant instead of an inline `julianday()` expression.

### `routes/enquiries.py`
- **Purpose:** Enquiry CRUD — the entry point of the sales funnel before admission.
- **Functions/Classes:** `index()`, `add()`, `edit(enquiry_id)`, `delete(enquiry_id)`, `view(enquiry_id)`, plus `_sanitize_date(value)` (as of 2026-07-23, ADR-18).
- **Depends on:** `database.supabase_client.get_supabase_client` (as of 2026-07-23, ADR-18 — `enquiries` table reads/writes, source of truth for `index()`/`edit()`/`view()`); `postgrest.exceptions.APIError`; `database.db.get_connection` (still used for the SQLite mirror writes in `add()`/`edit()`/`delete()`, and for `index()`'s/`view()`'s `students` lookup — `students` itself is unmigrated); `sqlite3.Error` (mirror-write error handling); `datetime.date` (`_sanitize_date`'s ISO-format check).
- **Depended on by:** `app.py` (registers `enquiry_bp`); `routes/student.py`'s `admission()` redirects to `enquiry.index` when an enquiry isn't found, and reads the enquiry row it needs directly from the SQLite mirror this file maintains (see below) rather than importing from here.
- **Future modification notes:** `delete()` runs on a plain `GET` with no confirmation (Known Technical Debt item TD-14) — convert to POST + confirmation before this route is ever exposed beyond trusted admins. **As of 2026-07-23 (ADR-18):** Supabase is the source of truth for every read; SQLite is kept as a write-synced mirror purely because `routes/student.py`'s `admission()` (out of this migration's scope) still reads the enquiry row and writes `students` against a real SQLite FK to `enquiry_id`. `add()` computes `enquiry_id` itself — `SELECT MAX(enquiry_id) FROM enquiries` (SQLite) `+ 1` — rather than letting Supabase's identity column auto-assign it, then inserts that explicit id into Supabase and mirrors the identical row into SQLite, rolling back the Supabase insert if the SQLite mirror-insert raises `sqlite3.Error` (same rollback shape as `routes/auth.py`'s `register()`, see ADR-16). The explicit-id computation isn't optional: Supabase's `enquiries` identity sequence was seeded once by the one-time data copy (ADR-15) and had fallen far behind SQLite's `AUTOINCREMENT` counter (verified live at 599 vs. 1012) from prior sessions' SQLite-only usage — trusting Supabase's auto-assigned id caused every `add()` to collide with an id SQLite had already used, caught by running the full test suite (45 cascading failures) before this fix, see ADR-18. `edit()` updates both — the SQLite mirror update is not best-effort, because `admission()` reads `full_name`/`mobile`/`purpose`/`preferred_shift` from SQLite and must not see stale pre-edit values. `delete()` deletes from Supabase first (authoritative — the user-visible action) then best-effort deletes the SQLite mirror, swallowing `sqlite3.Error` so a lingering FK from an already-admitted student's `students.enquiry_id` can't undo the visible delete. `index()` no longer does the old `LEFT JOIN students` in SQL — it fetches Supabase's enquiries, separately queries SQLite for this admin's `enquiry_id → student_id` map, and merges them in Python before rendering, since `students` isn't on Supabase yet. `_sanitize_date()` converts blank/unparsable `followup_date` input to `None` before any Supabase call, since Postgres's `DATE` column (unlike SQLite's dynamic typing) would otherwise raise `postgrest.exceptions.APIError` on invalid input. **Known gap (TD-36):** `admission()`'s `UPDATE enquiries SET status='Admitted' ...` is SQLite-only and outside this migration's scope — Supabase's `status` column goes stale after an admission, so the Enquiries list/detail pages keep showing the pre-admission status and "Admission" action until `routes/student.py` is migrated too.

### `routes/student.py`
- **Purpose:** Student records and the enquiry→student "admission" conversion.
- **Functions/Classes:** `index()`, `admission(enquiry_id)`, `view(student_id)`, `edit(student_id)`.
- **Depends on:** `database.db.get_connection`, `database.membership_queries.EFFECTIVE_STATUS_SQL` (added 2026-07-21), `sqlite3` (added 2026-07-22, for the `IntegrityError` catch below).
- **Depended on by:** `app.py` (registers `student_bp`); `routes/membership.py` and `routes/payment.py` redirect to `student.view` after success; `routes/enquiries.py`/`routes/membership.py` link to `student.index`.
- **Fixed 2026-07-22 (QA & Validation Sprint):** `edit()`'s `UPDATE students SET mobile=...` had no `try/except` around it — editing a student's mobile number to a value already used by another student of the same admin violates `students`' `UNIQUE(mobile, admin_id)` constraint and raised an unhandled `sqlite3.IntegrityError` (500). Worse: because the crash happened before `conn.close()`, the open connection could linger and produce `sqlite3.OperationalError: database is locked` on *subsequent, unrelated* requests until it was garbage-collected — reproduced live via the Flask test client (two students, editing the second one's mobile to collide with the first triggered the crash, then the very next request failed with "database is locked"). Fix: wrapped the `UPDATE` in `try/except sqlite3.IntegrityError`, rolling back and closing the connection before re-rendering the edit form with a friendly flash, matching the pattern already used in `routes/membership.py`/`routes/payment.py`. See [CHANGELOG.md](CHANGELOG.md).
- **Future modification notes:** `admission()` forcibly redirects into `membership.create` — if you ever want admission without an immediate membership, this is the coupling to loosen. `index()`'s membership-status column now uses the shared `EFFECTIVE_STATUS_SQL` constant (fixed 2026-07-21 — TD-6) instead of its own inline `CASE` — keep using the shared constant rather than re-inlining the condition if this query changes. **As of 2026-07-23 (ADR-18), this file was deliberately left unmigrated** (out of scope for that session's Enquiries slice): `admission()`'s `SELECT * FROM enquiries` and `UPDATE enquiries SET status='Admitted' ...` now read/write a SQLite row that `routes/enquiries.py` maintains only as a write-synced mirror of the Supabase original — `admission()` itself is unaware anything changed. Its `status='Admitted'` write does not propagate to Supabase, which is what `routes/enquiries.py` actually reads for the Enquiries list/detail pages — a real, documented gap (TD-36) that can only be closed by migrating this file's `students`/`enquiries` reads to Supabase too, the recommended next slice per ADR-18.

### `routes/membership.py`
- **Purpose:** Membership creation and renewal — the core money-generating flow.
- **Functions/Classes:** `index()`, `create(student_id)`, `renew(student_id)`.
- **Depends on:** `database.db.get_connection`, `database.payment_queries.record_payment` (added 2026-07-22, replaces a direct `insert_income_entry` call — see below), `database.membership_settings_queries.get_membership_settings`, `database.membership_queries` (`EFFECTIVE_STATUS_SQL`, `get_active_membership`, `get_plan_pricing`, `get_admission_fee`, added 2026-07-21).
- **Depended on by:** `app.py` (registers `membership_bp`); `routes/student.py`'s `admission()` redirects here; `routes/membership_distribution.py` links here when no prior membership exists to renew.
- **Future modification notes:** As of 2026-07-22 (Payment Workflow Audit, TD-22 resolved — see [CHANGELOG.md](CHANGELOG.md)): `create()` and `renew()` no longer inline their own `INSERT INTO payments` + ad-hoc `REC-YYYYMMDD-<id>` receipt-number formula — both call `database.payment_queries.record_payment()`, the same helper `routes/payment.py`'s `collect()` uses, so all three payment-creating flows share one receipt-numbering/Cashbook-linking implementation instead of three. Both routes now also reject a negative `paid_amount`/`due_amount` (previously only `paid_amount + due_amount <= 0` was checked, so e.g. `paid=-500, due=1000` passed the total-fee check and silently stored a negative `paid_amount` with no payment record to back it) and wrap the membership-insert + payment-record sequence in `try/except sqlite3.Error: conn.rollback()` so a failure can't leave a membership row with no matching payment, or vice versa. As of 2026-07-21 (TD-7 partially resolved): `index()` lists effective status (not the raw, possibly-stale column) so the Memberships table matches Dashboard/Student/Distribution instead of showing a membership as "Active" after its `end_date` has passed; `create()` now refuses to insert a second membership while an effectively-active one already exists (redirects to `renew` instead — see `get_active_membership`); both `create()` and `renew()` fetch this admin's `membership_settings` and pass `plan_pricing`/`admission_fee` into the template so the plan dropdown's duration/fee auto-fill reflects the admin's configured pricing instead of a hardcoded 30/90/180/365 + manual fee entry. The admin can still hand-edit the auto-filled `paid_amount`/`due_amount`/`duration` fields (e.g. for a discount or a custom plan) — this is auto-fill, not a server-enforced total. `late_fee_per_day`/`renewal_grace_days`/`auto_expiry`/`allow_early_renewal` are still not consumed anywhere (no late-fee line item, no grace-window enforcement, no auto-expiry job, no early-renewal block) — see TD-7's updated note.

### `routes/membership_analytics.py`
- **Purpose:** URL-compatibility shim — permanently redirects to Membership Distribution.
- **Functions/Classes:** `index()` — `redirect(url_for("membership_distribution.index"))`.
- **Depends on:** nothing beyond Flask itself.
- **Depended on by:** `app.py` (registers `membership_analytics_bp`).
- **Fixed 2026-07-22 (QA & Validation Sprint):** previously `render_template("membership/analytics.html")` — that path doesn't exist (`templates/membership/` was never a real directory; the real one is `templates/memberships/`, plural), so every visit to `/membership-analytics/` crashed with `jinja2.exceptions.TemplateNotFound`, confirmed live via the Flask test client. The template the path was presumably meant to reach, `templates/memberships/analytics.html`, turned out to be a pre-existing 0-byte empty file (see PF-2), so correcting only the path would have produced a 200 OK response with a completely blank, chrome-less page (no layout/nav/sidebar — a dead end). Since Membership Distribution already fully implements the same data, this now redirects there instead, the same pattern `routes/report.py` already uses for its own superseded route (PF-3) — no new ADR added, following that same precedent. `templates/memberships/analytics.html` is now unreferenced by any route — see TD-11.
- **Future modification notes:** If Membership Analytics is ever meant to be a distinct page from Membership Distribution again, build it out properly rather than restoring the old broken render call.

### `routes/membership_distribution.py`
- **Purpose:** Plan-distribution analytics (the real analytics page).
- **Functions/Classes:** `index()`.
- **Depends on:** `database.db.get_connection`, `utils.charts.generate_membership_distribution_donut`, `database.cashbook_queries` (`get_pending_fees`, `get_total_fee_revenue`, added 2026-07-21), `database.membership_queries` (`get_membership_counts`, `get_effective_status`, `DAYS_LEFT_SQL`, added 2026-07-21).
- **Depended on by:** `app.py` (registers `membership_distribution_bp`); linked from `components/membership_chart.html` on the Dashboard.
- **Future modification notes:** "Quick insights" are computed in Python from an already-fetched row list, not extra queries — keep that pattern if you add more insights rather than issuing new SQL per insight. The exception is "Revenue Collected"/"Pending Payments": those now call `get_total_fee_revenue`/`get_pending_fees` (fixed 2026-07-21) instead of Python-summing `paid_amount`/`pending_amount` off the fetched rows, so this page's numbers can never drift from Dashboard's/Cashbook's identically-named cards — don't revert to a local `sum()`. Active/Expired counts and the per-row status label now come from `database.membership_queries` (`get_membership_counts`/`get_effective_status`, fixed 2026-07-21 — TD-6) instead of two standalone `COUNT` queries plus an inline `is_active` boolean — `routes/dashboard.py` shares the same count function, so don't reintroduce a local copy.

### `routes/payment.py`
- **Purpose:** Standalone fee collection against an existing membership's pending balance.
- **Functions/Classes:** `index()`, `collect(membership_id)`.
- **Depends on:** `database.db.get_connection`, `database.payment_queries.record_payment` (added 2026-07-22, replaces a direct `insert_income_entry` call plus an inline receipt-number formula — see below).
- **Depended on by:** `app.py` (registers `payment_bp`); linked from student/membership views wherever a "Collect Payment" action appears.
- **Future modification notes:** As of 2026-07-22 (Payment Workflow Audit, TD-22 resolved): the old `REC-YYYYMMDD-<membership_id>-<new_paid>` inline formula is gone — `collect()` now calls `database.payment_queries.record_payment()`, the same shared helper `routes/membership.py`'s `create()`/`renew()` use, so receipt numbers are globally sequential per admin and actually reflect the `receipt_prefix`/`next_receipt_number` configured in Settings → Receipt Settings instead of ignoring it. `collect()` also now: refuses to collect against a membership with `pending_amount <= 0` (previously reachable by URL even with nothing owed, surfacing a confusing "cannot exceed pending balance of ₹0" error instead of redirecting straight back); wraps the membership-update + payment-record sequence in `try/except sqlite3.Error: conn.rollback()` so a DB failure can't leave the membership's `paid_amount`/`pending_amount` updated without a matching `payments` row; and echoes the generated receipt number in the success flash message.

### `routes/cashbook.py`
- **Purpose:** The manual ledger UI — add/edit entries, filter/search/paginate, view audit log.
- **Functions/Classes:** `index()`, `add_transaction()`, `edit_transaction(entry_id)`, plus module-level chart-building helpers `_month_label`, `_build_income_expense_chart`, `_build_category_chart`, `_build_payment_method_chart`.
- **Depends on:** `database.cashbook_queries` (most of its functions), `database.audit_queries.get_recent_audit_log`, `database.cashbook_categories` (constants).
- **Depended on by:** `app.py` (registers `cashbook_bp`); `routes/dashboard.py`'s quick-add modal can redirect back here (`redirect_to` form field).
- **Future modification notes:** `edit_transaction()`'s `source != "Cashbook Manual Entry"` guard is load-bearing (ADR-4) — don't remove it without an explicit decision to allow editing auto-generated entries, which would require reconciling the originating membership/payment record too.

### `routes/business_intelligence.py`
- **Purpose:** The BI dashboard — health score, growth, top categories, action items, timeline.
- **Functions/Classes:** `index()`, plus module-level helpers `_month_label`, `_build_revenue_trend_chart`, `_build_membership_growth_chart`.
- **Depends on:** `database.cashbook_queries` (`get_monthly_income`, `get_monthly_expense`), `database.bi_queries` (most of its functions).
- **Depended on by:** `app.py` (registers `business_intelligence_bp`); `routes/report.py` redirects here unconditionally.
- **Future modification notes:** This route has no POST handlers — it's pure read/aggregate. If interactivity (e.g. drill-down) is added, keep the heavy aggregation in `database/bi_queries.py`, not inline here. `_build_revenue_trend_chart` now derives a third "Profit" dataset (`income - expense` per month) locally, same pattern as `routes/cashbook.py`'s `_build_income_expense_chart` — the Revenue Trend chart previously plotted only Revenue/Expenses with no profit line at all (fixed 2026-07-21).

### `routes/notification.py`
- **Purpose:** Membership-expiry notifications, both as a full page and as the navbar bell's data source.
- **Functions/Classes:** `index(filter_type=None)`, `get_notification_summary(admin_id)`.
- **Depends on:** `database.db.get_connection`, `database.membership_queries.DAYS_LEFT_SQL` (added 2026-07-21).
- **Depended on by:** `app.py` (imports `get_notification_summary` directly for its global `inject_notification_summary` context processor — this makes `notification.py` one of the few modules effectively invoked on *every* authenticated page render, not just its own route); `templates/components/notification_dropdown.html` consumes the resulting `nav_notifications` context variable.
- **Future modification notes:** Because `get_notification_summary` runs on every page load via the context processor, keep it cheap — it's not just this page's concern anymore. Its bucket window (today/tomorrow/3-days/expired) is still hardcoded and does **not** read `library_settings`' `reminder_7_days`/`reminder_3_days`/`reminder_1_day`/`notify_on_expiry_day`/`notify_after_expiry` toggles configured on Settings → Notification Settings — those toggles are persisted and displayed but never change which memberships get bucketed here (see the new TD row in [11_FUTURE_WORK.md](11_FUTURE_WORK.md)). `days_left` now comes from the shared `DAYS_LEFT_SQL` constant instead of an inline `julianday()` expression.

### `routes/setting.py`
- **Purpose:** All Settings sub-pages: Library Profile, Membership Settings, Receipt Settings, Notification Settings, Staff & User Access, Data & Backup, Security Settings — the Settings module is now fully built out (no stubs remaining).
- **Functions/Classes:** `index()`, `membership_settings()`, `library_profile()`, `remove_library_logo()`, `receipt_settings()`, `notification_settings()` (full GET/POST handler), `staff_access()` (placeholder page, no form), `data_backup()`, `backup_export_csv()`, `backup_create()`, `security_settings()` (password-change + session-preferences forms), plus helpers `_format_membership_setting`, `_build_membership_changes`, `_format_receipt_setting`, `_build_receipt_changes`, `_format_notification_setting`, `_build_notification_changes`, `_format_file_size`, `_allowed_file`, `_save_upload`. Module constants `NOTIFICATION_SETTING_FIELDS`/`NOTIFICATION_SETTING_DEFAULTS`, `SESSION_TIMEOUT_OPTIONS`.
- **Depends on:** `database.settings_queries`, `database.membership_settings_queries`, `database.receipt_settings_queries`, `database.notification_settings_queries`, `database.backup_queries`, `database.security_settings_queries`, `database.db` (`get_connection`, `DATABASE_PATH` — still used by `backup_export_csv()`/`backup_create()`/`data_backup()`), `database.supabase_client.get_supabase_client` (as of 2026-07-23, ADR-17 — `security_settings()`'s password branch only), `postgrest.exceptions.APIError`, `routes.auth.validate_password`, `werkzeug.security` (`check_password_hash`, `generate_password_hash`), `werkzeug.utils.secure_filename`, `csv`, `io`, `shutil`.
- **Depended on by:** `app.py` (registers `setting_bp`); linked from `layouts/navbar.html` (gear icon).
- **Future modification notes:** `membership_settings()`'s one-shot "what changed" diff (`session["membership_change_summary"]`) is a pattern now reused by `receipt_settings()` (`session["receipt_change_summary"]`) and `notification_settings()` (`session["notification_change_summary"]`) — follow the same `_build_*_changes`/`_format_*_setting` pair if another settings page needs it. `receipt_settings()`/`notification_settings()` both redirect to `library_profile` when no `library_settings` row exists yet, since neither supports insert, only `UPDATE`. `membership_settings()` no longer builds/validates `reminder_days`/`send_reminders` from the form — it fetches `get_notification_settings(admin_id)` and passes it through for the template's read-only summary instead (see ADR-8 in [DECISIONS.md](DECISIONS.md)). `notification_settings()` stores reminder/channel/quiet-hours/dashboard-display config only — nothing dispatches SMS/Email/WhatsApp or enforces quiet hours yet (TD-24 in [11_FUTURE_WORK.md](11_FUTURE_WORK.md)). `backup_create()` copies `DATABASE_PATH` into the project-root `backups/` folder (creating it if needed), records the copy via `record_backup()`, then serves it as a download — there is no scheduled/automatic backup (PF-5). `security_settings()`'s password-change branch (`form_type == "password"`) verifies the current password with `check_password_hash`, validates the new one with `routes.auth.validate_password`, and is the one part of Security Settings that's actually enforced — as of 2026-07-23 (ADR-17) it reads/writes `admins.password` via Supabase (`database.supabase_client.get_supabase_client()`, `.eq("admin_id", admin_id)`-filtered `.select()`/`.update()` calls each wrapped in `try/except APIError`), the same table and client `routes/auth.py`'s login/register/forgot-password use (ADR-16) — this closed TD-35's password split-brain, now `Resolved`. Every other Settings sub-page (`library_profile`/`membership_settings`/`receipt_settings`/`notification_settings`/`backup_log`/`security_settings`'s own session-preference columns) is still SQLite-only, deliberately out of this slice's scope (see ADR-17); `session_timeout_minutes`/`remember_me_enabled`/`login_notifications_enabled` are saved via `save_security_settings()` (SQLite) but not read/enforced anywhere else yet (TD-26). `staff_access()` takes no form input — it's a static placeholder (PF-4).

### `routes/report.py`
- **Purpose:** Deprecated URL-compatibility shim.
- **Functions/Classes:** `index()` — unconditional redirect to `business_intelligence.index`.
- **Depends on:** nothing beyond Flask itself.
- **Depended on by:** `app.py` (registers `report_bp`).
- **Future modification notes:** `templates/reports/index.html` still exists on disk but is dead — delete it when you're confident nothing else references it, or repurpose this route if "Reports" needs to become a distinct feature from Business Intelligence again.

---

## `templates/`

### `templates/layouts/`
- **Purpose:** The two page shells every other template builds on.
- **Files:** `base.html` (authenticated shell — navbar + sidebar + content block), `auth_base.html` (minimal shell for login/register/forgot-password), `navbar.html`, `sidebar.html` (plain includes, not extended).
- **Depends on:** `static/css/style.css` / `static/css/login.css`, Google Fonts (Poppins, CDN), Bootstrap 5.3.7 + Icons (CDN), `templates/components/notification_dropdown.html` (included by `navbar.html`).
- **Depended on by:** every feature template extends `base.html` or `auth_base.html`.
- **Future modification notes:** `sidebar.html` references `enquiries_new_count`/`students_new_today_count`/`memberships_expiring_soon_count`/`payments_pending_count` that nothing currently supplies (Known Technical Debt item TD-15) — either wire these into the `inject_notification_summary`-style context processor in `app.py`, or remove the badge markup.

### `templates/components/`
- **Purpose:** ~45 shared partials — generic card primitives plus feature-specific widgets grouped by prefix (`bi_*`, `cashbook_*`, `membership_*`).
- **Depends on:** the page-specific stylesheet of whatever page includes them, and (for chart components) either a static PNG path (`static/charts/*.png`) or a `window.*ChartData` JS global populated by the rendering route.
- **Depended on by:** `templates/dashboard/index.html`, `templates/cashbook/index.html`, `templates/business_intelligence/index.html`, `templates/memberships/distribution.html` — see [09_DEPENDENCY_MAP.md](09_DEPENDENCY_MAP.md) for the full include graph.
- **Future modification notes:** `alert.html` is a 0-byte empty file (Known Technical Debt item TD-12) — check whether anything still `{% include %}`s it before deleting. `activity_card.html` uses `{% block %}` (extend-only) while most others use `{% call %}`/`with`-include — keep new components consistent with whichever pattern the page around them already uses. `notification_dropdown.html` now also reads `nav_notification_prefs` (from `app.py`'s context processor): it hides the badge-count pill when `dash_show_badge_count` is off, and skips rendering the `today`/`tomorrow`/`expired` categories in its loop when their matching toggle is off (`three_days` has no corresponding Notification Settings toggle and is always shown).

### `templates/auth/`
- **Purpose:** `login.html`, `register.html`, `forgot_password.html`.
- **Depends on:** `layouts/auth_base.html`, `static/css/login.css`, `static/js/login.js`.
- **Depended on by:** `routes/auth.py`.
- **Future modification notes:** No shared component partials here — these are self-contained, unlike most other feature folders.

### `templates/dashboard/`
- **Purpose:** `index.html` — the main KPI landing page.
- **Depends on:** `layouts/base.html`; `components/{dashboard_header, quick_actions, revenue_chart, membership_chart, expiry_table, recent_admissions, add_transaction_modal, edit_transaction_modal}.html`; `static/js/dashboard-charts.js`, `static/js/transaction_modal.js`.
- **Depended on by:** `routes/dashboard.py`.
- **Future modification notes:** Any new dashboard tile should follow the existing `stat_card.html`/`chart_card.html` include pattern rather than hand-rolling new markup. The "Pending Fees" stat card is now wrapped in `{% if dash_show_pending_fees %}`, driven by `routes/dashboard.py`'s Notification Settings lookup — follow the same pattern if `dash_show_new_admissions` (currently unwired, TD-25) ever gets a real widget. Gained a `get_flashed_messages()` block (fixed 2026-07-22, QA & Validation Sprint — TD-31 now fully resolved across the whole app) — previously any `flash()` reachable from a redirect back to `/dashboard` (e.g. `routes/cashbook.py`'s `add_transaction()` with `redirect_to=dashboard`) was silently discarded.

### `templates/enquiries/`
- **Purpose:** `index.html`, `add.html`, `edit.html`, `view.html`.
- **Depends on:** `layouts/base.html`.
- **Depended on by:** `routes/enquiries.py`.
- **Future modification notes:** `add.html`, `edit.html`, and `view.html` all gained a `get_flashed_messages()` block (fixed 2026-07-22, QA & Validation Sprint — TD-31 now fully resolved) — none rendered flashes before, so every `flash()` call from `routes/enquiries.py` (add success, edit success/not-found, delete success) that lands on these pages was silently discarded; confirmed live via the Flask test client before this fix. `index.html` already had one.

### `templates/students/`
- **Purpose:** `index.html`, `admission.html`, `view.html`, `edit.html`.
- **Depends on:** `layouts/base.html`.
- **Depended on by:** `routes/student.py`.
- **Future modification notes:** `view.html`'s "Collect Payment" button is now wrapped in `{% if membership and membership.pending_amount and membership.pending_amount > 0 %}` (fixed 2026-07-22, Payment Workflow Audit) — previously it showed for any membership regardless of balance, so a fully-paid student's page linked into `payment.collect` only to hit a "cannot exceed pending balance of ₹0" validation error. Its "Print Receipt" button is still a dead `href="#"` link — out of scope for that audit (would be a new feature, not a fix). `index.html` and `view.html` both gained a `get_flashed_messages()` block (fixed 2026-07-22 — TD-31 partial). `admission.html` and `edit.html` also gained the same block (fixed 2026-07-22, QA & Validation Sprint — TD-31 now fully resolved across the whole app) — previously the crash fix in `edit()`'s duplicate-mobile handling (see this file's `routes/student.py` card) would have re-rendered `edit.html` with a flashed error message that the page couldn't display at all.

### `templates/memberships/`
- **Purpose:** `index.html`, `create.html`, `renew.html`, `distribution.html`, `analytics.html` (**0-byte, unreferenced by any route as of 2026-07-22** — `routes/membership_analytics.py` now redirects instead of rendering it; see PF-2 and this file's `routes/membership_analytics.py` card).
- **Depends on:** `layouts/base.html`; `components/membership_*.html` (distribution page only); `static/css/membership_distribution.css`, `static/js/membership_distribution.js` (distribution page only).
- **Depended on by:** `routes/membership.py` (`index`, `create`, `renew`), `routes/membership_distribution.py` (`distribution`). `routes/membership_analytics.py` no longer depends on `analytics.html` (fixed 2026-07-22 — was previously requesting the wrong path, `membership/analytics.html`, which doesn't exist; see [CHANGELOG.md](CHANGELOG.md)).
- **Future modification notes:** `index.html`, `create.html`, and `renew.html` gained a `get_flashed_messages()` block on 2026-07-22 (Payment Workflow Audit — TD-31 partial); `distribution.html` gained the same block on 2026-07-22 (QA & Validation Sprint — TD-31 now fully resolved across the whole app) — previously it silently discarded any `flash()` reachable from `routes/membership_distribution.py`. `analytics.html` is dead code (0 bytes, no route renders it) — safe to delete, or repurpose if Membership Analytics is ever rebuilt as a distinct page.

### `templates/payments/`
- **Purpose:** `index.html`, `collect.html` (rendered), plus `create.html`, `success.html` (**not currently rendered by any route** — Known Technical Debt item TD-11).
- **Depends on:** `layouts/base.html`.
- **Depended on by:** `routes/payment.py` (only `index`/`collect`).
- **Future modification notes:** Either wire up `create.html`/`success.html` or remove them — check with `grep render_template routes/payment.py` before assuming either is safe. `index.html` and `collect.html` both gained a `get_flashed_messages()` block (fixed 2026-07-22 — TD-31) — neither rendered flashes before, so `collect()`'s validation errors (invalid amount, amount exceeds pending, DB error) and its success message (now including the receipt number, see ADR-13) were being set correctly and then silently discarded; confirmed live via the Flask test client before this fix.

### `templates/cashbook/`
- **Purpose:** `index.html` (rendered), plus `transactions.html`, `analytics.html` (**not currently rendered** — Known Technical Debt item TD-11).
- **Depends on:** `layouts/base.html`; `components/cashbook_{summary_cards, filters, charts, transactions, activity_log}.html`; `static/css/cashbook.css`, `static/js/cashbook.js`, `static/js/transaction_modal.js`.
- **Depended on by:** `routes/cashbook.py` (only `index`).
- **Future modification notes:** `index.html` gained a `get_flashed_messages()` block (fixed 2026-07-22, QA & Validation Sprint — TD-31) — previously discarded every `flash()` from `add_transaction()`/`edit_transaction()` (invalid category/amount/payment-method errors, "cannot be edited" for automatic entries, success confirmations), confirmed live via the Flask test client before this fix.

### `templates/business_intelligence/`
- **Purpose:** `index.html`.
- **Depends on:** `layouts/base.html`; `components/bi_*.html` (9 files); `static/css/business_intelligence.css`, `static/js/business_intelligence.js`.
- **Depended on by:** `routes/business_intelligence.py`.
- **Future modification notes:** Gained a `get_flashed_messages()` block (fixed 2026-07-22, QA & Validation Sprint — TD-31 now fully resolved across the whole app). This page has no route-level `flash()` calls of its own today, but the block is there for consistency and for any future one.

### `templates/notification/`
- **Purpose:** `index.html`.
- **Depends on:** `layouts/base.html`.
- **Depended on by:** `routes/notification.py`.
- **Future modification notes:** Gained a `get_flashed_messages()` block (fixed 2026-07-22, QA & Validation Sprint — TD-31 now fully resolved across the whole app).

### `templates/settings/`
- **Purpose:** `index.html` (7 action cards, up from 4), `library_profile.html`, `membership_settings.html`, `receipt_settings.html`, `notification_settings.html` (new), `staff_access.html` (new), `data_backup.html` (new), `security_settings.html` (new). Every Settings sub-page now has a real template — no stubs remain.
- **Depends on:** `layouts/base.html`; `static/css/settings.css`, `static/js/settings.js` (`library_profile.html`, `receipt_settings.html`, `notification_settings.html` — quiet-hours toggle script — and `security_settings.html` — password-match script).
- **Depended on by:** `routes/setting.py`.
- **Future modification notes:** `membership_settings.html`'s reminder-day/send-reminder inputs were replaced with a read-only "Reminders & Notifications" card fed by `notification_settings` (passed in from `routes/setting.py`'s `membership_settings()`) that links out to Notification Settings — don't reintroduce editable reminder inputs here (see ADR-8 in [DECISIONS.md](DECISIONS.md)). `notification_settings.html` reuses the same "Configuration Changes" diff-table component as `membership_settings.html`/`receipt_settings.html`. `staff_access.html` and the "Future Security Features" card in `security_settings.html` are intentionally static placeholders — no form inputs, nothing to wire up until multi-user auth / 2FA / device management actually exist. `staff_access.html` gained a `get_flashed_messages()` block (fixed 2026-07-22, QA & Validation Sprint — TD-31 now fully resolved across the whole app); the other Settings sub-pages already had one.

### `templates/reports/`
- **Purpose:** `index.html` — **dead**, never rendered (`routes/report.py` always redirects instead).
- **Depends on:** `layouts/base.html` (presumably, unread in practice).
- **Depended on by:** nothing.
- **Future modification notes:** Safe to delete once confirmed no other branch/plan intends to un-deprecate `routes/report.py`.

---

## `utils/`

### `utils/charts.py`
- **Purpose:** Server-side matplotlib chart generation for the Dashboard and Membership Distribution pages.
- **Responsibilities:** Query the DB itself (not passed data), render a PNG, save it to a fixed path under `static/charts/`.
- **Functions/Classes:** `_smooth_curve(x, y, samples_per_segment=30)`, `_format_currency_short(value, _pos=None)`, `generate_revenue_chart(admin_id)`, `generate_membership_chart(admin_id)`, `generate_membership_distribution_donut(admin_id)`.
- **Depends on:** `database.db.get_connection`, `matplotlib` (+ `matplotlib.pyplot`, `matplotlib.colors`, `matplotlib.ticker`), `numpy`.
- **Depended on by:** `routes/dashboard.py` (`generate_revenue_chart`, `generate_membership_chart`), `routes/membership_distribution.py` (`generate_membership_distribution_donut`).
- **Future modification notes:** `requirements.txt` already lists both `matplotlib>=3.7.0` and `numpy>=1.26.0` (verified 2026-07-22, QA & Validation Sprint — TD-8 flipped to Resolved; this doc previously claimed they were missing). The shared, non-admin-scoped output filenames are a cross-tenant leak (TD-1) — if you touch this file for any other reason, consider fixing the filename scoping (`{chart}_{admin_id}.png`) at the same time. `generate_revenue_chart` groups `payments.payment_date` by `strftime('%m', ...)` (month-of-year only) to build the Jan–Dec bars — it now also filters `WHERE strftime('%Y', payment_date) = strftime('%Y', 'now')` (fixed 2026-07-21); without it, payments from different calendar years silently summed into the same month bar (e.g. July 2025 + July 2026 both landing in "Jul"). The header's "This Month / This Year / Last Year" `<select>` is still cosmetic only (not wired to any handler) — the chart is effectively always "This Year" now, matching that default option. `generate_membership_chart` (the Dashboard's compact pie) now has the same zero-memberships empty state as `generate_membership_distribution_donut` — before 2026-07-21 it produced a genuinely blank white PNG (`ax.pie([])` on an empty `sizes` list draws nothing, and nothing checked for that case) instead of a "No membership data yet" message. Both empty-state branches (this function's and `generate_membership_distribution_donut`'s) now call `ax.set_xlim(-1, 1)`/`ax.set_ylim(-1, 1)` before placing the `(0, 0)`-anchored text — without explicit symmetric limits, `bbox_inches="tight"` crops to matplotlib's default `(0, 1)` axes extent and the text lands pinned in the bottom-left corner instead of centered (also fixed 2026-07-21 — verify centering visually if you touch either empty-state branch again).
