# Routes Reference

Every route in every blueprint. "Auth" = whether the route checks `session["admin_id"]`. See [09_DEPENDENCY_MAP.md](09_DEPENDENCY_MAP.md) for which `database/*` modules each route pulls in.

## `routes/auth.py` — blueprint `auth`, no prefix

| Method | Path | Function | Template | Auth | Purpose |
|---|---|---|---|---|---|
| GET/POST | `/` | `login` | `auth/login.html` | No | Login by username or mobile + password. Shows a signup link only if zero admins exist yet (`show_signup = admin_count == 0`) |
| GET | `/logout` | `logout` | redirect | No | Clears session, redirects to `/` |
| GET/POST | `/register` | `register` | `auth/register.html` | No | Creates a new admin account |
| GET/POST | `/forgot-password` | `forgot_password` | `auth/forgot_password.html` | No | Resets password; requires **both** mobile and full name (case-insensitive) to match — mobile alone is not enough |

Data access: as of 2026-07-23 (ADR-16), Supabase (PostgreSQL) via `database.supabase_client.get_supabase_client()` — `.eq()`-filtered queries directly on `admins`, no query module; was raw SQL via `database.db.get_connection()` until this cutover. `register` used to also mirror-insert the new row into SQLite immediately after the Supabase insert succeeded, since other tables still enforced a SQLite foreign key to `admins.admin_id`; as of 2026-07-25 (ADR-31), that mirror-insert is deleted outright — Supabase is the only store, and this route (like every other route in the app as of Phase 10's completion) has no SQLite dependency left at all. Password validation (`validate_password`): min 8 chars, ≥1 letter, ≥1 digit. `register` also checks mobile is exactly 10 digits and username/mobile uniqueness, and hardcodes `role="Admin"` on insert (note: schema default is lowercase `'admin'` — inconsistent casing in practice).

## `routes/dashboard.py` — blueprint `dashboard`, no prefix

| Method | Path | Function | Template | Auth | Purpose |
|---|---|---|---|---|---|
| GET | `/dashboard` | `dashboard` | `dashboard/index.html` | Yes | Main KPI dashboard |
| GET | `/dashboard/revenue-chart` | `revenue_chart` | JSON | Yes (401 JSON, not redirect, if missing — same shape as `routes/search.py`'s `suggestions()`) | Revenue Overview card's period switcher: `?period=` `this_year` (default) or `last_year` (anything else falls back to `this_year`); returns a Chart.js `{labels, datasets}` object from `build_revenue_chart_data(admin_id, period)` (ADR-56 — was `{"image_url": ...}` when charts were server-rendered PNGs). `dashboard-charts.js` does `chart.data = json; chart.update()` with it |

Builds the two dashboard chart payloads via `utils.chart_data.build_revenue_chart_data(admin_id, "this_year")` and `build_membership_chart_data(admin_id)` (client-side Chart.js as of 2026-08-28, ADR-56 — no server-side PNG). Computes: active/expired student & membership counts, total/pending/today revenue, upcoming expiries (next 7 days, `days_left` via `database.membership_queries.get_days_left()`), recent admissions (last 5) — as of 2026-07-23 (ADR-23), all via Supabase `students`/`enquiries`/`memberships` (`database.membership_queries`'s `get_membership_counts`/`get_memberships_for_admin`/`get_admin_students`, plus direct `count="exact"` queries for the two totals), replacing the raw SQLite `JOIN`s this route used before; "Total Revenue"/"Today's Collection" also moved to Supabase as of 2026-07-24 (ADR-25), via `database.cashbook_queries`. Uses `database.cashbook_categories` constants for the quick-add-transaction modal.

`revenue_chart`: *(added 2026-08-18)* backs the Revenue Overview card's "This Year"/"Last Year" `<select>` (`templates/components/revenue_chart.html`, wired up by `static/js/dashboard-charts.js`'s `initRevenuePeriodSelect()`). Previously the dropdown had no `id`/handler and this route didn't exist — every option silently rendered the same current-year chart.

## `routes/enquiries.py` — blueprint `enquiry`, prefix `/enquiries`

| Method | Path | Function | Template | Auth | Purpose |
|---|---|---|---|---|---|
| GET | `/enquiries/` | `index` | `enquiries/index.html` | Yes | List all enquiries (from Supabase), merged in Python with a Supabase `students` lookup (ADR-23) to flag already-admitted ones |
| GET/POST | `/enquiries/add` | `add` | `enquiries/add.html` | Yes | Create enquiry |
| GET/POST | `/enquiries/edit/<int:enquiry_id>` | `edit` | `enquiries/edit.html` | Yes | Edit enquiry |
| GET | `/enquiries/delete/<int:enquiry_id>` | `delete` | redirect | Yes | **Deletes on a plain GET request, no confirmation step** — see [11_FUTURE_WORK.md](11_FUTURE_WORK.md) |
| GET | `/enquiries/view/<int:enquiry_id>` | `view` | `enquiries/view.html` | Yes | Enquiry detail |

As of 2026-07-23 (ADR-18), `enquiries` reads/writes go through `database.supabase_client.get_supabase_client()` (Supabase is the source of truth), and as of 2026-07-24 (ADR-30) the only store — `add()`/`edit()`/`delete()`'s SQLite `INSERT`/`UPDATE`/`DELETE` calls were deleted outright, no SQLite dependency left anywhere in this file. As of 2026-07-23 (ADR-23), `index()`'s/`view()`'s `enquiry_id → student_id` lookup queries Supabase `students` directly. `_sanitize_date()` normalizes `followup_date` to `None` on blank/unparsable input before any Supabase call, since Postgres's `DATE` column is strictly typed unlike SQLite's. TD-36 (`admission()`'s `status='Admitted'` write not reaching Supabase) is now `Resolved` — see ADR-19.

## `routes/student.py` — blueprint `student`, prefix `/students`

| Method | Path | Function | Template | Auth | Purpose |
|---|---|---|---|---|---|
| GET | `/students/` | `index` | `students/index.html` | Yes | List students (from Supabase) with each one's latest membership plan/effective status merged in from Supabase (ADR-23) |
| GET/POST | `/students/admission/<int:enquiry_id>` | `admission` | `students/admission.html` | Yes | Converts an enquiry into a student ("admission") |
| GET | `/students/view/<int:student_id>` | `view` | `students/view.html` | Yes | Student detail: profile, latest membership, full payment history |
| GET/POST | `/students/edit/<int:student_id>` | `edit` | `students/edit.html` | Yes | Edit student fields |

`admission()` guards against double-admission (same mobile+admin_id), copies `purpose`/`preferred_shift` from the enquiry, marks the enquiry `status='Admitted'`, and redirects to `membership.create` to force a membership to be created immediately after. As of 2026-07-23 (ADR-19), `students` reads/writes go through `database.supabase_client.get_supabase_client()` (Supabase is the source of truth for `index()`/`admission()`/`view()`/`edit()`), and as of 2026-07-24 (ADR-29) the only store — `admission()`/`edit()`'s SQLite `INSERT`/`UPDATE` calls were deleted outright, no SQLite dependency left anywhere in this file. As of 2026-07-23 (ADR-23), `index()`'s own membership merge also reads Supabase via `database.membership_queries.get_memberships_for_admin()` instead of a SQLite self-join. As of 2026-07-24 (ADR-25), `view()` reads its membership and full payment history from Supabase too (`memberships`, and `payments` filtered directly by `student_id`). `admission()` also reads/writes `enquiries` via `get_supabase_client()` (the same Supabase copy `routes/enquiries.py` owns) instead of the old SQLite-only read/update — its `status='Admitted'` flip now reaches Supabase directly, closing TD-36. `_sanitize_date()` normalizes `join_date` the same way `routes/enquiries.py`'s does for `followup_date`. Cross-blueprint links via `url_for` to `enquiry.index` and `membership.create`.

## `routes/membership.py` — blueprint `membership`, prefix `/memberships`

| Method | Path | Function | Template | Auth | Purpose |
|---|---|---|---|---|---|
| GET | `/memberships/` | `index` | `memberships/index.html` | Yes | List all memberships with student name/mobile |
| GET/POST | `/memberships/create/<int:student_id>` | `create` | `memberships/create.html` | Yes | Create the first/a new membership, optional initial payment |
| GET/POST | `/memberships/renew/<int:student_id>` | `renew` | `memberships/renew.html` | Yes | Expire the prior active membership, create a new one + payment |

Both `create` and `renew` validate `paid_amount` as a non-negative float and require `total_fee > 0`; there is no `due_amount` form field (removed 2026-08-17, ADR-45) — `pending_amount` is always derived as `total_fee - paid_amount`, and `paid_amount > total_fee` is rejected. As of ADR-45, `total_fee` itself is server-computed from `membership_settings` (`get_plan_pricing`/`get_admission_fee`) for any standard plan name, not read from client input — only the `"Custom"` plan accepts a client-submitted `total_fee`. `create` (only, not `renew`) additionally accepts `discount_amount`/`discount_reason` as of the same day (ADR-46) — a flat-₹ discount applied on top of the plan-derived total (Total Payable), rejected if negative or `>=` the pre-discount total, otherwise subtracted to produce the `total_fee` actually stored (Final Payable); if `discount_amount`/`discount_reason` don't exist yet on the live Supabase project and a real discount was entered, `create` fails the whole request with a clear flash message (`database.membership_queries.insert_membership()`'s `DiscountColumnsUnavailable`) rather than silently dropping the discount. Both call the shared `database.payment_queries.record_payment()` (globally-unique, admin-configured receipt numbering — see ADR-13) to insert into `payments` and post the matching Cashbook Income entry in the same transaction (category `"Admission Fee"` for create, `"Membership Renewal"` for renew) — fixed 2026-07-22, Payment Workflow Audit; this paragraph previously described the old, since-removed inline `REC-YYYYMMDD-<membership_id>` formula. `renew` also requires at least one prior membership to exist and marks all prior `Active` memberships `Expired`.

