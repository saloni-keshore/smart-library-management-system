# Routes Reference

Every route in every blueprint. "Auth" = whether the route checks `session["admin_id"]`. See [09_DEPENDENCY_MAP.md](09_DEPENDENCY_MAP.md) for which `database/*` modules each route pulls in.

## `routes/auth.py` — blueprint `auth`, no prefix

| Method | Path | Function | Template | Auth | Purpose |
|---|---|---|---|---|---|
| GET/POST | `/` | `login` | `auth/login.html` | No | Login by username or mobile + password. Shows a signup link only if zero admins exist yet (`show_signup = admin_count == 0`) |
| GET | `/logout` | `logout` | redirect | No | Clears session, redirects to `/` |
| GET/POST | `/register` | `register` | `auth/register.html` | No | Creates a new admin account |
| GET/POST | `/forgot-password` | `forgot_password` | `auth/forgot_password.html` | No | Resets password; requires **both** mobile and full name (case-insensitive) to match — mobile alone is not enough |

Data access: raw SQL via `database.db.get_connection()` directly on `admins` — no query module. Password validation (`validate_password`): min 8 chars, ≥1 letter, ≥1 digit. `register` also checks mobile is exactly 10 digits and username/mobile uniqueness, and hardcodes `role="Admin"` on insert (note: schema default is lowercase `'admin'` — inconsistent casing in practice).

## `routes/dashboard.py` — blueprint `dashboard`, no prefix

| Method | Path | Function | Template | Auth | Purpose |
|---|---|---|---|---|---|
| GET | `/dashboard` | `dashboard` | `dashboard/index.html` | Yes | Main KPI dashboard |

Calls `utils.charts.generate_revenue_chart(admin_id)` and `generate_membership_chart(admin_id)` (regenerates the two dashboard PNGs on every page load). Computes: active/expired student & membership counts, total/pending/today revenue, upcoming expiries (next 7 days, with `days_left` via `julianday`), recent admissions (last 5). Uses `database.cashbook_categories` constants for the quick-add-transaction modal.

## `routes/enquiries.py` — blueprint `enquiry`, prefix `/enquiries`

| Method | Path | Function | Template | Auth | Purpose |
|---|---|---|---|---|---|
| GET | `/enquiries/` | `index` | `enquiries/index.html` | Yes | List all enquiries, left-joined to `students` to flag already-admitted ones |
| GET/POST | `/enquiries/add` | `add` | `enquiries/add.html` | Yes | Create enquiry |
| GET/POST | `/enquiries/edit/<int:enquiry_id>` | `edit` | `enquiries/edit.html` | Yes | Edit enquiry |
| GET | `/enquiries/delete/<int:enquiry_id>` | `delete` | redirect | Yes | **Deletes on a plain GET request, no confirmation step** — see [11_FUTURE_WORK.md](11_FUTURE_WORK.md) |
| GET | `/enquiries/view/<int:enquiry_id>` | `view` | `enquiries/view.html` | Yes | Enquiry detail |

Raw SQL only, no query module.

## `routes/student.py` — blueprint `student`, prefix `/students`

| Method | Path | Function | Template | Auth | Purpose |
|---|---|---|---|---|---|
| GET | `/students/` | `index` | `students/index.html` | Yes | List students with each one's latest membership plan/effective status |
| GET/POST | `/students/admission/<int:enquiry_id>` | `admission` | `students/admission.html` | Yes | Converts an enquiry into a student ("admission") |
| GET | `/students/view/<int:student_id>` | `view` | `students/view.html` | Yes | Student detail: profile, latest membership, full payment history |
| GET/POST | `/students/edit/<int:student_id>` | `edit` | `students/edit.html` | Yes | Edit student fields |

`admission()` guards against double-admission (same mobile+admin_id), copies `purpose`/`preferred_shift` from the enquiry, marks the enquiry `status='Admitted'`, and redirects to `membership.create` to force a membership to be created immediately after. Raw SQL only; cross-blueprint links via `url_for` to `enquiry.index` and `membership.create`.

