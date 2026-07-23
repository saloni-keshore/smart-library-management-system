# Feature Modules — End-to-End Walkthroughs

Each section traces a feature from route → data access → template, so you can find every file involved without grepping.

## Auth
`routes/auth.py` (no query module; Supabase via `database/supabase_client.py`'s `get_supabase_client()`, `.eq()`-filtered on `admins` — as of 2026-07-23, was raw SQLite until ADR-16's cutover) → `templates/auth/{login,register,forgot_password}.html` (extend `layouts/auth_base.html`) → `static/css/login.css`, `static/js/login.js`. Session keys set on success: `admin_id`, `username`. `admins` writes from Settings → Security Settings' password-change form also go to Supabase as of 2026-07-23 (ADR-17), using the same client — see TD-35 (`Resolved`) in [11_FUTURE_WORK.md](11_FUTURE_WORK.md).

## Dashboard
`routes/dashboard.py` → raw SQL (students/memberships/payments/enquiries) + `utils/charts.py` (`generate_revenue_chart`, `generate_membership_chart`) + `database/cashbook_categories.py` (constants for the quick-add modal) → `templates/dashboard/index.html` → `components/{dashboard_header, quick_actions, revenue_chart, membership_chart, expiry_table, recent_admissions, add_transaction_modal, edit_transaction_modal}.html` → `static/js/dashboard-charts.js`, `static/js/transaction_modal.js`.

## Enquiries → Students (Admission) pipeline
`routes/enquiries.py` (CRUD on `enquiries`) → student is created from `routes/student.py`'s `admission(enquiry_id)`, which copies fields, marks the enquiry `Admitted`, and redirects into `routes/membership.py`'s `create(student_id)` to force a membership on the same flow. Templates: `templates/enquiries/*.html`, `templates/students/*.html`.

## Membership create/renew → Payment → Cashbook (the core money flow)
This is the most important cross-cutting flow in the app:

1. `routes/membership.py`'s `create()` or `renew()` inserts a `memberships` row and (if `paid_amount > 0`) a `payments` row, generating a `REC-YYYYMMDD-...` receipt number.
2. In the **same transaction**, it calls `database/cashbook_queries.py`'s `insert_income_entry(conn, admin_id, category, ...)` — this writes the `cashbook` row (category `"Admission Fee"` or `"Membership Renewal"`) and, inside `insert_income_entry` itself, calls `database/audit_queries.py`'s `log_entry(cursor, ...)` to write the audit trail. All three writes (membership/payment, cashbook, audit) commit or fail together.
3. `routes/payment.py`'s `collect()` (for later, standalone fee collection) follows the identical pattern: `payments` insert → `insert_income_entry` (category `"Membership Fee"`) → same audit trail.
4. From there, the ledger entry is visible in `routes/cashbook.py`'s `index()` (as a **non-editable** row, since its `source` isn't `"Cashbook Manual Entry"`) and feeds every aggregate in `database/bi_queries.py` (health score, growth, top revenue sources) via `database/cashbook_queries.py`.

Templates involved: `memberships/{create,renew}.html`, `payments/collect.html`, `cashbook/index.html` (read side).

## Membership Distribution (analytics, read-only)
`routes/membership_distribution.py` → raw SQL + `utils/charts.py`'s `generate_membership_distribution_donut` → `templates/memberships/distribution.html` → `components/membership_{summary_cards, distribution_chart, distribution_table, filters, quick_insights, progress}.html`.

## Membership Analytics (redirect shim)
`routes/membership_analytics.py` → permanently redirects to `membership_distribution.index` (fixed 2026-07-22 — previously requested a nonexistent template path, `membership/analytics.html`, crashing every visit; see [CHANGELOG.md](CHANGELOG.md) and [11_FUTURE_WORK.md](11_FUTURE_WORK.md) PF-2).

## Cashbook (manual ledger + audit)
`routes/cashbook.py` → `database/cashbook_queries.py` (nearly every function) + `database/audit_queries.py` (`get_recent_audit_log`) + `database/cashbook_categories.py` (allowed categories/methods) → `templates/cashbook/index.html` → `components/cashbook_{summary_cards, filters, charts, transactions, activity_log}.html` → `static/js/cashbook.js`, `static/js/transaction_modal.js`, `static/css/cashbook.css`.

## Business Intelligence (derived analytics on top of Cashbook)
`routes/business_intelligence.py` → `database/bi_queries.py` (health score, growth, top categories, action items, timeline) + `database/cashbook_queries.py` (monthly income/expense) → `templates/business_intelligence/index.html` → `components/bi_*.html` (9 files) → `static/js/business_intelligence.js`, `static/css/business_intelligence.css`.

## Notifications (expiry alerts)
`routes/notification.py`'s `get_notification_summary(admin_id)` is called two ways: (1) directly by `notification.index()` for the full notifications page, and (2) globally by `app.py`'s `inject_notification_summary` context processor on **every** authenticated page render, feeding the navbar bell (`components/notification_dropdown.html`). One function, two consumers.

