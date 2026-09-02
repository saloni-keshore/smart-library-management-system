# Project Structure — Annotated File Reference

This is the **actual** current tree (as opposed to an aspirational one). Every folder and file that exists in the repo is listed with a one-line purpose. Use this as the fastest way to answer "where is X implemented?" — for deeper detail follow the link in the "Details" column.

## Root

| Path | Purpose | Details |
|---|---|---|
| `app.py` | Flask app factory, blueprint registration, entry point | [02_ARCHITECTURE.md](02_ARCHITECTURE.md) |
| `config.py` | Env-driven config classes used by `app.py`; also the app's `load_dotenv()` call site | [02_ARCHITECTURE.md](02_ARCHITECTURE.md) |
| `requirements.txt` | Pinned Python deps (`==` versions) — Flask/Werkzeug/Jinja, `supabase` + its stack, `waitress`, `python-dotenv`, `cryptography`, `pytest`. Must be UTF-8. No `matplotlib`/`numpy` since 2026-08-28 (ADR-56 — charts are client-side now) | |
| `vercel.json` / `api/index.py` / `.vercelignore` | Vercel serverless deploy config (secondary/testing host alongside Render) — see [DEPLOYMENT.md](DEPLOYMENT.md) | |
| `README.md` | **Empty (0 bytes)** — no project-level README exists | [11_FUTURE_WORK.md](11_FUTURE_WORK.md) |
| `.claude/` | Claude Code local settings (`settings.local.json`) | |
| `.agents/` | Empty directory, no files | [08_UTILS_SERVICES_MODELS.md](08_UTILS_SERVICES_MODELS.md) |
| `backups/` | Previously empty; as of 2026-07-21 holds manual backups written by `routes/setting.py`'s `backup_create()` (Settings → Data & Backup), named `library_backup_<admin_id>_<timestamp>.json` as of 2026-07-25 (ADR-32 — was `.db`, a whole-file SQLite copy, before SQLite was removed) | [10_FEATURE_MODULES.md](10_FEATURE_MODULES.md) |
| `models/` | Empty directory, no files (no ORM model classes exist anywhere in the project) | [08_UTILS_SERVICES_MODELS.md](08_UTILS_SERVICES_MODELS.md) |
| `reports/` | Empty directory, no files | [08_UTILS_SERVICES_MODELS.md](08_UTILS_SERVICES_MODELS.md) |
| `services/` | Empty directory, no files (no service layer exists; business logic lives directly in `routes/*.py` and `database/*_queries.py`) | [08_UTILS_SERVICES_MODELS.md](08_UTILS_SERVICES_MODELS.md) |
| `tests/` | Empty directory, no files — **there is no automated test coverage** | [11_FUTURE_WORK.md](11_FUTURE_WORK.md) |

## `database/`

| Path | Purpose |
|---|---|
| `supabase_client.py` | `get_supabase_client()` — the single shared Supabase (PostgREST) client factory; as of 2026-07-25 (ADR-32) the app's **only** database access layer — `database/db.py` (the old SQLite connection factory), `database/schema.sql`, `database/seed.py`, `database/init_db.py`, and every `database/migrate_*.py` script were deleted outright once SQLite was removed entirely (see [DECISIONS.md](DECISIONS.md)) |
| `supabase_migration.sql` | Full DDL for every table — the single, sole source of truth for the schema as of ADR-32 (previously paired with `schema.sql`, which no longer exists) |
| `audit_queries.py` | Read access to Supabase `audit_log` (`get_recent_audit_log`) — no SQLite mirror-write left as of ADR-26; `database/cashbook_queries.py` writes Supabase `audit_log` rows directly |
| `bi_queries.py` | Business-intelligence aggregates (health score, growth, top categories, action items, timeline) |
| `cashbook_categories.py` | Static category/payment-method constant lists (no DB access) |
| `cashbook_queries.py` | Core cashbook ledger data-access layer (largest query module, 20 functions) |
| `membership_settings_queries.py` | Get/upsert per-admin membership plan pricing + extra-charge settings (ADR-66) |
| `membership_charges_queries.py` | Extra-charge catalog (`CHARGE_CATALOG`) + per-membership `membership_charges` rows (ADR-66) |
| `shift_slots_queries.py` | CRUD for per-admin time-window shift slots (`shift_slots`, ADR-65) |
| `settings_queries.py` | Get/create/update per-admin library profile settings |
| `receipt_settings_queries.py` | Get/update per-admin receipt numbering/branding/printing settings (same `library_settings` row) |
| `notification_settings_queries.py` | Get/update per-admin reminder/channel/quiet-hours/dashboard-display settings (same `library_settings` row) |
| `backup_queries.py` | Get/record per-admin manual backup info (`backup_log` table) |
| `security_settings_queries.py` | Get/upsert per-admin session/security preferences (`security_settings` table) |
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
| `settings/` | index (7 cards), library_profile, membership_settings, receipt_settings, notification_settings, staff_access, data_backup, security_settings — every Settings sub-page now has a real template |
| `reports/index.html` | Unused leftover — `routes/report.py` never renders it (permanent redirect instead) |

Full breakdown: [06_TEMPLATES_REFERENCE.md](06_TEMPLATES_REFERENCE.md).

## `static/`

| Path | Purpose |
|---|---|
| `css/style.css` | Main global stylesheet (sidebar theme vars, layout, base component styles) |
| `css/business_intelligence.css`, `css/cashbook.css`, `css/membership_distribution.css`, `css/settings.css`, `css/login.css` | Page-specific stylesheets, each with their own `:root` design-token variables |
| `js/*.js` | Per-page Chart.js wiring (incl. `dashboard-charts.js`, which renders the Dashboard/Distribution charts), skeleton loaders, login toggle, settings form + transaction modal logic |
| `uploads/settings/` | **Legacy (ADR-57).** Branding images (logo/stamp/signature) now upload to a public Supabase Storage bucket (`library-branding`) via `database/branding_storage.py`; `library_settings.*_path` holds the full URL. Any files left here are pre-migration and still resolve via `utils/branding.py`'s `branding_src()` |
| `images/` | Empty directory, no files |

Full breakdown: [07_STATIC_ASSETS.md](07_STATIC_ASSETS.md).

## `utils/`

| Path | Purpose |
|---|---|
| `chart_data.py` | Chart.js `{labels, datasets}` builders for the Dashboard/Distribution charts (`build_revenue_chart_data`, `build_membership_chart_data`, `build_plan_distribution_chart_data`) — replaced the matplotlib `charts.py` on 2026-08-28 (ADR-56); rendering is client-side now |
| `normalization.py` | Shared input-normalization helpers (see ADR-36) |

Detail: [08_UTILS_SERVICES_MODELS.md](08_UTILS_SERVICES_MODELS.md).

## `docs/`

This documentation system. See [README.md](README.md) for the index.
