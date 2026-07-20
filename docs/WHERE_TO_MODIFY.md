# Where to Modify X

Quick lookup: find the feature you want to change, get every file it touches. For deeper detail on any file, jump to its card in [FILE_REFERENCE.md](FILE_REFERENCE.md).

| Feature | Route(s) | Data access | Templates | Static | Table(s) |
|---|---|---|---|---|---|
| **Login / Register / Forgot Password** | `routes/auth.py` | raw SQL on `admins` | `templates/auth/*.html` (extends `auth_base.html`) | `css/login.css`, `js/login.js` | `admins` |
| **Dashboard (KPIs, quick actions)** | `routes/dashboard.py` | raw SQL + `utils/charts.py` (`generate_revenue_chart`, `generate_membership_chart`) | `templates/dashboard/index.html` + `components/{dashboard_header,quick_actions,revenue_chart,membership_chart,expiry_table,recent_admissions,*_modal}.html` | `js/dashboard-charts.js`, `js/transaction_modal.js` | `students`, `memberships`, `payments`, `enquiries` |
| **Enquiries** | `routes/enquiries.py` | raw SQL | `templates/enquiries/*.html` | — | `enquiries` |
| **Students / Admissions** | `routes/student.py` | raw SQL | `templates/students/*.html` | — | `students`, `enquiries`, `memberships`, `payments` |
| **Memberships (create/renew)** | `routes/membership.py` | raw SQL + `database/cashbook_queries.py` (`insert_income_entry`) | `templates/memberships/{index,create,renew}.html` | — | `memberships`, `payments`, `cashbook`, `audit_log` |
| **Membership Distribution (plan analytics)** | `routes/membership_distribution.py` | raw SQL + `utils/charts.py` (`generate_membership_distribution_donut`) | `templates/memberships/distribution.html` + `components/membership_*.html` | `css/membership_distribution.css`, `js/membership_distribution.js` | `memberships`, `students`, `payments` |
| **Membership Analytics** *(stub — no data wired yet)* | `routes/membership_analytics.py` | none | `templates/memberships/analytics.html` | — | — |
| **Payments (collect fee)** | `routes/payment.py` | raw SQL + `database/cashbook_queries.py` (`insert_income_entry`) | `templates/payments/{index,collect}.html` | — | `payments`, `memberships`, `cashbook`, `audit_log` |
| **Cashbook (ledger, manual entries, audit log)** | `routes/cashbook.py` | `database/cashbook_queries.py`, `database/audit_queries.py`, `database/cashbook_categories.py` | `templates/cashbook/index.html` + `components/cashbook_*.html` | `css/cashbook.css`, `js/cashbook.js`, `js/transaction_modal.js` | `cashbook`, `audit_log` |
| **Business Intelligence (health score, growth, action items)** | `routes/business_intelligence.py` | `database/bi_queries.py`, `database/cashbook_queries.py` | `templates/business_intelligence/index.html` + `components/bi_*.html` | `css/business_intelligence.css`, `js/business_intelligence.js` | `cashbook`, `memberships`, `students` |
| **Notifications (expiry buckets + navbar bell)** | `routes/notification.py` (`index()` for the page, `get_notification_summary()` for the navbar bell via `app.py`'s context processor) | raw SQL | `templates/notification/index.html`, `components/notification_dropdown.html` | — | `memberships`, `students` |
| **Settings → Library Profile** | `routes/setting.py` (`library_profile`, `remove_library_logo`) | `database/settings_queries.py` | `templates/settings/library_profile.html` | `css/settings.css`, `js/settings.js` | `library_settings` |
| **Settings → Membership Settings (plan pricing/policy)** | `routes/setting.py` (`membership_settings`) | `database/membership_settings_queries.py` | `templates/settings/membership_settings.html` | — | `membership_settings` — **note:** not yet read by the Membership create/renew flow, see [11_FUTURE_WORK.md](11_FUTURE_WORK.md) TD-7 |
| **Settings → Receipt Settings** *(stub)* | `routes/setting.py` (`receipt_settings`) | none yet | none yet — build from scratch | — | — |
| **Settings → Notification Settings** *(stub)* | `routes/setting.py` (`notification_settings`) | none yet | none yet — build from scratch | — | — |
| **Reports** | `routes/report.py` — permanent redirect shim | — | `templates/reports/index.html` exists but is dead | — | — |
| **Receipt numbering** | Inline in `routes/membership.py` (`create`/`renew`) and `routes/payment.py` (`collect`) — **not centralized**, format duplicated in both places (`REC-YYYYMMDD-...`) | — | — | — | `payments.receipt_number` |
| **Auth/session guard pattern** | Copy-pasted `if "admin_id" not in session: return redirect("/")` at the top of nearly every route function — no decorator or `before_request` hook exists yet | — | — | — | — |
| **Colors / design tokens** | — | — | — | `css/style.css` (`.sidebar-wrapper` vars), `css/business_intelligence.css` (`--bi-*`), `css/membership_distribution.css` (`--md-*`) — each page redefines its own tokens, not a single shared file | — | — |
| **Database schema changes** | — | `database/schema.sql` (fresh installs) **+** a new `database/migrate_*.py` script (existing installs) — there's no migration runner, both must be updated together | — | — | update [04_DATABASE_SCHEMA.md](04_DATABASE_SCHEMA.md) in the same change |

## If your change doesn't fit neatly into one row above

- Check [FILE_REFERENCE.md](FILE_REFERENCE.md) for the specific file's full dependency card (what it depends on, what depends on it) before editing.
- Check [09_DEPENDENCY_MAP.md](09_DEPENDENCY_MAP.md) for cross-blueprint `url_for` couplings that won't show up as Python imports.
- Check [11_FUTURE_WORK.md](11_FUTURE_WORK.md) — your change might already be a known, tracked issue.
