# Dependency Map

Which files import/call which. Two data-access styles coexist (see [02_ARCHITECTURE.md](02_ARCHITECTURE.md)) — this map makes that split explicit.

## `app.py` → everything

`app.py` imports and registers all 13 blueprints, and imports `get_notification_summary` from `routes/notification.py` for its global context processor. Nothing imports `app.py` back (it's the entry point).

## Routes that use raw SQL directly (no `database/*_queries.py` module)

```
routes/auth.py                 → database.supabase_client.get_supabase_client   (admins table, Supabase/PostgreSQL —
                                  as of 2026-07-23, ADR-16; was database.db.get_connection until this cutover)
                                → database.db.get_connection   (register() ONLY — mirror-inserts the same new admin
                                  into SQLite too, since enquiries/students/library_settings/membership_settings/
                                  audit_log still enforce a SQLite FK to admins.admin_id; TD-35, temporary bridge)
routes/dashboard.py            → database.supabase_client.get_supabase_client   (as of 2026-07-23, ADR-23 —
                                  total-students/total-enquiries counts, source-of-truth Supabase reads)
                                → database.membership_queries (get_membership_counts, get_memberships_for_admin,
                                  get_admin_students, get_days_left — as of 2026-07-23, ADR-23, replacing the
                                  raw SQLite JOINs and DAYS_LEFT_SQL this route used before; no SQLite dependency
                                  left in this route)
                                → utils.charts (generate_revenue_chart — still SQLite, payments unmigrated;
                                  generate_membership_chart — Supabase, ADR-23)
                                → database.cashbook_categories (constants only)
                                → database.cashbook_queries (get_pending_fees — Supabase, ADR-23;
                                  get_total_fee_revenue/get_today_fee_collection — still SQLite, payments
                                  unmigrated)
routes/enquiries.py            → database.supabase_client.get_supabase_client   (enquiries table, Supabase/
                                  PostgreSQL — as of 2026-07-23, ADR-18; was database.db.get_connection until
                                  this cutover; source of truth for index()/edit()/view(); as of ADR-23, also
                                  used for index()'s/view()'s students lookup, previously SQLite)
                                → database.db.get_connection   (SQLite mirror-write in add()/edit()/delete()
                                  only, as of ADR-23 — temporary bridge since routes/payment.py's index()/
                                  database.payment_queries' receipt-fallback branch/utils.charts' revenue chart
                                  still JOIN students directly against SQLite, payments unmigrated; routes/
                                  setting.py's backup_export_csv() migrated off this list, ADR-24)
routes/student.py              → database.supabase_client.get_supabase_client   (students table, Supabase/
                                  PostgreSQL — as of 2026-07-23, ADR-19; was database.db.get_connection until
                                  this cutover; source of truth for index()/admission()/view()/edit(); also
                                  reads/writes enquiries there directly in admission(), closing TD-36)
                                → database.db.get_connection   (SQLite mirror-write in admission()/edit(), and
                                  view()'s membership/payment lookups — payments is unmigrated; as of ADR-23,
                                  index()'s own membership merge no longer uses this)
                                → database.membership_queries (get_memberships_for_admin, get_effective_status —
                                  as of 2026-07-23, ADR-23, replacing the raw SQLite self-join index() used before)
routes/membership_distribution.py → database.supabase_client (via database.membership_queries, ADR-23 —
                                  students/memberships reads for everything except each row's last-payment
                                  columns)
                                → database.db.get_connection (as of 2026-07-23, ADR-23 — now only the batched
                                  payments lookup for receipt_number/payment_mode/payment_date/last_amount_paid,
                                  payments unmigrated)
                                → utils.charts.generate_membership_distribution_donut (Supabase, ADR-23)
                                → database.cashbook_queries (get_pending_fees, get_total_fee_revenue)
                                → database.membership_queries (get_membership_counts, get_memberships_for_admin,
                                  get_effective_status — as of 2026-07-23, ADR-23, replacing two raw SQLite
                                  JOINs and DAYS_LEFT_SQL)
routes/notification.py         → database.membership_queries (get_memberships_for_admin, get_days_left — as of
                                  2026-07-23, ADR-23, replacing database.db.get_connection/DAYS_LEFT_SQL; this
                                  route has no SQLite dependency left)
routes/membership_analytics.py → (no DB access at all - redirects to membership_distribution.index, fixed 2026-07-22)
```

## Routes that delegate to a `database/*_queries.py` module

```
routes/membership.py           → database.supabase_client.get_supabase_client   (memberships table, Supabase/
                                  PostgreSQL — as of 2026-07-23, ADR-20; was database.db.get_connection until
                                  this cutover; source of truth for index()/create()/renew(); also reads
                                  students there directly (Supabase, ADR-19) instead of the SQLite mirror)
                                → database.db.get_connection   (SQLite mirror-write in create()/renew() —
                                  temporary bridge since routes/student.py's view() (the one remaining
                                  memberships-mirror reader, ADR-23) still JOINs memberships directly against
                                  SQLite)
                                → database.payment_queries.record_payment (added 2026-07-22, replacing a direct
                                  database.cashbook_queries.insert_income_entry call + an inline receipt-number
                                  formula duplicated across create()/renew()/payment.collect() - TD-22, ADR-13;
                                  still SQLite-only, unaffected by ADR-20)
                                → database.membership_settings_queries.get_membership_settings (added 2026-07-21 - TD-7;
                                  Supabase as of 2026-07-24, ADR-24)
                                → database.membership_queries (get_effective_status, get_active_membership —
                                  now Supabase-backed since create() is its only caller, ADR-20 —
                                  get_plan_pricing, get_admission_fee - added 2026-07-21 - TD-6/TD-7)
routes/payment.py              → database.supabase_client.get_supabase_client   (memberships table, Supabase/
                                  PostgreSQL — as of 2026-07-23, ADR-21; was database.db.get_connection until this
                                  cutover; source of truth for collect()'s paid_amount/pending_amount read+update;
                                  also reads students there directly (Supabase, ADR-19) to verify ownership)
                                → database.db.get_connection   (index()'s own SQL for payments/students, unchanged
                                  and unmigrated; SQLite mirror-write of the same paid_amount/pending_amount
                                  update in collect() — temporary bridge since routes/student.py's view() (the
                                  one remaining memberships-mirror reader, ADR-23) still JOINs memberships
                                  directly against SQLite)
                                → database.payment_queries.record_payment (added 2026-07-22 - see routes/membership.py
                                  note above, same fix; still SQLite-only, unaffected by ADR-21)
routes/cashbook.py              → database.cashbook_queries (insert_transaction, get_total_income/expense,
                                   get_today_income/expense, get_pending_fees, get_monthly_income/expense,
                                   get_income_category_totals, get_expense_category_totals,
                                   get_payment_method_distribution, get_cash_balance,
                                   get_todays_transaction_count, get_cashbook_ledger,
                                   get_transaction_by_id, update_manual_transaction)
                                → database.audit_queries.get_recent_audit_log
                                → database.cashbook_categories (constants)
                                (no code changes for the ADR-22 Supabase cutover - see cashbook_queries.py/
                                 audit_queries.py below, this route's own calls are unchanged)
routes/business_intelligence.py → database.cashbook_queries.get_monthly_income / get_monthly_expense
                                → database.bi_queries (last_n_months, get_monthly_new_memberships,
                                   get_business_health_score, get_revenue_growth, classify_revenue_health,
                                   classify_expense_health, get_top_revenue_sources,
                                   get_top_expense_categories, get_action_items, get_business_timeline)
routes/setting.py              → database.settings_queries (get/save/create/update/clear library settings —
                                  Supabase, ADR-24), database.receipt_settings_queries (Supabase, ADR-24),
                                  database.notification_settings_queries (Supabase, ADR-24)
                                → database.membership_settings_queries (get/save — Supabase, ADR-24)
                                → database.backup_queries (Supabase, ADR-24), database.security_settings_queries
                                  (Supabase, ADR-24)
                                → database.supabase_client.get_supabase_client (security_settings()'s password
                                  branch, admins table, ADR-17; also backup_export_csv()'s students read, ADR-24)
                                → database.db.get_connection (backup_create()'s whole-file SQLite copy and
                                  data_backup()'s db_size display only, as of 2026-07-24 ADR-24 — every other
                                  function in this file is Supabase-backed)
routes/report.py               → (no DB access — pure redirect)
```

## `database/` internal dependencies

```
database/cashbook_queries.py   → database.audit_queries.log_entry   (SQLite mirror audit-write only, same
                                                                       transaction as insert_transaction,
                                                                       insert_income_entry, update_manual_transaction)
                                → database.supabase_client.get_supabase_client   (as of 2026-07-23, ADR-22 —
                                  cashbook table, source of truth for every read; primary write for
                                  insert_transaction(), best-effort mirror write for insert_income_entry() —
                                  see routes/membership.py's/routes/payment.py's cards for why the latter can't
                                  be strict; payment_id never sent to Supabase, TD-38)
                                → database.membership_queries.get_memberships_for_admin (as of 2026-07-23,
                                  ADR-23 — get_pending_fees() only, Supabase students/memberships)
                                → database.db.get_connection   (SQLite mirror read/write — every cashbook write's
                                  mirror row, plus get_today_fee_collection()/get_total_fee_revenue(), unchanged,
                                  reading payments/students not cashbook)
database/bi_queries.py         → database.cashbook_queries (get_monthly_income, get_monthly_expense,
                                   get_income_category_totals, get_expense_category_totals,
                                   get_pending_fees, get_total_fee_revenue, get_recent_transactions — all now
                                   Supabase-backed for the cashbook-table ones, as of ADR-22)
                                → database.membership_queries.get_memberships_for_admin (as of 2026-07-23,
                                  ADR-23 — replaces database.db.get_connection for its three membership-side
                                  functions; this module has no SQLite dependency left)
database/audit_queries.py      → database.supabase_client.get_supabase_client   (as of 2026-07-23, ADR-22 —
                                  audit_log table, source of truth for get_recent_audit_log(); log_entry()
                                  itself is unchanged — takes a cursor, doesn't open its own connection, SQLite
                                  mirror-write only)
database/membership_settings_queries.py → database.supabase_client.get_supabase_client, database.settings_queries._now_iso
                                  (as of 2026-07-24, ADR-24 — no SQLite dependency left)
database/membership_queries.py → database.supabase_client.get_supabase_client only (as of 2026-07-23, ADR-23 —
                                  this module has no SQLite dependency left at all; get_membership_counts()
                                  moved to Supabase, joining get_active_membership() which already was, ADR-20)
database/payment_queries.py    → database.cashbook_queries.insert_income_entry (added 2026-07-22 - see TD-22, ADR-13)
                                → database.supabase_client.get_supabase_client (as of 2026-07-24, ADR-24 —
                                  generate_receipt_number()'s library_settings read/advance only; its payments
                                  uniqueness check stays on the caller's SQLite conn, payments unmigrated - TD-40)
database/settings_queries.py   → database.supabase_client.get_supabase_client, postgrest.exceptions.APIError
                                  (as of 2026-07-24, ADR-24 — no SQLite dependency left; also exports _now_iso()/
                                  _normalize_timestamps(), imported by receipt_settings_queries.py/
                                  notification_settings_queries.py/membership_settings_queries.py/backup_queries.py/
                                  security_settings_queries.py)
database/receipt_settings_queries.py → database.supabase_client.get_supabase_client, database.settings_queries._now_iso
                                  (as of 2026-07-24, ADR-24)
database/notification_settings_queries.py → database.supabase_client.get_supabase_client,
                                  database.settings_queries._now_iso, flask.g (as of 2026-07-24, ADR-24)
database/backup_queries.py     → database.supabase_client.get_supabase_client, database.settings_queries._now_iso
                                  (as of 2026-07-24, ADR-24)
database/security_settings_queries.py → database.supabase_client.get_supabase_client, database.settings_queries._now_iso
                                  (as of 2026-07-24, ADR-24)
database/cashbook_categories.py → (no DB access — static constants module)
```

## Cross-blueprint references (via `url_for`, not Python imports)

These are runtime-only couplings — renaming a blueprint or endpoint function breaks these silently (no import error, just a `BuildError` at request time):

```
routes/student.py     admission() → url_for('membership.create', ...)   after successful admission
routes/student.py     admission() → url_for('enquiry.index')            when enquiry not found
routes/membership.py  create/renew() → url_for('student.view', ...)     after success
routes/membership.py  renew()    → url_for('membership.create', ...)    when no prior membership exists
routes/cashbook.py    add_transaction() → url_for('dashboard.dashboard') optional redirect target
routes/setting.py     all routes → url_for('setting.index')             self-referencing redirects
```

## `utils/charts.py` — called by, not calling

```
routes/dashboard.py               → utils.charts.generate_revenue_chart
                                   → utils.charts.generate_membership_chart
routes/membership_distribution.py → utils.charts.generate_membership_distribution_donut
```

`utils/charts.py` itself is not a pure function of data passed in — it queries the DB on its own. As of 2026-07-23 (ADR-23), `generate_membership_chart`/`generate_membership_distribution_donut` import `database.membership_queries.get_memberships_for_admin` (Supabase); `generate_revenue_chart` still imports `database.db.get_connection` directly (SQLite, `payments` unmigrated) — the two chart functions in this file no longer share a single backend.

## Template include/extend graph (high level)

```
layouts/base.html          ← extended by every authenticated page
  includes layouts/navbar.html
    includes components/notification_dropdown.html
  includes layouts/sidebar.html

layouts/auth_base.html     ← extended by auth/login.html, auth/register.html, auth/forgot_password.html

dashboard/index.html       includes components/{dashboard_header, quick_actions, revenue_chart,
                                     membership_chart, expiry_table, recent_admissions,
                                     add_transaction_modal, edit_transaction_modal}.html

cashbook/index.html        includes components/cashbook_{summary_cards, filters, charts,
                                     transactions, activity_log}.html
                                     + components/{add,edit,transaction_details}_transaction_modal.html

business_intelligence/index.html includes components/bi_{health_score, health_status, action_center,
                                     revenue_growth, revenue_trend_chart, membership_growth_chart,
                                     top_revenue, top_expense, timeline, advisor}.html

memberships/distribution.html includes components/membership_{summary_cards, distribution_chart,
                                     distribution_table, filters, quick_insights, progress}.html
```

If you rename or delete a component template, grep the relevant feature's `index.html` for `{% include` / `{% call` before assuming it's safe.