## `routes/membership.py` — blueprint `membership`, prefix `/memberships`

| Method | Path | Function | Template | Auth | Purpose |
|---|---|---|---|---|---|
| GET | `/memberships/` | `index` | `memberships/index.html` | Yes | List all memberships with student name/mobile |
| GET/POST | `/memberships/create/<int:student_id>` | `create` | `memberships/create.html` | Yes | Create the first/a new membership, optional initial payment |
| GET/POST | `/memberships/renew/<int:student_id>` | `renew` | `memberships/renew.html` | Yes | Expire the prior active membership, create a new one + payment |

Both `create` and `renew` validate `paid_amount`/`due_amount` as non-negative floats, require `total_fee > 0`, and call the shared `database.payment_queries.record_payment()` (globally-unique, admin-configured receipt numbering — see ADR-13) to insert into `payments` and post the matching Cashbook Income entry in the same transaction (category `"Admission Fee"` for create, `"Membership Renewal"` for renew) — fixed 2026-07-22, Payment Workflow Audit; this paragraph previously described the old, since-removed inline `REC-YYYYMMDD-<membership_id>` formula. `renew` also requires at least one prior membership to exist and marks all prior `Active` memberships `Expired`.

## `routes/membership_analytics.py` — blueprint `membership_analytics`, prefix `/membership-analytics`

| Method | Path | Function | Template | Auth | Purpose |
|---|---|---|---|---|---|
| GET | `/membership-analytics/` | `index` | none — redirects | Yes | Permanently redirects to `membership_distribution.index` |

Fixed 2026-07-22 (QA & Validation Sprint): previously rendered `membership/analytics.html`, a path that doesn't exist (the real directory is `templates/memberships/`, plural) — every visit crashed with `jinja2.exceptions.TemplateNotFound`. The template that path was *meant* to reach (`templates/memberships/analytics.html`) turned out to be a 0-byte empty file, so even a corrected path would only have produced a blank, chrome-less page. Now redirects to Membership Distribution (the fully-implemented equivalent page), the same pattern `routes/report.py` already uses for its own superseded route. See [11_FUTURE_WORK.md](11_FUTURE_WORK.md) PF-2 and [CHANGELOG.md](CHANGELOG.md).

## `routes/membership_distribution.py` — blueprint `membership_distribution`, prefix `/membership-distribution`

| Method | Path | Function | Template | Auth | Purpose |
|---|---|---|---|---|---|
| GET | `/membership-distribution/` | `index` | `memberships/distribution.html` | Yes | Plan distribution analytics: per-plan counts/percentages, active/expired totals, full listing with last-payment info, quick insights |

Calls `utils.charts.generate_membership_distribution_donut(admin_id)`. `PLAN_ORDER = ["Monthly", "Quarterly", "Half-Yearly", "Yearly"]` seeds counts so all four plans always show even at zero. "Quick insights" (most popular plan, upcoming renewals, total revenue/pending) are computed purely in Python from the already-fetched row list — no extra queries. Read-only page, no POST handling.

## `routes/payment.py` — blueprint `payment`, prefix `/payments`

| Method | Path | Function | Template | Auth | Purpose |
|---|---|---|---|---|---|
| GET | `/payments/` | `index` | `payments/index.html` | Yes | List all payments, newest first |
| GET/POST | `/payments/collect/<int:membership_id>` | `collect` | `payments/collect.html` | Yes | Collect a payment against a membership's pending balance |

`collect` validates `amount_paid` is numeric, `>0`, and `<= pending_amount`; generates receipt number `REC-YYYYMMDD-<membership_id>-<new_paid>`; updates `memberships.paid_amount`/`pending_amount`; logs an income entry (category `"Membership Fee"`) via `insert_income_entry`.

## `routes/cashbook.py` — blueprint `cashbook`, prefix `/cashbook`