## Settings
Settings is now fully built out — 7 sub-pages, no remaining stubs (as of the 2026-07-21 Notification Settings / Staff & User Access / Data & Backup / Security Settings pass):

- **Library Profile**: `routes/setting.py`'s `library_profile()` + `remove_library_logo()` → `database/settings_queries.py` → `templates/settings/library_profile.html` → `static/js/settings.js`, `static/css/settings.css`. Uploaded files land in `static/uploads/settings/`.
- **Membership Settings**: `routes/setting.py`'s `membership_settings()` → `database/membership_settings_queries.py` → `templates/settings/membership_settings.html`. Note: this configures plan pricing/policy but is **not yet read by** `routes/membership.py`'s create/renew flow (see [11_FUTURE_WORK.md](11_FUTURE_WORK.md)) — fees are still entered manually per membership. As of 2026-07-21, reminder-day/send-reminder inputs were removed from this page — it now renders a read-only summary sourced from `database/notification_settings_queries.get_notification_settings(admin_id)` and links out to Notification Settings (see ADR-8 in [DECISIONS.md](DECISIONS.md)).
- **Receipt Settings**: `routes/setting.py`'s `receipt_settings()` → `database/receipt_settings_queries.py` → `templates/settings/receipt_settings.html` → `static/js/settings.js` (live receipt-number/branding/paper-size preview), `static/css/settings.css`. Reuses the `library_settings` row/table (no separate table) and the logo/stamp/signature already uploaded via Library Profile — redirects there if no profile exists yet. Configuration only: nothing in the app yet reads `receipt_prefix`/`next_receipt_number`/`paper_size`/etc. to actually generate, print, or email a receipt (see [11_FUTURE_WORK.md](11_FUTURE_WORK.md)).
- **Notification Settings** *(completed 2026-07-21, was a "coming soon" stub — PF-1)*: `routes/setting.py`'s `notification_settings()` → `database/notification_settings_queries.py` → `templates/settings/notification_settings.html` → `static/js/settings.js` (quiet-hours enable/disable), `static/css/settings.css`. Same "reuse the `library_settings` row, redirect to Library Profile if it doesn't exist yet" pattern as Receipt Settings. Now the single owner of reminder-day/channel/quiet-hours/dashboard-display preferences (see ADR-8). `dash_show_pending_fees` is read by `routes/dashboard.py` to conditionally show the dashboard's "Pending Fees" card; `dash_show_badge_count`/`dash_show_expiry_today`/`dash_show_expiry_tomorrow`/`dash_show_overdue` are read by `app.py`'s `inject_notification_summary` context processor to control the navbar bell (`components/notification_dropdown.html`). Configuration only beyond those two wired paths: no SMS/Email/WhatsApp dispatch or quiet-hours enforcement exists yet, and `dash_show_new_admissions` has no widget to attach to (see [11_FUTURE_WORK.md](11_FUTURE_WORK.md) TD-24/TD-25).
- **Staff & User Access** *(new 2026-07-21)*: `routes/setting.py`'s `staff_access()` → `templates/settings/staff_access.html`. No query module — a static "Coming Soon" placeholder explaining the single-admin limitation and previewing 4 future roles (Owner, Front Desk, Accountant, Librarian). See PF-4 in [11_FUTURE_WORK.md](11_FUTURE_WORK.md).
- **Data & Backup** *(new 2026-07-21, Export Database action removed 2026-07-21)*: `routes/setting.py`'s `data_backup()`, `backup_export_csv()`, `backup_create()` → `database/backup_queries.py` → `templates/settings/data_backup.html`. `data_backup()` shows DB file size, last backup date, and backup location; `backup_export_csv()` is a read-only download (admin-scoped `students` CSV); `backup_create()` (labeled "Create Backup") copies the live DB into the project-root `backups/` folder (previously empty/untracked) and records it via `record_backup()`. Uses its own `backup_log` table, decoupled from `library_settings` so a backup can be taken before a Library Profile exists (ADR-9). No automatic/scheduled backup exists (PF-5).
- **Security Settings** *(new 2026-07-21)*: `routes/setting.py`'s `security_settings()` → `database/security_settings_queries.py` (session preferences, still SQLite) + `database/supabase_client.py`'s `get_supabase_client()` (password change, as of 2026-07-23 — ADR-17) → `templates/settings/security_settings.html` → `static/js/settings.js` (new/confirm password match check). Password change is fully functional and re-verified end-to-end as of 2026-07-23: wrong password rejected, correct change works, and logging in with the new password now succeeds — `routes/auth.py`'s login and this form both read/write the same Supabase `admins.password` (TD-35 in [11_FUTURE_WORK.md](11_FUTURE_WORK.md) now `Resolved`, ADR-17). Session timeout / remember-me / login-notification preferences are persisted via its own `security_settings` table (ADR-9) but **not enforced** anywhere yet (TD-26).

## Reports (deprecated)
`routes/report.py` unconditionally redirects to `business_intelligence.index`. `templates/reports/index.html` exists but is dead/unreferenced.
