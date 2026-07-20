# Project Structure — Annotated File Reference

This is the **actual** current tree (as opposed to an aspirational one). Every folder and file that exists in the repo is listed with a one-line purpose. Use this as the fastest way to answer "where is X implemented?" — for deeper detail follow the link in the "Details" column.

## Root

| Path | Purpose | Details |
|---|---|---|
| `app.py` | Flask app factory, blueprint registration, entry point | [02_ARCHITECTURE.md](02_ARCHITECTURE.md) |
| `config.py` | Unused config classes (dead code, not imported by `app.py`) | [02_ARCHITECTURE.md](02_ARCHITECTURE.md) |
| `requirements.txt` | Python deps — currently only `Flask`, `Werkzeug` (missing `matplotlib`/`numpy`, see [11_FUTURE_WORK.md](11_FUTURE_WORK.md)) | |
| `README.md` | **Empty (0 bytes)** — no project-level README exists | [11_FUTURE_WORK.md](11_FUTURE_WORK.md) |
| `.claude/` | Claude Code local settings (`settings.local.json`) | |
| `.agents/` | Empty directory, no files | [08_UTILS_SERVICES_MODELS.md](08_UTILS_SERVICES_MODELS.md) |
| `backups/` | Empty directory, no files | [08_UTILS_SERVICES_MODELS.md](08_UTILS_SERVICES_MODELS.md) |
| `models/` | Empty directory, no files (no ORM model classes exist anywhere in the project) | [08_UTILS_SERVICES_MODELS.md](08_UTILS_SERVICES_MODELS.md) |
| `reports/` | Empty directory, no files | [08_UTILS_SERVICES_MODELS.md](08_UTILS_SERVICES_MODELS.md) |
| `services/` | Empty directory, no files (no service layer exists; business logic lives directly in `routes/*.py` and `database/*_queries.py`) | [08_UTILS_SERVICES_MODELS.md](08_UTILS_SERVICES_MODELS.md) |
| `tests/` | Empty directory, no files — **there is no automated test coverage** | [11_FUTURE_WORK.md](11_FUTURE_WORK.md) |

## `database/`

| Path | Purpose |
|---|---|
| `db.py` | `get_connection()` — the single shared SQLite connection factory |
| `schema.sql` | Full DDL for every table (source of truth for a from-scratch DB) |
| `seed.py` | Despite the name, does **not** insert sample data — runs `schema.sql` via `executescript()` to (re)create tables |
| `migrate.py` | Multi-tenant retrofit: adds `admin_id` to `enquiries`/`students` |
| `migrate_audit_log.py` | Creates `audit_log` table |
| `migrate_transactions.py` | Creates a `transactions` table (⚠ shape differs from the one also defined in `schema.sql` — see [04_DATABASE_SCHEMA.md](04_DATABASE_SCHEMA.md)) |
| `migrate_cashbook_ledger.py` | Adds `cashbook.reference_id` and `cashbook.source` columns |
| `migrate_backfill_cashbook_payments.py` | One-off data backfill: creates missing `cashbook` rows for historical `payments` |
| `migrate_library_settings.py` | Creates `library_settings` table |
| `migrate_settings_receipt_footer.py` | Adds `library_settings.receipt_footer` column |
| `migrate_membership_setting.py` | Creates `membership_settings` table, with a schema-compatibility guard |
| `audit_queries.py` | Read/write access to `audit_log` |
| `bi_queries.py` | Business-intelligence aggregates (health score, growth, top categories, action items, timeline) |
| `cashbook_categories.py` | Static category/payment-method constant lists (no DB access) |
| `cashbook_queries.py` | Core cashbook ledger data-access layer (largest query module, 20 functions) |
| `membership_settings_queries.py` | Get/upsert per-admin membership plan pricing settings |
| `settings_queries.py` | Get/create/update per-admin library profile settings |
| `library.db` | The actual SQLite database file |
| `__pycache__/` | Compiled bytecode — **tracked in git** (see [11_FUTURE_WORK.md](11_FUTURE_WORK.md)) |

