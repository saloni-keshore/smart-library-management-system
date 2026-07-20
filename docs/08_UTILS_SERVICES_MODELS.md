# Utils, Services, Models — and the empty placeholder folders

## `utils/charts.py` — the only file in `utils/`

Uses **matplotlib** (`matplotlib.use("Agg")` for headless rendering) and **numpy** — not PIL, not Chart.js server-side. Imports `get_connection` directly from `database.db` and queries the DB itself (routes don't pass data in; they just call the generator function and then render a template that points at the resulting static PNG).

**Helpers:**
- `_smooth_curve(x, y, samples_per_segment=30)` — Catmull-Rom spline interpolation so the revenue line chart curves smoothly while still passing exactly through each real monthly data point.
- `_format_currency_short(value, _pos=None)` — matplotlib tick formatter producing compact ₹ labels (e.g. `₹12.5K`).

**Chart generators** (each takes only `admin_id`, runs its own SQL, writes a PNG, returns `None`):
| Function | Query | Output | Called from |
|---|---|---|---|
| `generate_revenue_chart(admin_id)` | `payments` join `students`, monthly `SUM(amount_paid)` | `static/charts/revenue.png` | `routes/dashboard.py` |
| `generate_membership_chart(admin_id)` | `memberships` join `students`, count by `plan_name` | `static/charts/membership.png` | `routes/dashboard.py` |
| `generate_membership_distribution_donut(admin_id)` | Same as above, larger chart with a fixed `PLAN_CHART_COLORS` map, center total-count label, "No membership data yet" empty state | `static/charts/membership_distribution_donut.png` | `routes/membership_distribution.py` |

**Important side effect to know before touching this file:** because these three functions overwrite the *same* filename every time regardless of which admin triggered them, and the resulting PNG is served as a shared static file to every admin's browser, one admin's chart data is briefly visible to another admin whose page happens to load in between generation and their own next page load. See [11_FUTURE_WORK.md](11_FUTURE_WORK.md).

## Empty placeholder folders

These exist in the repo but contain **zero files** (confirmed via directory listing, not just "no tracked files" — they're genuinely empty, nothing to migrate or reference):

| Folder | Apparent original intent (per old, now-removed planning docs) | Current reality |
|---|---|---|
| `models/` | ORM-style model classes (Student, Payment, Admin, Alert) | No ORM is used anywhere; all persistence is raw SQL via `database/*_queries.py` and `database/db.py`. Nothing to put here under the current architecture unless an ORM migration is planned. |
| `services/` | A business-logic layer separate from routes | Business logic currently lives directly in `routes/*.py` (validation, calculations) and `database/*_queries.py` (aggregation, e.g. `bi_queries.py`'s health-score math). No separate service layer exists. |
| `reports/` | Generated PDF/Excel/CSV report output | No report-generation code exists anywhere in the project (no ReportLab/openpyxl/pandas usage found; `requirements.txt` only has Flask/Werkzeug). `routes/report.py` is a pure redirect shim to Business Intelligence. |
| `tests/` | Unit/integration/DB tests | **No automated tests exist at all.** This is the most consequential empty folder — see [11_FUTURE_WORK.md](11_FUTURE_WORK.md). |
| `backups/` | Database backup scripts/output | No backup script exists; `database/library.db` has no automated backup mechanism. |
| `.agents/` | Unknown — not referenced by any old doc or code | No references found anywhere in the codebase. |

None of these are wired into `app.py`, imported by any route, or referenced by any template. They can be safely populated when the corresponding feature is actually built, or removed if the project decides not to pursue that direction — see [11_FUTURE_WORK.md](11_FUTURE_WORK.md) for the recommendation.