| Method | Path | Function | Template | Auth | Purpose |
|---|---|---|---|---|---|
| GET | `/cashbook/` | `index` | `cashbook/index.html` | Yes | Filterable ledger + totals + charts + audit log |
| POST | `/cashbook/add` | `add_transaction` | redirect | Yes | Add a manual income/expense entry |
| POST | `/cashbook/edit/<int:entry_id>` | `edit_transaction` | redirect | Yes | Edit an existing **manual** entry only |

Heaviest user of `database/cashbook_queries.py` (nearly every function in that module) plus `database.audit_queries.get_recent_audit_log`. `index` supports date presets (`today`/`this_week`/`this_month`/`custom`), search, type/category/payment-method/source filters, and pagination (`TRANSACTIONS_PER_PAGE=10`). `edit_transaction` explicitly blocks editing any row where `source != "Cashbook Manual Entry"` (i.e. auto-generated rows from memberships/payments are read-only here). Builds Chart.js-ready dicts locally (`_build_income_expense_chart`, `_build_category_chart`, `_build_payment_method_chart`).

## `routes/business_intelligence.py` — blueprint `business_intelligence`, prefix `/business-intelligence`

| Method | Path | Function | Template | Auth | Purpose |
|---|---|---|---|---|---|
| GET | `/business-intelligence/` | `index` | `business_intelligence/index.html` | Yes | Health score, revenue growth, top categories, action items, timeline, trend charts |

Pulls from `database.bi_queries` (health score, growth classification, top revenue/expense, action items, timeline) and `database.cashbook_queries` (monthly income/expense). `TREND_MONTHS = 6`. Single comprehensive read-only dashboard, no forms.

## `routes/notification.py` — blueprint `notification`, prefix `/notifications`

| Method | Path | Function | Template | Auth | Purpose |
|---|---|---|---|---|---|
| GET | `/notifications/` and `/notifications/<filter_type>` | `index(filter_type=None)` | `notification/index.html` | Yes | Memberships expiring today / tomorrow / in 3 days / already expired |

`get_notification_summary(admin_id)` (defined here) is also called by `app.py`'s global `inject_notification_summary` context processor, so it runs on **every** authenticated page render, not just this route — it's the data source for the navbar bell dropdown everywhere. `CATEGORY_META` defines label/icon/badge/title per bucket. Raw SQL only.

## `routes/setting.py` — blueprint `setting`, prefix `/settings`

| Method | Path | Function | Template | Auth | Purpose |
|---|---|---|---|---|---|
| GET | `/settings/` | `index` | `settings/index.html` | Yes | Settings landing page (7 cards) |
| GET/POST | `/settings/membership` | `membership_settings` | `settings/membership_settings.html` | Yes | View/update membership plan fees, durations, fine rules. Reminder-day/send-reminder inputs removed — now a read-only summary sourced from Notification Settings |
| GET/POST | `/settings/library` | `library_profile` | `settings/library_profile.html` | Yes | View/update library profile + logo/stamp/signature uploads |
| POST | `/settings/library/remove-logo` | `remove_library_logo` | JSON | Yes (401 JSON, not redirect, if missing) | Deletes logo file from disk + clears DB reference |
| GET/POST | `/settings/receipt` | `receipt_settings` | `settings/receipt_settings.html` | Yes | View/update receipt numbering, branding print toggles, paper size, printing preferences, footer, email preference |
| GET/POST | `/settings/notification` | `notification_settings` | `settings/notification_settings.html` | Yes | View/update reminder rules, notification channels, quiet hours, dashboard-display toggles |
| GET | `/settings/staff` | `staff_access` | `settings/staff_access.html` | Yes | **Placeholder (PF-4)** — "Coming Soon" page explaining the single-admin limitation, previews 4 future roles |
| GET | `/settings/backup` | `data_backup` | `settings/data_backup.html` | Yes | Shows DB size, last backup date, backup location; links to the two export/backup actions below |
| GET | `/settings/backup/export-csv` | `backup_export_csv` | file download | Yes | Downloads a CSV of this admin's `students` rows as `students_export_<timestamp>.csv` |
| POST | `/settings/backup/create` | `backup_create` | file download | Yes | Copies `library.db` into the project-root `backups/` folder as `library_backup_<admin_id>_<timestamp>.db`, records it in `backup_log`, then serves it as a download |
| GET/POST | `/settings/security` | `security_settings` | `settings/security_settings.html` | Yes | Change password (`form_type=password`) or save session preferences (`form_type` defaults to preferences) |