Full column-level schema: [04_DATABASE_SCHEMA.md](04_DATABASE_SCHEMA.md). Function-level detail: [09_DEPENDENCY_MAP.md](09_DEPENDENCY_MAP.md).

## `routes/` (13 blueprint modules)

| Path | Blueprint | Prefix |
|---|---|---|
| `auth.py` | `auth` | none (root: `/`, `/logout`, `/register`, `/forgot-password`) |
| `dashboard.py` | `dashboard` | none (`/dashboard`) |
| `enquiries.py` | `enquiry` | `/enquiries` |
| `student.py` | `student` | `/students` |
| `membership.py` | `membership` | `/memberships` |
| `membership_analytics.py` | `membership_analytics` | `/membership-analytics` |
| `membership_distribution.py` | `membership_distribution` | `/membership-distribution` |
| `payment.py` | `payment` | `/payments` |
| `cashbook.py` | `cashbook` | `/cashbook` |
| `business_intelligence.py` | `business_intelligence` | `/business-intelligence` |
| `notification.py` | `notification` | `/notifications` |
| `setting.py` | `setting` | `/settings` |
| `report.py` | `report` | `/reports` (deprecated redirect shim → business_intelligence) |

Full route-by-route detail: [05_ROUTES_REFERENCE.md](05_ROUTES_REFERENCE.md).

## `templates/`

| Path | Purpose |
|---|---|
| `layouts/base.html` | Main authenticated-app shell (navbar + sidebar + content block) |
| `layouts/auth_base.html` | Minimal shell for login/register/forgot-password pages |
| `layouts/navbar.html` | Top navbar include |
| `layouts/sidebar.html` | Left nav include, badge counts, active-link highlighting |
| `components/` (~45 files) | Shared/reusable partials — cards, charts, filters, modals, feature-specific widgets |
| `auth/` | login, register, forgot_password |
| `dashboard/index.html` | Main dashboard page |
| `enquiries/` | index, add, edit, view |
| `students/` | index, admission, view, edit |
| `memberships/` | index, create, renew, distribution, analytics |
| `payments/` | index, collect, create, success |
| `cashbook/` | index, transactions, analytics |
| `business_intelligence/index.html` | BI dashboard |
| `notification/index.html` | Expiry notification buckets |
| `settings/` | index, library_profile, membership_settings |
| `reports/index.html` | Unused leftover — `routes/report.py` never renders it (permanent redirect instead) |

Full breakdown: [06_TEMPLATES_REFERENCE.md](06_TEMPLATES_REFERENCE.md).

## `static/`

| Path | Purpose |
|---|---|
| `css/style.css` | Main global stylesheet (sidebar theme vars, layout, base component styles) |
| `css/business_intelligence.css`, `css/cashbook.css`, `css/membership_distribution.css`, `css/settings.css`, `css/login.css` | Page-specific stylesheets, each with their own `:root` design-token variables |
| `js/*.js` (7 files) | Per-page Chart.js wiring, dashboard skeleton loaders, login toggle, settings form + transaction modal logic |
| `charts/` | 3 server-generated PNGs (`revenue.png`, `membership.png`, `membership_distribution_donut.png`), overwritten in place by `utils/charts.py` |
| `uploads/settings/` | Per-admin uploaded branding assets (logo/stamp/signature), named `{type}_{admin_id}_{filename}` |
| `images/` | Empty directory, no files |

Full breakdown: [07_STATIC_ASSETS.md](07_STATIC_ASSETS.md).

## `utils/`

| Path | Purpose |
|---|---|
| `charts.py` | Server-side matplotlib chart generation (revenue line chart, membership pie chart, membership distribution donut) |

Detail: [08_UTILS_SERVICES_MODELS.md](08_UTILS_SERVICES_MODELS.md).

## `docs/`

This documentation system. See [README.md](README.md) for the index.
