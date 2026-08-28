# Dependency Map

Which files import/call which. Two data-access styles coexist (see [02_ARCHITECTURE.md](02_ARCHITECTURE.md)) — this map makes that split explicit.

## `app.py` → everything

`app.py` imports and registers all 13 blueprints, and imports `get_notification_summary` from `routes/notification.py` for its global context processor. Nothing imports `app.py` back (it's the entry point).

## Routes that use raw SQL directly (no `database/*_queries.py` module)

```
routes/auth.py                 → database.supabase_client.get_supabase_client   (admins table, Supabase/PostgreSQL —
                                  as of 2026-07-23, ADR-16; was database.db.get_connection until this cutover; as of
                                  2026-07-25, ADR-31, the ONLY store — no database.db.get_connection/sqlite3 left
                                  in this file at all, the last of the app's seven mirrors/bridges to reach that
                                  state)
routes/dashboard.py            → database.supabase_client.get_supabase_client   (as of 2026-07-23, ADR-23 —
                                  total-students/total-enquiries counts, source-of-truth Supabase reads)
                                → database.membership_queries (get_membership_counts, get_memberships_for_admin,
                                  get_admin_students, get_days_left — as of 2026-07-23, ADR-23, replacing the
                                  raw SQLite JOINs and DAYS_LEFT_SQL this route used before; no SQLite dependency
                                  left in this route)
                                → utils.chart_data (build_revenue_chart_data, build_membership_chart_data —
                                  client-side Chart.js payloads, ADR-56, replacing utils.charts)
                                → database.cashbook_categories (constants only)
                                → database.cashbook_queries (get_pending_fees — Supabase, ADR-23;
                                  get_total_fee_revenue/get_today_fee_collection — Supabase, ADR-25; this
                                  route has no SQLite dependency left at all)
routes/enquiries.py            → database.supabase_client.get_supabase_client   (enquiries table, Supabase/
                                  PostgreSQL — as of 2026-07-23, ADR-18, and as of 2026-07-24 (ADR-30) the only
                                  store; source of truth for index()/edit()/view(); as of ADR-23, also used for
                                  index()'s/view()'s students lookup, previously SQLite)
                                (as of 2026-07-24, ADR-30: no database.db.get_connection dependency left at all -
                                  add()/edit()/delete()'s SQLite mirror-writes were removed outright, the sixth
                                  mirror fully removed in Phase 10)
routes/student.py              → database.supabase_client.get_supabase_client   (students table, Supabase/
                                  PostgreSQL — as of 2026-07-23, ADR-19; source of truth for index()/admission()/
                                  view()/edit(), and as of 2026-07-24 (ADR-29) the only store; also reads/writes
                                  enquiries there directly in admission(), closing TD-36; as of 2026-07-24
                                  (ADR-25), also view()'s memberships/payments reads)
                                → database.membership_queries (get_memberships_for_admin, get_effective_status —
                                  as of 2026-07-23, ADR-23, replacing the raw SQLite self-join index() used before)
                                (as of 2026-07-24, ADR-29: no database.db.get_connection dependency left at all -
                                  admission()/edit()'s SQLite mirror-writes were removed outright)
routes/membership_distribution.py → database.supabase_client (via database.membership_queries, ADR-23 —
                                  students/memberships reads)
                                → database.payment_queries.get_payments_for_admin (as of 2026-07-24, ADR-25,
                                  replacing the batched SQLite payments lookup for receipt_number/payment_mode/
                                  payment_date/last_amount_paid — this route has no SQLite dependency left)
                                → utils.chart_data.build_plan_distribution_chart_data (client-side Chart.js
                                  doughnut payload, ADR-56, replacing utils.charts.generate_membership_distribution_donut)
                                → database.cashbook_queries (get_pending_fees, get_total_fee_revenue — both Supabase)
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
                                  PostgreSQL — as of 2026-07-23, ADR-20, and as of 2026-07-24 (ADR-29) the only
                                  store; source of truth for index()/create()/renew(); also reads students
                                  there directly (Supabase, ADR-19) instead of the SQLite mirror)
                                → database.payment_queries.record_payment (added 2026-07-22, replacing a direct
                                  database.cashbook_queries.insert_income_entry call + an inline receipt-number
                                  formula duplicated across create()/renew()/payment.collect() - TD-22, ADR-13;
                                  as of 2026-07-24 (ADR-28), Supabase-only and strict - create()/renew()'s
                                  except clause is except APIError, wrapping only this call)
                                → database.membership_settings_queries.get_membership_settings (added 2026-07-21 - TD-7;
                                  Supabase as of 2026-07-24, ADR-24)
                                → database.membership_queries (get_effective_status, get_active_membership —
                                  now Supabase-backed since create() is its only caller, ADR-20 —
                                  get_plan_pricing, get_admission_fee - added 2026-07-21 - TD-6/TD-7)
                                (as of 2026-07-24, ADR-29: no database.db.get_connection dependency left at all -
                                  create()/renew()'s SQLite mirror-writes were removed outright)
routes/payment.py              → database.supabase_client.get_supabase_client   (memberships table, Supabase/
                                  PostgreSQL — as of 2026-07-23, ADR-21, and as of 2026-07-24 (ADR-29) the only
                                  store; source of truth for collect()'s paid_amount/pending_amount read+update;
                                  also reads students there directly (Supabase, ADR-19) to verify ownership)
                                → database.payment_queries.get_payments_for_admin (as of 2026-07-24, ADR-25 —
                                  index()'s Supabase payments/students read, replacing raw SQL)
                                → database.payment_queries.record_payment (added 2026-07-22 - see routes/membership.py
                                  note above, same fix; as of 2026-07-24 (ADR-28), Supabase-only and strict -
                                  collect()'s except clause is except APIError, wrapping only this call)
                                (as of 2026-07-24, ADR-29: no database.db.get_connection dependency left at all -
                                  collect()'s SQLite mirror-write was removed outright)
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
                                   get_top_expense_categories, get_action_items, get_business_timeline,
                                   get_purpose_breakdown — used by index()/purpose_analytics(); added
                                   2026-07-26, revenue_analytics() only: get_revenue_time_windows,
                                   get_monthly_fee_revenue, get_revenue_by_plan, get_revenue_by_payment_mode,
                                   get_payment_mode_usage_counts, get_new_vs_renewal_revenue,
                                   get_revenue_collection_summary, get_avg_revenue_per_student; added
                                   2026-07-26, occupancy_analytics() only: get_occupancy_summary,
                                   get_monthly_occupancy_trend, get_occupancy_by_purpose,
                                   get_occupancy_by_plan, get_purpose_shift_matrix, get_occupancy_insights)
routes/setting.py              → database.settings_queries (get/save/create/update/clear library settings —
                                  Supabase, ADR-24), database.receipt_settings_queries (Supabase, ADR-24),
                                  database.notification_settings_queries (Supabase, ADR-24)
                                → database.membership_settings_queries (get/save — Supabase, ADR-24)
                                → database.backup_queries (Supabase, ADR-24), database.security_settings_queries
                                  (Supabase, ADR-24)
                                → database.bi_queries.DEFAULT_SHIFT_CAPACITY (added 2026-07-26, ADR-38 —
                                  library_profile()'s seating-capacity fallback default)
                                → database.supabase_client.get_supabase_client (security_settings()'s password
                                  branch, admins table, ADR-17; backup_export_csv()'s students read, ADR-24; and
                                  as of 2026-07-25 (ADR-32) backup_create()'s per-admin export too, via the new
                                  _collect_admin_backup_data() helper — this file has zero SQLite dependency of
                                  any kind now, the last one in the app to reach that state)
routes/report.py               → (no DB access — pure redirect)
```

## `database/` internal dependencies

```
database/cashbook_queries.py   → database.supabase_client.get_supabase_client   (as of 2026-07-23, ADR-22 —
                                  cashbook table, source of truth for every read; as of 2026-07-24 (ADR-27),
                                  also the only store for every write — insert_transaction() strict (rolls
                                  back if audit_log fails), insert_income_entry() best-effort (id generation +
                                  both inserts wrapped in one try/except, see routes/membership.py's/
                                  routes/payment.py's cards for why it can't be strict); payment_id sent to
                                  Supabase as of ADR-25, closing TD-38's common case, best-effort — TD-41/TD-43)
                                → database.membership_queries.get_memberships_for_admin/get_admin_students
                                  (as of 2026-07-23/2026-07-24, ADR-23/ADR-25 — get_pending_fees() and the local
                                  _fetch_payments_for_admin() helper respectively, both Supabase)
                                (as of 2026-07-24, ADR-27: no database.db.get_connection dependency left at all
                                  — this module's last SQLite write, get_connection() for insert_transaction()/
                                  insert_income_entry()/update_manual_transaction(), was removed)
database/bi_queries.py         → database.cashbook_queries (get_monthly_income, get_monthly_expense,
                                   get_income_category_totals, get_expense_category_totals,
                                   get_pending_fees, get_total_fee_revenue, get_recent_transactions — all now
                                   Supabase-backed for the cashbook-table ones, as of ADR-22)
                                → database.membership_queries.get_memberships_for_admin/get_admin_students (as of
                                  2026-07-23, ADR-23 — replaces database.db.get_connection for its three
                                  membership-side functions; this module has no SQLite dependency left)
                                → database.payment_queries.get_payments_for_admin (added 2026-07-26,
                                  get_purpose_breakdown() and every Revenue Analytics helper — merges Students
                                  purpose with Payments amount_paid in Python, same shape
                                  get_memberships_for_admin() uses for its own Students join)
                                → database.membership_queries.get_effective_status, database.settings_queries.
                                  get_library_settings (added 2026-07-26, ADR-38 — every Occupancy Analytics
                                  helper: get_active_memberships() filters through get_effective_status(),
                                  get_shift_capacities() reads library_settings' *_capacity columns)
database/audit_queries.py      → database.supabase_client.get_supabase_client   (as of 2026-07-23, ADR-22 —
                                  audit_log table, source of truth for get_recent_audit_log(), its only
                                  function; log_entry() was deleted outright as of 2026-07-24, ADR-26 — this
                                  module has zero SQLite dependency now)
database/membership_settings_queries.py → database.supabase_client.get_supabase_client, database.settings_queries._now_iso
                                  (as of 2026-07-24, ADR-24 — no SQLite dependency left)
database/membership_queries.py → database.supabase_client.get_supabase_client only (as of 2026-07-23, ADR-23 —
                                  this module has no SQLite dependency left at all; get_membership_counts()
                                  moved to Supabase, joining get_active_membership() which already was, ADR-20)
database/payment_queries.py    → database.cashbook_queries.insert_income_entry (added 2026-07-22 - see TD-22, ADR-13)
                                → database.membership_queries.get_admin_students (added ADR-25 -
                                  get_payments_for_admin())
                                → database.supabase_client.get_supabase_client, postgrest.exceptions.APIError
                                  (ADR-24 for generate_receipt_number()'s library_settings read/advance - TD-40
                                  still open there; ADR-25/ADR-28 for get_payments_for_admin()'s read and
                                  record_payment()'s Supabase payments insert, strict as of ADR-28). As of
                                  2026-07-24 (ADR-28): zero SQLite dependency left at all -
                                  _receipt_number_taken()'s uniqueness check moved to Supabase too
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

## `utils/chart_data.py` — called by, not calling

```
routes/dashboard.py               → utils.chart_data.build_revenue_chart_data      (dashboard() + revenue_chart())
                                   → utils.chart_data.build_membership_chart_data
routes/membership_distribution.py → utils.chart_data.build_plan_distribution_chart_data   (fed the plan_counts dict)
tests/test_05_*.py               → utils.chart_data._monthly_revenue_for_year
```

Added 2026-08-28 (ADR-56), replacing the deleted `utils/charts.py` (matplotlib PNGs). Charts now render client-side with Chart.js. `build_revenue_chart_data`/`build_membership_chart_data` import `database.payment_queries.get_payments_for_admin` / `database.membership_queries.get_memberships_for_admin` (Supabase) and `utils.normalization.normalize_category`; `build_plan_distribution_chart_data` and `_monthly_revenue_for_year`/`_plan_counts` are pure functions of data passed in. No chart/plotting library, no `matplotlib`/`numpy`.

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
                                     + imports components/bi_components.html as bi (tabs() only, added 2026-07-25)

business_intelligence/{purpose_analytics, revenue_analytics, occupancy_analytics}.html
                                   imports components/bi_components.html as bi
                                     (tabs, analytics_header, kpi_card, chart_card, insight_card,
                                     analytics_table macros) — added 2026-07-25
                                   occupancy_analytics.html also includes components/bi_occupancy_insights.html
                                     with context (added 2026-07-26, ADR-38 — reads the parent template's
                                     `insights` variable without it being passed explicitly)

memberships/distribution.html includes components/membership_{summary_cards, distribution_chart,
                                     distribution_table, filters, quick_insights, progress}.html
```

If you rename or delete a component template, grep the relevant feature's `index.html` for `{% include` / `{% call` before assuming it's safe.