`membership_settings`: builds a diff of what changed (`_build_membership_changes`/`_format_membership_setting`, currency shown as `₹X`, booleans as Enabled/Disabled) and stashes it in `session["membership_change_summary"]` for a one-shot "what changed" banner on the next GET; no longer includes `reminder_days`/`send_reminders` in that diff (see ADR-8 in [DECISIONS.md](DECISIONS.md)) — it now also passes `notification_settings=get_notification_settings(admin_id)` to the template for a read-only reminder summary. `library_profile`: validates required fields, phone digits-only, optional email regex, opening<closing time, and file extensions (`png`/`jpg`/`jpeg`/`webp`); supports an AJAX path (`X-Requested-With` header) returning JSON instead of flash+redirect. `receipt_settings`: reuses the `library_settings` row (redirects to `library_profile` if it doesn't exist yet); validates `receipt_prefix` (≤10 chars, letters/numbers/dash only) and `next_receipt_number` (>0); logo/stamp/signature images are read from Library Profile, not re-uploaded here; builds the same kind of change diff (`_build_receipt_changes`/`_format_receipt_setting`) stashed in `session["receipt_change_summary"]`. Does not generate PDFs, print, or send email — configuration only, per `docs/11_FUTURE_WORK.md`.

`notification_settings`: same "redirect to Library Profile if no row yet" guard as `receipt_settings` (both are `UPDATE`-only on the `library_settings` row); validates `quiet_hours_start`/`quiet_hours_end` as valid `HH:MM` times; builds the same kind of change diff (`_build_notification_changes`/`_format_notification_setting`) stashed in `session["notification_change_summary"]`. Persists reminder-rule/channel/quiet-hours/dashboard-display preferences only — no SMS/Email/WhatsApp dispatch or quiet-hours enforcement exists (TD-24 in [11_FUTURE_WORK.md](11_FUTURE_WORK.md)); `dash_show_pending_fees` is read by `routes/dashboard.py` and the badge/today/tomorrow/overdue toggles are read by `app.py`'s context processor for the navbar bell, but `dash_show_new_admissions` has no consumer yet (TD-25).

`staff_access`: renders a static template, no query, no form — intentionally a placeholder (PF-4).

`data_backup`/`backup_export_csv`/`backup_create`: `data_backup` computes DB file size via `_format_file_size` and reads `get_backup_info(admin_id)` for the "last backup" display. `backup_export_csv` writes an admin-scoped `students` export via `csv.writer` into an in-memory `io.StringIO`. `backup_create` (labeled "Create Backup" in the UI) `shutil.copy2`s the live DB into `backups/` (creating that directory if needed), calls `record_backup()`, then serves the copy as a download. No scheduled/automatic backup exists (PF-5).

`security_settings`: branches on a hidden `form_type` field. `form_type=password` verifies `current_password` against the stored hash (`check_password_hash`), confirms `new_password == confirm_password`, validates the new password with `routes.auth.validate_password`, and updates `admins.password` directly — this path is fully functional (verified end-to-end). The other branch validates `session_timeout_minutes` against `SESSION_TIMEOUT_OPTIONS` (`15`/`30`/`60`/`0` minutes, falling back to `60`) and saves it plus `remember_me_enabled`/`login_notifications_enabled` via `save_security_settings()` — none of these three are actually enforced anywhere yet (TD-26 in [11_FUTURE_WORK.md](11_FUTURE_WORK.md)).

## `routes/report.py` — blueprint `report`, prefix `/reports`

| Method | Path | Function | Template | Auth | Purpose |
|---|---|---|---|---|---|
| GET | `/reports/` | `index` | redirect only | No | **Deprecated shim** — always redirects to `business_intelligence.index`. No auth check, no DB, no template. `templates/reports/index.html` exists on disk but is never rendered by this route. |
