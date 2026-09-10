# Utils, Services, Models — and the empty placeholder folders

## `utils/`

Three files: `chart_data.py`, `normalization.py`, `security.py`.

### `utils/chart_data.py` — Chart.js payload builders

Added 2026-08-28 (ADR-56), replacing the deleted `utils/charts.py` (which used **matplotlib** + **numpy** to write PNGs into `static/charts/`). Those two packages, and the whole matplotlib transitive stack, were removed from `requirements.txt` — nothing else imported them — so the app installs lean and runs on a read-only serverless filesystem (Vercel). All charts render client-side with Chart.js now, the same way the Business Intelligence and Cashbook pages already did.

Every function returns a plain `{labels, datasets}` dict; no plotting library, no disk I/O.

| Function | Reads | Returned to | Rendered by |
|---|---|---|---|
| `build_revenue_chart_data(admin_id, period="this_year")` | `database.payment_queries.get_payments_for_admin` → `_monthly_revenue_for_year(payments, year)` (filtered to `this_year`/`last_year`) | `routes/dashboard.py` `dashboard()` (initial) + `revenue_chart()` (period switch, as JSON) | `static/js/dashboard-charts.js` → `#revenue-chart-canvas` (line) |
| `build_membership_chart_data(admin_id)` | `database.membership_queries.get_memberships_for_admin`, grouped by `normalize_category(plan_name)`, ranked by count | `routes/dashboard.py` `dashboard()` | `dashboard-charts.js` → `#membership-chart-canvas` (doughnut) |
| `build_plan_distribution_chart_data(plan_counts)` | the `plan_counts` dict `routes/membership_distribution.py` already computes (zero-count plans dropped) | `routes/membership_distribution.py` `index()` | `dashboard-charts.js` → `#distribution-donut-canvas` (doughnut) |

Constants: `MONTHS`, `REVENUE_LINE_COLOR`/`REVENUE_FILL_COLOR`, `PLAN_CHART_COLORS` (keys UPPERCASE, matching `normalize_category`), `PLAN_CHART_FALLBACK_COLOR`; helper `plan_color(label)` normalizes any-casing labels before the colour lookup. Empty `labels` from `build_membership_chart_data`/`build_plan_distribution_chart_data` tells the JS to render a "No membership data yet" placeholder.

### `utils/normalization.py`

Shared input-normalization helpers (Category → UPPERCASE, Name/Location → Title Case, free-text/phone → trim only) — see ADR-36 and this file's card in [FILE_REFERENCE.md](FILE_REFERENCE.md).

### `utils/security.py`

CSRF token generation/validation and the in-process login/forgot-password rate limiter — see [FILE_REFERENCE.md](FILE_REFERENCE.md).

## Empty / near-empty placeholder folders

| Folder | Apparent original intent | Current reality |
|---|---|---|
| `models/` | ORM-style model classes | No ORM anywhere; persistence is `database/*_queries.py` + inline `database/supabase_client.py` (PostgREST). Nothing to put here. |
| `services/` | A business-logic layer separate from routes | Business logic lives in `routes/*.py` and `database/*_queries.py`. No service layer exists. |
| `reports/` | Generated PDF/Excel/CSV report output | No report-generation code exists (no ReportLab/openpyxl/pandas). `routes/report.py` is a redirect shim to Business Intelligence. |
| `backups/` | Database backup output | Holds runtime-generated per-admin JSON exports only (gitignored); `routes/setting.py`'s `backup_create()` streams from memory now (ADR-56) and no longer writes here. |
| `.agents/` | Unknown | Not referenced anywhere. |

`tests/` is **not** empty — it holds a full pytest suite (`tests/conftest.py` + `tests/test_00..17_*.py`, 500+ tests) run against a real Supabase project, added in the 2026-07-22 QA sprint (TD-20 Resolved). **As of 2026-09-09 (ADR-69):** `conftest.py` calls `load_dotenv(<repo root>/.env.test, override=True)` before importing `app` — so when a git-ignored `.env.test` exists, the suite binds to a dedicated throwaway project instead of whatever `.env` (the shared local/deploy project) points at; with no `.env.test` it falls back to `.env`. There is still no mocking or teardown — the suite creates real rows, which is why it must not run against a project anyone cares about (`scripts/verify_schema.py` is the read-only alternative for checking a real project).
