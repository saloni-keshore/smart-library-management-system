# Feature Modules — End-to-End Walkthroughs

Each section traces a feature from route → data access → template, so you can find every file involved without grepping.

## Auth
`routes/auth.py` (no query module, raw SQL on `admins`) → `templates/auth/{login,register,forgot_password}.html` (extend `layouts/auth_base.html`) → `static/css/login.css`, `static/js/login.js`. Session keys set on success: `admin_id`, `username`.

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

## Membership Analytics (stub)
`routes/membership_analytics.py` → `templates/memberships/analytics.html`, no data passed — see [11_FUTURE_WORK.md](11_FUTURE_WORK.md).

## Cashbook (manual ledger + audit)
`routes/cashbook.py` → `database/cashbook_queries.py` (nearly every function) + `database/audit_queries.py` (`get_recent_audit_log`) + `database/cashbook_categories.py` (allowed categories/methods) → `templates/cashbook/index.html` → `components/cashbook_{summary_cards, filters, charts, transactions, activity_log}.html` → `static/js/cashbook.js`, `static/js/transaction_modal.js`, `static/css/cashbook.css`.

## Business Intelligence (derived analytics on top of Cashbook)
`routes/business_intelligence.py` → `database/bi_queries.py` (health score, growth, top categories, action items, timeline) + `database/cashbook_queries.py` (monthly income/expense) → `templates/business_intelligence/index.html` → `components/bi_*.html` (9 files) → `static/js/business_intelligence.js`, `static/css/business_intelligence.css`.

## Notifications (expiry alerts)
`routes/notification.py`'s `get_notification_summary(admin_id)` is called two ways: (1) directly by `notification.index()` for the full notifications page, and (2) globally by `app.py`'s `inject_notification_summary` context processor on **every** authenticated page render, feeding the navbar bell (`components/notification_dropdown.html`). One function, two consumers.

## Settings
- **Library Profile**: `routes/setting.py`'s `library_profile()` + `remove_library_logo()` → `database/settings_queries.py` → `templates/settings/library_profile.html` → `static/js/settings.js`, `static/css/settings.css`. Uploaded files land in `static/uploads/settings/`.
- **Membership Settings**: `routes/setting.py`'s `membership_settings()` → `database/membership_settings_queries.py` → `templates/settings/membership_settings.html`. Note: this configures plan pricing/policy but is **not yet read by** `routes/membership.py`'s create/renew flow (see [11_FUTURE_WORK.md](11_FUTURE_WORK.md)) — fees are still entered manually per membership.
- **Receipt Settings / Notification Settings**: stubs, flash "coming soon", no templates/query modules exist yet.

## Reports (deprecated)
`routes/report.py` unconditionally redirects to `business_intelligence.index`. `templates/reports/index.html` exists but is dead/unreferenced.