As of 2026-07-23 (ADR-20), `memberships` reads/writes go through `database.supabase_client.get_supabase_client()` (Supabase is the source of truth for `index()`/`create()`/`renew()`), and as of 2026-07-24 (ADR-29) the only store — `create()`/`renew()`'s SQLite `INSERT` calls were deleted outright. Both `create()`/`renew()` compute `membership_id` explicitly, as of ADR-29 from Supabase's own `ORDER BY membership_id DESC LIMIT 1` (was SQLite `MAX(membership_id) + 1` before that, the same fix ADR-18/ADR-19 needed for `enquiry_id`/`student_id`). `index()` fetches this admin's students from Supabase to scope which memberships to fetch, then merges the two in Python (same shape `routes/student.py`'s own `index()` uses in reverse). `database.membership_queries.get_active_membership()` (`create()`'s duplicate-active guard, its only caller) now reads Supabase too; `EFFECTIVE_STATUS_SQL`/`DAYS_LEFT_SQL`/`get_membership_counts`/`get_plan_pricing`/`get_admission_fee` are unaffected — still SQL/SQLite-backed (though unused by any live caller — see `database/membership_queries.py`'s file card). TD-37 (`routes/payment.py`'s `collect()` vs. `paid_amount`/`pending_amount` split-brain) was `Resolved` by ADR-21 — `collect()` writes Supabase first, same as here.

## `routes/membership_analytics.py` — blueprint `membership_analytics`, prefix `/membership-analytics`

| Method | Path | Function | Template | Auth | Purpose |
|---|---|---|---|---|---|
| GET | `/membership-analytics/` | `index` | none — redirects | Yes | Permanently redirects to `membership_distribution.index` |

Fixed 2026-07-22 (QA & Validation Sprint): previously rendered `membership/analytics.html`, a path that doesn't exist (the real directory is `templates/memberships/`, plural) — every visit crashed with `jinja2.exceptions.TemplateNotFound`. The template that path was *meant* to reach (`templates/memberships/analytics.html`) turned out to be a 0-byte empty file, so even a corrected path would only have produced a blank, chrome-less page. Now redirects to Membership Distribution (the fully-implemented equivalent page), the same pattern `routes/report.py` already uses for its own superseded route. See [11_FUTURE_WORK.md](11_FUTURE_WORK.md) PF-2 and [CHANGELOG.md](CHANGELOG.md).

## `routes/membership_distribution.py` — blueprint `membership_distribution`, prefix `/membership-distribution`

| Method | Path | Function | Template | Auth | Purpose |
|---|---|---|---|---|---|
| GET | `/membership-distribution/` | `index` | `memberships/distribution.html` | Yes | Plan distribution analytics: per-plan counts/percentages, active/expired totals, full listing with last-payment info, quick insights |

Builds the doughnut payload via `utils.chart_data.build_plan_distribution_chart_data(plan_counts)` (client-side Chart.js as of 2026-08-28, ADR-56). `PLAN_ORDER = ["Monthly", "Quarterly", "Half-Yearly", "Yearly"]` seeds counts so all four plans always show even at zero in the summary cards/bars (the doughnut itself drops zero-count plans). "Quick insights" (most popular plan, upcoming renewals, total revenue/pending) are computed purely in Python from the already-fetched row list — no extra queries. As of 2026-07-23 (ADR-23), total/plan-wise counts and the listing's non-payment columns read Supabase `students`/`memberships` via `database.membership_queries.get_memberships_for_admin()`. As of 2026-07-24 (ADR-25), each row's `receipt_number`/`payment_mode`/`payment_date`/`last_amount_paid` come from `database.payment_queries.get_payments_for_admin()` (Supabase), sorted by `payment_id` descending and reduced to the latest row per `membership_id` in Python — this route has no SQLite dependency left at all. Read-only page, no POST handling.

## `routes/payment.py` — blueprint `payment`, prefix `/payments`

| Method | Path | Function | Template | Auth | Purpose |
|---|---|---|---|---|---|
| GET | `/payments/` | `index` | `payments/index.html` | Yes | List all payments, newest first |
| GET/POST | `/payments/collect/<int:membership_id>` | `collect` | `payments/collect.html` | Yes | Collect a payment against a membership's pending balance |

`collect` reads the target membership from Supabase (source of truth, ADR-21) and verifies it belongs to the logged-in admin via a `students` ownership check (also Supabase, ADR-19); validates `amount_paid` is numeric, `>0`, and `<= pending_amount`; updates `memberships.paid_amount`/`pending_amount` in Supabase — the only store as of 2026-07-24 (ADR-29), no SQLite mirror-write left; generates the receipt number and logs the matching income entry via `database/payment_queries.py`'s `record_payment()` (`receipt_prefix`/`next_receipt_number` from Supabase Settings → Receipt Settings, ADR-13/ADR-24; Supabase-only and strict as of ADR-28), category `"Membership Fee"`.

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

`get_notification_summary(admin_id)` (defined here) is also called by `app.py`'s global `inject_notification_summary` context processor, so it runs on **every** authenticated page render, not just this route — it's the data source for the navbar bell dropdown everywhere. `CATEGORY_META` defines label/icon/badge/title per bucket. As of 2026-07-23 (ADR-23), reads Supabase `students`/`memberships` via `database.membership_queries.get_memberships_for_admin()`/`get_days_left()` — this route has no SQLite dependency left.

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
| GET | `/settings/backup` | `data_backup` | `settings/data_backup.html` | Yes | Shows last backup date, backup location; links to the two export/backup actions below |
| GET | `/settings/backup/export-csv` | `backup_export_csv` | file download | Yes | Downloads a CSV of this admin's `students` rows as `students_export_<timestamp>.csv` |
| POST | `/settings/backup/create` | `backup_create` | file download | Yes | As of 2026-07-25 (ADR-32), exports this admin's own rows across every admin-scoped Supabase table as JSON into the project-root `backups/` folder as `library_backup_<admin_id>_<timestamp>.json`, records it in `backup_log`, then serves it as a download |
| GET/POST | `/settings/security` | `security_settings` | `settings/security_settings.html` | Yes | Change password (`form_type=password`) or save session preferences (`form_type` defaults to preferences) |

`membership_settings`: builds a diff of what changed (`_build_membership_changes`/`_format_membership_setting`, currency shown as `₹X`, booleans as Enabled/Disabled) and stashes it in `session["membership_change_summary"]` for a one-shot "what changed" banner on the next GET; no longer includes `reminder_days`/`send_reminders` in that diff (see ADR-8 in [DECISIONS.md](DECISIONS.md)) — it now also passes `notification_settings=get_notification_settings(admin_id)` to the template for a read-only reminder summary. `library_profile`: validates required fields, phone digits-only, optional email regex, opening<closing time, and file extensions (`png`/`jpg`/`jpeg`/`webp`); supports an AJAX path (`X-Requested-With` header) returning JSON instead of flash+redirect. `receipt_settings`: reuses the `library_settings` row (redirects to `library_profile` if it doesn't exist yet); validates `receipt_prefix` (≤10 chars, letters/numbers/dash only) and `next_receipt_number` (>0); logo/stamp/signature images are read from Library Profile, not re-uploaded here; builds the same kind of change diff (`_build_receipt_changes`/`_format_receipt_setting`) stashed in `session["receipt_change_summary"]`. Does not generate PDFs, print, or send email — configuration only, per `docs/11_FUTURE_WORK.md`.

`notification_settings`: same "redirect to Library Profile if no row yet" guard as `receipt_settings` (both are `UPDATE`-only on the `library_settings` row); validates `quiet_hours_start`/`quiet_hours_end` as valid `HH:MM` times; builds the same kind of change diff (`_build_notification_changes`/`_format_notification_setting`) stashed in `session["notification_change_summary"]`. Persists reminder-rule/channel/quiet-hours/dashboard-display preferences only — no SMS/Email/WhatsApp dispatch or quiet-hours enforcement exists (TD-24 in [11_FUTURE_WORK.md](11_FUTURE_WORK.md)); `dash_show_pending_fees` is read by `routes/dashboard.py` and the badge/today/tomorrow/overdue toggles are read by `app.py`'s context processor for the navbar bell, but `dash_show_new_admissions` has no consumer yet (TD-25).

`staff_access`: renders a static template, no query, no form — intentionally a placeholder (PF-4).

`data_backup`/`backup_export_csv`/`backup_create`: `data_backup` reads `get_backup_info(admin_id)` (Supabase, ADR-24) for the "last backup" display — as of 2026-07-25 (ADR-32) it no longer shows a DB-size stat (that was a SQLite-file-only concept with no equivalent once every admin shares one Supabase project). `backup_export_csv` writes an admin-scoped `students` export via `csv.writer` into an in-memory `io.StringIO` — as of 2026-07-24 (ADR-24) the `students` rows come from Supabase (`database.supabase_client.get_supabase_client()`) instead of the SQLite mirror. `backup_create` (labeled "Create Backup" in the UI), as of 2026-07-25 (ADR-32), calls a new helper, `_collect_admin_backup_data(admin_id)`, which queries every admin-scoped Supabase table filtered to this admin only (directly via `admin_id` for most tables; via this admin's own `student_id`s for `memberships`/`payments`, which have no `admin_id` column), serializes the result to JSON, writes it into `backups/` (creating that directory if needed), calls `record_backup()` (Supabase, ADR-24), then serves it as a download. This replaced the old whole-file SQLite snapshot, which was **TD-32**, a critical cross-tenant data leak (every admin could download every other admin's data) — the rebuild fixes it as a side effect of removing SQLite. No scheduled/automatic backup exists (PF-5).

`security_settings`: branches on a hidden `form_type` field. `form_type=password` verifies `current_password` against the stored hash (`check_password_hash`), confirms `new_password == confirm_password`, validates the new password with `routes.auth.validate_password`, and updates `admins.password` — as of 2026-07-23 (ADR-17) this reads/writes Supabase via `database.supabase_client.get_supabase_client()` (`.eq("admin_id", admin_id)`-filtered, wrapped in `try/except postgrest.exceptions.APIError`), the same table/client `routes/auth.py`'s login/register/forgot-password use, so a password changed here now takes effect on the very next login (closed TD-35 in [11_FUTURE_WORK.md](11_FUTURE_WORK.md)) — this path is fully functional (verified end-to-end). The other branch validates `session_timeout_minutes` against `SESSION_TIMEOUT_OPTIONS` (`15`/`30`/`60`/`0` minutes, falling back to `60`) and saves it plus `remember_me_enabled`/`login_notifications_enabled` via `save_security_settings()` (Supabase as of 2026-07-24, ADR-24) — none of these three are actually enforced anywhere yet (TD-26 in [11_FUTURE_WORK.md](11_FUTURE_WORK.md)).

## `routes/report.py` — blueprint `report`, prefix `/reports`

| Method | Path | Function | Template | Auth | Purpose |
|---|---|---|---|---|---|
| GET | `/reports/` | `index` | redirect only | No | **Deprecated shim** — always redirects to `business_intelligence.index`. No auth check, no DB, no template. `templates/reports/index.html` exists on disk but is never rendered by this route. |

## `routes/search.py` — blueprint `search`, prefix `/search` *(added 2026-08-17, ADR-44)*

| Method | Path | Function | Template | Auth | Purpose |
|---|---|---|---|---|---|
| GET | `/search/suggestions` | `suggestions` | JSON | Yes (401 JSON, not redirect, if missing — same shape as `routes/ai_center.py`'s `student_suggestions()`) | The global navbar search bar's autocomplete data source: `?q=` matched (case-insensitive, partial) against Students/Payments/Enquiries/Cashbook at once, capped at 5 per type, grouped into one JSON object |

Backed entirely by `database.search_queries.global_search()` — this route does no filtering of its own, only reshapes each group's rows into the fields `static/js/navbar_search.js` renders. `GET`-only, so `app.py`'s CSRF `before_request` check (which only gates `POST`/`PUT`/`PATCH`/`DELETE`) never applies here. Cashbook results carry no navigable ID in the response — there's no single-entry Cashbook view page yet (TD-56 in [11_FUTURE_WORK.md](11_FUTURE_WORK.md)), so the frontend renders them non-clickable rather than linking somewhere misleading.
