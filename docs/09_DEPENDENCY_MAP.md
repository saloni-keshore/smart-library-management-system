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
routes/dashboard.py            → database.db.get_connection   (students, memberships, payments, enquiries —
                                  memberships is Supabase-backed as of ADR-20/ADR-21, but this read stays against
                                  the SQLite mirror, which routes/membership.py's create()/renew() and
                                  routes/payment.py's collect() both keep current)
                                → utils.charts (generate_revenue_chart, generate_membership_chart)
                                → database.cashbook_categories (constants only)
                                → database.cashbook_queries (get_pending_fees, get_total_fee_revenue - added
                                  2026-07-21, replacing two inline SUM() queries that duplicated Cashbook's own)
                                → database.membership_queries (get_membership_counts, DAYS_LEFT_SQL - added
                                  2026-07-21, replacing an inline COUNT(DISTINCT CASE...) query and a raw
                                  julianday() expression - see TD-6)
routes/enquiries.py            → database.supabase_client.get_supabase_client   (enquiries table, Supabase/
                                  PostgreSQL — as of 2026-07-23, ADR-18; was database.db.get_connection until
                                  this cutover; source of truth for index()/edit()/view())
                                → database.db.get_connection   (SQLite mirror-write in add()/edit()/delete() —
                                  temporary bridge since routes/payment.py/routes/dashboard.py/
                                  routes/membership_distribution.py/routes/notification.py/etc. still JOIN
                                  students directly against SQLite; also used read-only in index()/view() to
                                  look up students' enquiry_id → student_id map)
routes/student.py              → database.supabase_client.get_supabase_client   (students table, Supabase/
                                  PostgreSQL — as of 2026-07-23, ADR-19; was database.db.get_connection until
                                  this cutover; source of truth for index()/admission()/view()/edit(); also
                                  reads/writes enquiries there directly in admission(), closing TD-36)
                                → database.db.get_connection   (SQLite mirror-write in admission()/edit() —
                                  temporary bridge since routes/payment.py/routes/dashboard.py/
                                  routes/membership_distribution.py/routes/notification.py/routes/setting.py's
                                  backup functions/database.bi_queries/cashbook_queries/membership_queries all
                                  still JOIN students directly against SQLite (routes/membership.py migrated
                                  off this list 2026-07-23, ADR-20 — its own student lookups now go through
                                  Supabase too); also used read-only in index()/view() for memberships/payments —
                                  memberships is Supabase-backed as of ADR-20 too, but this read stays against
                                  the SQLite mirror, which routes/membership.py keeps current; payments stays
                                  SQLite)
                                → database.membership_queries.EFFECTIVE_STATUS_SQL (added 2026-07-21 - TD-6)
routes/membership_distribution.py → database.db.get_connection (memberships, students, payments)
                                → utils.charts.generate_membership_distribution_donut
                                → database.cashbook_queries (get_pending_fees, get_total_fee_revenue - added
                                  2026-07-21, replacing a Python-side sum() over the page's fetched rows)
                                → database.membership_queries (get_membership_counts, get_effective_status,
                                  DAYS_LEFT_SQL - added 2026-07-21, replacing two standalone COUNT queries plus
                                  an inline is_active boolean - see TD-6)
routes/notification.py         → database.db.get_connection   (memberships, students)
                                → database.membership_queries.DAYS_LEFT_SQL (added 2026-07-21)
routes/membership_analytics.py → (no DB access at all - redirects to membership_distribution.index, fixed 2026-07-22)
```

## Routes that delegate to a `database/*_queries.py` module

```
routes/membership.py           → database.supabase_client.get_supabase_client   (memberships table, Supabase/
                                  PostgreSQL — as of 2026-07-23, ADR-20; was database.db.get_connection until
                                  this cutover; source of truth for index()/create()/renew(); also reads
                                  students there directly (Supabase, ADR-19) instead of the SQLite mirror)
                                → database.db.get_connection   (SQLite mirror-write in create()/renew() —
                                  temporary bridge since routes/dashboard.py/routes/membership_distribution.py/
                                  routes/notification.py/routes/student.py's view()/database.cashbook_queries'
                                  get_pending_fees()/database.bi_queries all still JOIN memberships directly
                                  against SQLite (routes/payment.py migrated off this list 2026-07-23, ADR-21 —
                                  its collect() now writes Supabase directly too, closing TD-37))
                                → database.payment_queries.record_payment (added 2026-07-22, replacing a direct
                                  database.cashbook_queries.insert_income_entry call + an inline receipt-number
                                  formula duplicated across create()/renew()/payment.collect() - TD-22, ADR-13;
                                  still SQLite-only, unaffected by ADR-20)
                                → database.membership_settings_queries.get_membership_settings (added 2026-07-21 - TD-7)
                                → database.membership_queries (get_effective_status, get_active_membership —
                                  now Supabase-backed since create() is its only caller, ADR-20 —
                                  get_plan_pricing, get_admission_fee - added 2026-07-21 - TD-6/TD-7)
routes/payment.py              → database.supabase_client.get_supabase_client   (memberships table, Supabase/
                                  PostgreSQL — as of 2026-07-23, ADR-21; was database.db.get_connection until this
                                  cutover; source of truth for collect()'s paid_amount/pending_amount read+update;
                                  also reads students there directly (Supabase, ADR-19) to verify ownership)
                                → database.db.get_connection   (index()'s own SQL for payments/students, unchanged
                                  and unmigrated; SQLite mirror-write of the same paid_amount/pending_amount
                                  update in collect() — temporary bridge since routes/dashboard.py/
                                  routes/membership_distribution.py/routes/notification.py/routes/student.py's
                                  view()/database.cashbook_queries' get_pending_fees()/database.bi_queries all
                                  still JOIN memberships directly against SQLite)
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
routes/business_intelligence.py → database.cashbook_queries.get_monthly_income / get_monthly_expense
                                → database.bi_queries (last_n_months, get_monthly_new_memberships,
                                   get_business_health_score, get_revenue_growth, classify_revenue_health,
                                   classify_expense_health, get_top_revenue_sources,
                                   get_top_expense_categories, get_action_items, get_business_timeline)
routes/setting.py              → database.settings_queries (get/save/create/update/clear library settings)
                                → database.membership_settings_queries (get/save)
                                → database.supabase_client.get_supabase_client (security_settings()'s password
                                  branch ONLY, admins table, Supabase/PostgreSQL — as of 2026-07-23, ADR-17; was
                                  database.db.get_connection until this cutover; every other function in this
                                  file, including the rest of security_settings(), is still SQLite)
routes/report.py               → (no DB access — pure redirect)
```

## `database/` internal dependencies

```
database/cashbook_queries.py   → database.audit_queries.log_entry   (writes an audit row in the same transaction
                                                                       as insert_transaction, insert_income_entry,
                                                                       update_manual_transaction)
database/bi_queries.py         → database.cashbook_queries (get_monthly_income, get_monthly_expense,
                                   get_income_category_totals, get_expense_category_totals,
                                   get_pending_fees, get_total_fee_revenue)
database/audit_queries.py      → (no internal dependencies — takes a cursor, doesn't open its own connection)
database/membership_settings_queries.py → database.db.get_connection only
database/membership_queries.py → database.db.get_connection only (added 2026-07-21 - see TD-6/TD-7)
database/payment_queries.py    → database.cashbook_queries.insert_income_entry (added 2026-07-22 - see TD-22, ADR-13;
                                   generate_receipt_number() reads/writes library_settings directly via the caller's
                                   conn, no separate connection)
database/settings_queries.py   → database.db.get_connection only
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

`utils/charts.py` itself imports `database.db.get_connection` directly — it is not a pure function of data passed in, it queries the DB on its own.

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
