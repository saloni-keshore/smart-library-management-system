# File Reference

Per-file cards for every important source file: **Purpose**, **Responsibilities**, **Functions/Classes**, **Files it depends on**, **Files that depend on it**, **Future modification notes**.

"Depends on" / "depended on by" are drawn from a grep of every `import`/`from` statement in the project (verified 2026-07-20, see [DIAGRAMS.md](DIAGRAMS.md) for the same data as a graph) — cross-blueprint `url_for` couplings (runtime-only, not imports) are noted separately where relevant. If you add or remove an import, update the two matching cards (both sides of the edge) in the same change.

---

## Root

### `app.py`
- **Purpose:** Flask application factory and process entry point.
- **Responsibilities:** Create the Flask app, set `SECRET_KEY`, register all 13 blueprints, define the one global context processor that feeds the navbar notification bell on every page.
- **Functions/Classes:** `create_app()`; module-level `app = create_app()`; no classes. Inline `inject_notification_summary()` registered via `@app.context_processor`.
- **Depends on:** `routes.auth`, `routes.dashboard`, `routes.enquiries`, `routes.student`, `routes.membership`, `routes.payment`, `routes.cashbook`, `routes.report`, `routes.setting`, `routes.notification` (also imports `get_notification_summary`), `routes.membership_analytics`, `routes.membership_distribution`, `routes.business_intelligence`.
- **Depended on by:** nothing imports `app.py` — it's the process entry point (`python app.py`).
- **Future modification notes:** This is the right place to add a centralized auth-check decorator/`before_request` hook (currently duplicated in nearly every route — see [Known Technical Debt](11_FUTURE_WORK.md)), to wire in `config.py` (currently unused), to add 404/500 error handlers, and to make `debug=True` conditional on an environment variable before any real deployment.

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
- **Depended on by:** `database/audit_queries.py`, `database/bi_queries.py`, `database/cashbook_queries.py`, `database/membership_settings_queries.py`, `database/settings_queries.py`, `utils/charts.py`, `routes/auth.py`, `routes/dashboard.py`, `routes/enquiries.py`, `routes/membership.py`, `routes/membership_distribution.py`, `routes/notification.py`, `routes/payment.py`, `routes/student.py`. Also imported by every `migrate_*.py` script and `database/migrate.py`, but via the bare `from db import get_connection` form rather than `from database.db import get_connection` — an inconsistent import style that only works because those scripts are always run standalone (Known Technical Debt item TD-21).
- **Future modification notes:** `PRAGMA foreign_keys = ON` is **not** set here — it only runs once at schema-init time inside `schema.sql`. If you need FK enforcement at runtime, add `connection.execute("PRAGMA foreign_keys = ON")` here (test this doesn't break any existing insert order first). No connection pooling exists; every request opens/closes its own connection — fine at current scale, worth revisiting under real concurrent load.

### `database/schema.sql`
- **Purpose:** Full DDL — source of truth for creating every table from scratch.
- **Responsibilities:** Define `admins`, `settings` (legacy/unused), `enquiries`, `students`, `memberships`, `payments`, `cashbook` (+ inline `ALTER TABLE` extensions), `expenses` (unused), `transactions` (⚠ conflicting second definition also exists in `migrate_transactions.py`), `audit_log`, `library_settings`, `membership_settings`. Sets `PRAGMA foreign_keys = ON;` at the top.
- **Functions/Classes:** N/A (pure SQL).
- **Depends on:** nothing (plain SQL file).
- **Depended on by:** `database/seed.py` (executed via `executescript()`).
- **Future modification notes:** Full column-level detail in [04_DATABASE_SCHEMA.md](04_DATABASE_SCHEMA.md). When adding a table here, also add a corresponding `migrate_*.py` script for existing installs that already ran an older version of this file — `schema.sql` alone won't retrofit an existing `library.db`.

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
- **Depends on:** `database.db.get_connection`, `database.cashbook_queries` (`get_monthly_income`, `get_monthly_expense`, `get_income_category_totals`, `get_expense_category_totals`, `get_pending_fees`, `get_total_income`).
- **Depended on by:** `routes/business_intelligence.py`.
- **Future modification notes:** `get_business_health_score`'s weighting (30% growth / 30% expense discipline / 20% fee collection / 20% renewal rate) is a business decision, not a technical one — if it changes, document the new weights and rationale in [DECISIONS.md](DECISIONS.md), not just here.

### `database/cashbook_categories.py`
- **Purpose:** Single source of truth for category/payment-method constant lists.
- **Responsibilities:** None beyond holding data — no DB access, no functions.
- **Functions/Classes:** none — module-level lists `AUTO_CATEGORIES`, `MANUAL_INCOME_CATEGORIES`, `MANUAL_EXPENSE_CATEGORIES`, `ALL_CATEGORIES`, `PAYMENT_METHODS`.
- **Depends on:** nothing.
- **Depended on by:** `routes/cashbook.py`, `routes/dashboard.py`.
- **Future modification notes:** If you add a new manual category here, it immediately becomes selectable in both the Cashbook and Dashboard quick-add forms — no other code change needed. Keep `AUTO_CATEGORIES` (Admission Fee, Membership Fee, Membership Renewal) in sync with the literal strings passed to `insert_income_entry()` in `routes/membership.py`/`routes/payment.py`.

### `database/cashbook_queries.py`
- **Purpose:** Core admin-isolated data-access layer for the financial ledger. The largest and most-depended-on query module.
- **Responsibilities:** Manual + automatic transaction inserts/updates, all aggregate reads (totals, monthly series, category breakdowns, payment-method distribution, cash balance, pagination/filtering for the ledger view).
- **Functions/Classes:** `_generate_reference_id(cursor, prefix)`, `get_recent_transactions(admin_id, limit=10)`, `insert_transaction(admin_id, transaction_type, category, person, description, amount, payment_method, entry_date)`, `insert_income_entry(conn, admin_id, category, person, description, amount, payment_method, entry_date, source, reference_prefix="PAY")`, `get_transaction_by_id(admin_id, entry_id)`, `update_manual_transaction(admin_id, entry_id, category, person, description, amount, payment_method, entry_date)`, `_get_total_by_type`, `get_total_income`, `get_total_expense`, `_get_today_total_by_type`, `get_today_income`, `get_today_expense`, `get_pending_fees(admin_id)`, `_monthly_totals_by_type`, `get_monthly_income`, `get_monthly_expense`, `get_monthly_profit`, `_category_totals_by_type`, `get_income_category_totals`, `get_expense_category_totals`, `get_payment_method_distribution(admin_id)`, `get_cash_balance(admin_id)`, `get_todays_transaction_count(admin_id)`, `get_cashbook_ledger(admin_id, search=None, date_from=None, date_to=None, transaction_type=None, category=None, payment_method=None, source=None, page=1, per_page=10)`.
- **Depends on:** `database.db.get_connection`, `database.audit_queries.log_entry`.
- **Depended on by:** `database/bi_queries.py`, `routes/business_intelligence.py` (direct import of `get_monthly_income`/`get_monthly_expense`), `routes/cashbook.py` (nearly every function), `routes/membership.py` (`insert_income_entry`), `routes/payment.py` (`insert_income_entry`).
- **Future modification notes:** `insert_income_entry` takes a caller-supplied `conn` deliberately (so it composes atomically with the membership/payment insert that triggered it) — don't change it to open its own connection, that would break the all-or-nothing transaction guarantee described in ADR and [10_FEATURE_MODULES.md](10_FEATURE_MODULES.md). `update_manual_transaction` intentionally scopes its `WHERE` clause to `source = 'Cashbook Manual Entry'` — preserve that guard (ADR-4).

### `database/membership_settings_queries.py`
- **Purpose:** Get/upsert per-admin membership plan pricing and policy configuration.
- **Responsibilities:** One row per `admin_id`.
- **Functions/Classes:** `get_membership_settings(admin_id)`, `save_membership_settings(admin_id, data)` (upsert via `INSERT ... ON CONFLICT(admin_id) DO UPDATE`).
- **Depends on:** `database.db.get_connection`.
- **Depended on by:** `routes/setting.py`.
- **Future modification notes:** This is configured but **not yet consumed** by `routes/membership.py`'s create/renew flow (Known Technical Debt item TD-7) — if you wire that up, this is the function pair you'll call from `membership.py` instead of hardcoding fee defaults there.

### `database/settings_queries.py`
- **Purpose:** Admin-isolated CRUD for the Library Profile settings page.
- **Responsibilities:** One `library_settings` row per admin, including logo/stamp/signature path bookkeeping.
- **Functions/Classes:** `get_library_settings(admin_id)`, `create_library_settings(admin_id, data)`, `update_library_settings(admin_id, data)`, `save_library_settings(admin_id, data)` (upsert wrapper), `clear_library_logo(admin_id)`.
- **Depends on:** `database.db.get_connection`.
- **Depended on by:** `routes/setting.py`.
- **Future modification notes:** File-path resolution (keep old / new upload / clear) is the *caller's* (`routes/setting.py`) responsibility, not this module's — keep that separation if you add new uploadable fields (e.g. a future receipt-footer image).

---

## `routes/`

### `routes/auth.py`
- **Purpose:** Login, registration, logout, password reset.
- **Responsibilities:** The only entry points that don't require an existing session; sets `session["admin_id"]`/`session["username"]` on success.
- **Functions/Classes:** `login()`, `logout()`, `register()`, `forgot_password()`, `validate_password(password)`.
- **Depends on:** `database.db.get_connection`, `werkzeug.security` (`generate_password_hash`, `check_password_hash`).
- **Depended on by:** `app.py` (registers `auth_bp`); referenced at runtime via `url_for('auth.logout')` from `templates/layouts/navbar.html`.
- **Future modification notes:** `register()` hardcodes `role="Admin"` while the schema default is lowercase `'admin'` (Known Technical Debt item TD-13) — fix the casing before anything starts branching on `role`.

### `routes/dashboard.py`
- **Purpose:** Main authenticated landing page — KPIs, charts, recent activity.
- **Responsibilities:** Aggregate counts/totals across students/memberships/payments/enquiries; trigger chart (re)generation.
- **Functions/Classes:** `dashboard()`.
- **Depends on:** `database.db.get_connection`, `utils.charts` (`generate_revenue_chart`, `generate_membership_chart`), `database.cashbook_categories` (constants for the quick-add modal).
- **Depended on by:** `app.py` (registers `dashboard_bp`); linked from `layouts/sidebar.html` and various "back to dashboard" redirects (e.g. `routes/cashbook.py`'s optional `redirect_to`).
- **Future modification notes:** Regenerates both chart PNGs on every single page load (not cached) — if dashboard load time ever becomes a concern, this is the place to add a cache/staleness check.

### `routes/enquiries.py`
- **Purpose:** Enquiry CRUD — the entry point of the sales funnel before admission.
- **Functions/Classes:** `index()`, `add()`, `edit(enquiry_id)`, `delete(enquiry_id)`, `view(enquiry_id)`.
- **Depends on:** `database.db.get_connection`.
- **Depended on by:** `app.py` (registers `enquiry_bp`); `routes/student.py`'s `admission()` redirects to `enquiry.index` when an enquiry isn't found.
- **Future modification notes:** `delete()` runs on a plain `GET` with no confirmation (Known Technical Debt item TD-14) — convert to POST + confirmation before this route is ever exposed beyond trusted admins.

### `routes/student.py`
- **Purpose:** Student records and the enquiry→student "admission" conversion.
- **Functions/Classes:** `index()`, `admission(enquiry_id)`, `view(student_id)`, `edit(student_id)`.
- **Depends on:** `database.db.get_connection`.
- **Depended on by:** `app.py` (registers `student_bp`); `routes/membership.py` and `routes/payment.py` redirect to `student.view` after success; `routes/enquiries.py`/`routes/membership.py` link to `student.index`.
- **Future modification notes:** `admission()` forcibly redirects into `membership.create` — if you ever want admission without an immediate membership, this is the coupling to loosen.

### `routes/membership.py`
- **Purpose:** Membership creation and renewal — the core money-generating flow.
- **Functions/Classes:** `index()`, `create(student_id)`, `renew(student_id)`.
- **Depends on:** `database.db.get_connection`, `database.cashbook_queries.insert_income_entry`.
- **Depended on by:** `app.py` (registers `membership_bp`); `routes/student.py`'s `admission()` redirects here; `routes/membership_distribution.py` links here when no prior membership exists to renew.
- **Future modification notes:** `create()` and `renew()` duplicate most of their validation/receipt-generation logic — a good extraction candidate if a third membership-creating flow is ever added. See Known Technical Debt item TD-7 for wiring in `membership_settings`.

### `routes/membership_analytics.py`
- **Purpose:** Placeholder analytics page.
- **Functions/Classes:** `index()` — renders a template with **no query, no context**.
- **Depends on:** nothing beyond Flask itself.
- **Depended on by:** `app.py` (registers `membership_analytics_bp`).
- **Future modification notes:** Either build this out (likely superseded already by `routes/membership_distribution.py`, which *does* have real data) or remove the route/template/nav link to avoid a dead-looking page in production.

### `routes/membership_distribution.py`
- **Purpose:** Plan-distribution analytics (the real analytics page).
- **Functions/Classes:** `index()`.
- **Depends on:** `database.db.get_connection`, `utils.charts.generate_membership_distribution_donut`.
- **Depended on by:** `app.py` (registers `membership_distribution_bp`); linked from `components/membership_chart.html` on the Dashboard.
- **Future modification notes:** "Quick insights" are computed in Python from an already-fetched row list, not extra queries — keep that pattern if you add more insights rather than issuing new SQL per insight.

### `routes/payment.py`
- **Purpose:** Standalone fee collection against an existing membership's pending balance.
- **Functions/Classes:** `index()`, `collect(membership_id)`.
- **Depends on:** `database.db.get_connection`, `database.cashbook_queries.insert_income_entry`.
- **Depended on by:** `app.py` (registers `payment_bp`); linked from student/membership views wherever a "Collect Payment" action appears.
- **Future modification notes:** Receipt-number format (`REC-YYYYMMDD-<membership_id>-<new_paid>`) is duplicated (with a slightly different suffix) in `routes/membership.py` — if a dedicated receipts module is ever built (see [WHERE_TO_MODIFY.md](WHERE_TO_MODIFY.md)), centralize this here first.

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
- **Future modification notes:** This route has no POST handlers — it's pure read/aggregate. If interactivity (e.g. drill-down) is added, keep the heavy aggregation in `database/bi_queries.py`, not inline here.

### `routes/notification.py`
- **Purpose:** Membership-expiry notifications, both as a full page and as the navbar bell's data source.
- **Functions/Classes:** `index(filter_type=None)`, `get_notification_summary(admin_id)`.
- **Depends on:** `database.db.get_connection`.
- **Depended on by:** `app.py` (imports `get_notification_summary` directly for its global `inject_notification_summary` context processor — this makes `notification.py` one of the few modules effectively invoked on *every* authenticated page render, not just its own route); `templates/components/notification_dropdown.html` consumes the resulting `nav_notifications` context variable.
- **Future modification notes:** Because `get_notification_summary` runs on every page load via the context processor, keep it cheap — it's not just this page's concern anymore.

### `routes/setting.py`
- **Purpose:** All Settings sub-pages: Library Profile, Membership Settings, and the Receipt/Notification stubs.
- **Functions/Classes:** `index()`, `membership_settings()`, `library_profile()`, `remove_library_logo()`, `receipt_settings()` (stub), `notification_settings()` (stub), plus helpers `_format_membership_setting`, `_build_membership_changes`, `_allowed_file`, `_save_upload`.
- **Depends on:** `database.settings_queries`, `database.membership_settings_queries`, `werkzeug.utils.secure_filename`.
- **Depended on by:** `app.py` (registers `setting_bp`); linked from `layouts/navbar.html` (gear icon).
- **Future modification notes:** `membership_settings()`'s one-shot "what changed" diff (`session["membership_change_summary"]`) is a nice pattern worth reusing for `library_profile()` too if that page ever wants the same UX.

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
- **Future modification notes:** `alert.html` is a 0-byte empty file (Known Technical Debt item TD-12) — check whether anything still `{% include %}`s it before deleting. `activity_card.html` uses `{% block %}` (extend-only) while most others use `{% call %}`/`with`-include — keep new components consistent with whichever pattern the page around them already uses.

### `templates/auth/`
- **Purpose:** `login.html`, `register.html`, `forgot_password.html`.
- **Depends on:** `layouts/auth_base.html`, `static/css/login.css`, `static/js/login.js`.
- **Depended on by:** `routes/auth.py`.
- **Future modification notes:** No shared component partials here — these are self-contained, unlike most other feature folders.

### `templates/dashboard/`
- **Purpose:** `index.html` — the main KPI landing page.
- **Depends on:** `layouts/base.html`; `components/{dashboard_header, quick_actions, revenue_chart, membership_chart, expiry_table, recent_admissions, add_transaction_modal, edit_transaction_modal}.html`; `static/js/dashboard-charts.js`, `static/js/transaction_modal.js`.
- **Depended on by:** `routes/dashboard.py`.
- **Future modification notes:** Any new dashboard tile should follow the existing `stat_card.html`/`chart_card.html` include pattern rather than hand-rolling new markup.

### `templates/enquiries/`
- **Purpose:** `index.html`, `add.html`, `edit.html`, `view.html`.
- **Depends on:** `layouts/base.html`.
- **Depended on by:** `routes/enquiries.py`.

### `templates/students/`
- **Purpose:** `index.html`, `admission.html`, `view.html`, `edit.html`.
- **Depends on:** `layouts/base.html`.
- **Depended on by:** `routes/student.py`.

### `templates/memberships/`
- **Purpose:** `index.html`, `create.html`, `renew.html`, `distribution.html`, `analytics.html`.
- **Depends on:** `layouts/base.html`; `components/membership_*.html` (distribution page only); `static/css/membership_distribution.css`, `static/js/membership_distribution.js` (distribution page only).
- **Depended on by:** `routes/membership.py` (`index`, `create`, `renew`), `routes/membership_distribution.py` (`distribution`), `routes/membership_analytics.py` (`analytics`).
- **Future modification notes:** `analytics.html` is rendered with zero context (Known Technical Debt item TD-8) — don't assume it has real data if you're extending it.

### `templates/payments/`
- **Purpose:** `index.html`, `collect.html` (rendered), plus `create.html`, `success.html` (**not currently rendered by any route** — Known Technical Debt item TD-11).
- **Depends on:** `layouts/base.html`.
- **Depended on by:** `routes/payment.py` (only `index`/`collect`).
- **Future modification notes:** Either wire up `create.html`/`success.html` or remove them — check with `grep render_template routes/payment.py` before assuming either is safe.

### `templates/cashbook/`
- **Purpose:** `index.html` (rendered), plus `transactions.html`, `analytics.html` (**not currently rendered** — Known Technical Debt item TD-11).
- **Depends on:** `layouts/base.html`; `components/cashbook_{summary_cards, filters, charts, transactions, activity_log}.html`; `static/css/cashbook.css`, `static/js/cashbook.js`, `static/js/transaction_modal.js`.
- **Depended on by:** `routes/cashbook.py` (only `index`).

### `templates/business_intelligence/`
- **Purpose:** `index.html`.
- **Depends on:** `layouts/base.html`; `components/bi_*.html` (9 files); `static/css/business_intelligence.css`, `static/js/business_intelligence.js`.
- **Depended on by:** `routes/business_intelligence.py`.

### `templates/notification/`
- **Purpose:** `index.html`.
- **Depends on:** `layouts/base.html`.
- **Depended on by:** `routes/notification.py`.

### `templates/settings/`
- **Purpose:** `index.html`, `library_profile.html`, `membership_settings.html`. No templates yet for the `receipt_settings`/`notification_settings` stubs.
- **Depends on:** `layouts/base.html`; `static/css/settings.css`, `static/js/settings.js` (`library_profile.html` only).
- **Depended on by:** `routes/setting.py`.

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
- **Future modification notes:** `matplotlib`/`numpy` are missing from `requirements.txt` (Known Technical Debt item TD-8) — add them. The shared, non-admin-scoped output filenames are a cross-tenant leak (TD-1) — if you touch this file for any other reason, consider fixing the filename scoping (`{chart}_{admin_id}.png`) at the same time.
