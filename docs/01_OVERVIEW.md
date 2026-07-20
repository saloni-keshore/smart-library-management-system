# Overview

## What this is

Smart Library App is a Flask web application for managing a coaching-center / reading-library business: student enquiries and admissions, membership plans and renewals, fee payments, a cashbook (income/expense ledger), and a business-intelligence dashboard on top of that financial data.

It is **multi-tenant**: every logged-in admin only ever sees their own data. Isolation is enforced by an `admin_id` column (directly or via join) on nearly every query — see [04_DATABASE_SCHEMA.md](04_DATABASE_SCHEMA.md).

## Tech stack (actual, as installed)

- **Backend:** Flask (`requirements.txt` pins only `Flask>=2.3.0` and `Werkzeug>=2.3.0`)
- **Database:** SQLite, single file at `database/library.db`, accessed with the stdlib `sqlite3` module (no ORM)
- **Templates:** Jinja2 (bundled with Flask)
- **Frontend:** Bootstrap 5.3.7 + Bootstrap Icons 1.11.3 (via CDN), Chart.js (client-side interactive charts), Google Fonts "Poppins"
- **Server-rendered charts:** `matplotlib` + `numpy` (used by `utils/charts.py` to render PNGs saved to `static/charts/`)

> **Known gap:** `matplotlib` and `numpy` are imported by `utils/charts.py` but are **not listed in `requirements.txt`**. A clean `pip install -r requirements.txt` will not have them, and the app will crash the first time a chart-generating route (dashboard, membership distribution) runs. See [11_FUTURE_WORK.md](11_FUTURE_WORK.md).

There is no ORM, no migrations framework (migrations are hand-written idempotent Python scripts, see [04_DATABASE_SCHEMA.md](04_DATABASE_SCHEMA.md)), no test suite (`tests/` is empty), and no build step for CSS/JS (plain hand-authored files served directly from `static/`).

## Running it locally

```
pip install -r requirements.txt
pip install matplotlib numpy   # required by utils/charts.py but missing from requirements.txt
python database/seed.py        # creates library.db from database/schema.sql if it doesn't exist
python app.py                  # runs with debug=True on the Flask default port (5000)
```

`app.py` hardcodes `debug=True` and does not read `config.py`'s `Config`/`DevelopmentConfig`/`ProductionConfig` classes at all — those exist but are dead code (see [02_ARCHITECTURE.md](02_ARCHITECTURE.md)).

## Multi-tenancy model

- One `admins` row = one tenant/owner of a library.
- Session holds `admin_id` and `username` after login (`routes/auth.py`).
- Every feature route checks `if "admin_id" not in session: return redirect("/")` before doing anything.
- Data isolation is enforced at the query level (`WHERE admin_id = ?` or a join back to a table that has `admin_id`), **not** by any framework-level tenancy mechanism. There is no row-level security — a query that forgets the `admin_id` filter would leak cross-tenant data. This is a manual convention, not something the framework guarantees.

## Feature areas (see [10_FEATURE_MODULES.md](10_FEATURE_MODULES.md) for full walkthroughs)

| Feature | Status |
|---|---|
| Auth (login/register/forgot password) | Implemented |
| Dashboard (KPIs, charts, quick actions) | Implemented |
| Enquiries | Implemented |
| Students / Admissions | Implemented |
| Memberships (create/renew) | Implemented |
| Membership Distribution (plan analytics) | Implemented |
| Membership Analytics (`/membership-analytics/`) | Route exists, renders a template shell with **no data** — effectively a stub |
| Payments (collect fee) | Implemented |
| Cashbook (ledger, manual entries, audit log) | Implemented |
| Business Intelligence (health score, growth, action items) | Implemented |
| Notifications (expiry buckets) | Implemented |
| Settings → Library Profile | Implemented |
| Settings → Membership Settings | Implemented |
| Settings → Receipt Settings | Implemented (configuration only — no PDF/print/email yet) |
| Settings → Notification Settings | Implemented (reminder-rule/channel/quiet-hours/dashboard-display preferences; `dash_show_pending_fees` and the navbar-bell toggles are wired, the rest are save-only — no SMS/Email/WhatsApp dispatch exists) |
| Settings → Staff & User Access | Placeholder ("Coming Soon" — still single-admin) |
| Settings → Data & Backup | Implemented (manual Export CSV / Create Backup only — no scheduled backups) |
| Settings → Security Settings | Implemented (password change is fully enforced; session timeout / remember-me / login-notification preferences are persisted but not enforced) |
| Reports (`/reports/`) | Deprecated redirect shim → Business Intelligence |
