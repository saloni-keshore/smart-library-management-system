# Changelog

Every coding session that changes behavior gets a new entry at the top, using this template:

```markdown
## YYYY-MM-DD — <short title>

- **Feature:** what capability this is part of
- **Files changed:** exact paths (not "various files") — code, templates, static, migrations
- **Why:** the actual motivation — a bug report, a design decision, a dependency, not just "improvement"
- **Database changes:** new/altered tables or columns, and which `migrate_*.py` script (if any) applies it to existing installs; "None" if not applicable
- **UI changes:** what a user visibly sees differently; "None" if not applicable
- **Future impact:** what this unblocks, what it constrains, what it leaves as debt — cross-link a [11_FUTURE_WORK.md](11_FUTURE_WORK.md) `TD-N`/`PF-N` id if this created or resolved one
```

Entries before 2026-07-20 are reconstructed from `git log` since no changelog existed at the time — fields marked *"Not recorded (predates changelog)"* genuinely can't be reconstructed with confidence; don't guess at them.

---

## 2026-07-20 — Documentation system replaced and expanded

- **Feature:** Project documentation (`docs/`)
- **Files changed:** Removed all 20 old files (`docs/01_Requirement_Analysis.md` through `docs/20_Normalization.md`). Added `docs/README.md`, `01_OVERVIEW.md`–`11_FUTURE_WORK.md`, `FILE_REFERENCE.md`, `DIAGRAMS.md`, `CODE_JOURNEY.md`, `WHERE_TO_MODIFY.md`, `TROUBLESHOOTING.md`, `CHANGELOG.md`, `DECISIONS.md`. Added root `CLAUDE.md`.
- **Why:** the old docs described a project that didn't match reality (referenced a non-existent `ml/` folder, MySQL, Scikit-learn, ReportLab — none used anywhere; actual stack is Flask + SQLite + Jinja2 + Bootstrap + Chart.js + matplotlib) and were never updated as the app evolved. Replaced with a reference set verified against the actual source, then expanded per a follow-up request to add per-file dependency cards, Mermaid diagrams, a request-flow walkthrough, a "where to modify X" lookup, a troubleshooting guide, and a living technical-debt log.
- **Database changes:** None — documentation only.
- **UI changes:** None.
- **Future impact:** established the doc-maintenance policy now recorded in `CLAUDE.md` (every code change updates docs + this changelog in the same session) and a living `TD-N` technical-debt log in [11_FUTURE_WORK.md](11_FUTURE_WORK.md) (21 items opened from this pass, see that file). No code changed in this session — the debt items are documented, not yet fixed.

## 2026-07-20 — Membership Settings feature (commit `ef688b9`)

- **Feature:** Settings → Membership Settings
- **Files changed:** `database/membership_settings_queries.py` (new), `templates/settings/membership_settings.html` (new), `database/migrate_membership_setting.py`, `database/schema.sql`, `routes/setting.py`, `templates/settings/index.html`
- **Why:** first step toward making plan fees/durations configurable per library instead of hardcoded, ahead of wiring it into the actual membership create/renew flow.
- **Database changes:** added `membership_settings` table (one row per admin; monthly/quarterly/half-yearly/yearly fee+days, admission fee, late fee, renewal grace days, auto-expiry/early-renewal/reminder flags, reminder days) via `database/migrate_membership_setting.py` for existing installs, and directly in `database/schema.sql` for fresh ones.
- **UI changes:** Settings landing page's "Membership Settings" and "Receipt Settings" cards changed from disabled "Coming soon" placeholders to a live link (Membership Settings) and a stub link (Receipt Settings); added the Membership Settings form page with a "what changed" diff banner shown after saving.
- **Future impact:** opened [11_FUTURE_WORK.md](11_FUTURE_WORK.md) TD-7 — `routes/membership.py`'s `create()`/`renew()` do not yet read from this table, so configuring it currently has no effect on actual membership creation.

## 2026-07-06 — Refactor (commit `62bb7b0`)

- **Feature:** Codebase-wide
- **Files changed:** Not recorded (predates changelog) — see `git show 62bb7b0` for the diff.
- **Why:** commit message states "Refactor code structure for improved readability and maintainability"; no further detail recorded.
- **Database changes:** Not recorded (predates changelog).
- **UI changes:** Not recorded (predates changelog).
- **Future impact:** Not recorded (predates changelog).

## 2026-07-06 — Settings uploads scaffolding (commit `fdcb80c`)

- **Feature:** Settings → Library Profile (uploads)
- **Files changed:** `static/uploads/settings/.gitkeep`
- **Why:** track the (then-empty) upload directory in git ahead of the Library Profile logo/stamp/signature upload feature.
- **Database changes:** None.
- **UI changes:** None.
- **Future impact:** enabled `routes/setting.py`'s `_save_upload()` to have a tracked destination directory.

## 2026-07-05 — Cashbook analytics and transaction management (commit `5b482dd`)

- **Feature:** Cashbook
- **Files changed:** `database/cashbook_queries.py` (new), `database/audit_queries.py` (new), `database/cashbook_categories.py` (new), `routes/cashbook.py`, `templates/cashbook/*`, `templates/components/cashbook_*.html`
- **Why:** build out a full manual ledger with filtering/search/pagination, category/payment-method breakdowns, and an audit trail for changes.
- **Database changes:** established `cashbook` as the central ledger table (extending the base table from `schema.sql` with `category`/`person`/`admin_id`/`payment_method` via earlier `ALTER TABLE`s) and added `audit_log` (`database/migrate_audit_log.py`).
- **UI changes:** new Cashbook page with summary cards, filters, charts, transaction list, and activity/audit log.
- **Future impact:** established ADR-3 and ADR-4 (see [DECISIONS.md](DECISIONS.md)) — Cashbook as the single source of truth for the ledger, and auto-generated entries being read-only in the UI.

## 2026-07-03 to 2026-07-04 — Membership Distribution feature (commits `583931f`, `d67daa5`)

- **Feature:** Membership Distribution
- **Files changed:** `routes/membership_distribution.py` (new), `utils/charts.py` (`generate_membership_distribution_donut` added), `templates/memberships/distribution.html` (new), `templates/components/membership_*.html` (new)
- **Why:** give admins a plan-distribution analytics view (counts/percentages per plan, active/expired totals, quick insights).
- **Database changes:** None (reads existing `memberships`/`students`/`payments`).
- **UI changes:** new Membership Distribution page, linked from the Dashboard's membership chart card.
- **Future impact:** established the server-rendered matplotlib chart pattern (ADR-5 in [DECISIONS.md](DECISIONS.md)) that later coexisted with the client-side Chart.js approach used by Cashbook/BI.

## 2026-07-02 — Dashboard UI enhancements (commit `c807844`)

- **Feature:** Dashboard
- **Files changed:** Not recorded in detail (predates changelog) — commit message: "Enhance dashboard UI with new components and improved styles."
- **Why:** Not recorded (predates changelog).
- **Database changes:** None recorded.
- **UI changes:** Dashboard visual/component improvements (exact scope not recorded).
- **Future impact:** Not recorded (predates changelog).

## 2026-07-01 — Multi-tenant `admin_id` isolation (commit `90b65e3`)

- **Feature:** Core architecture (multi-tenancy)
- **Files changed:** `database/migrate.py` (new), `database/schema.sql`, plus routes/templates touching `enquiries`/`students` (not individually recorded)
- **Why:** retrofit per-admin data isolation onto what was previously a single-tenant app.
- **Database changes:** added `admin_id` to `enquiries`; recreated `students` with `admin_id` + `UNIQUE(mobile, admin_id)`, backfilling existing rows to the first admin found.
- **UI changes:** None directly (backend isolation change).
- **Future impact:** established ADR-2 (see [DECISIONS.md](DECISIONS.md)) — the manual, per-query `admin_id` filtering convention that every feature built afterward depends on, and the inconsistency it left behind (some tables retrofitted without FK support — TD-2/TD-3/TD-5 in [11_FUTURE_WORK.md](11_FUTURE_WORK.md)).

## 2026-06-30 — V1 buildout and config management (commits `d13f945`, `615df85`)

- **Feature:** Core architecture, Membership, Payment
- **Files changed:** `config.py` (new, subsequently never wired into `app.py`), membership/payment routes and templates (not individually recorded)
- **Why:** initial working version ("bulding V1").
- **Database changes:** Not recorded in detail (predates changelog).
- **UI changes:** Not recorded in detail (predates changelog).
- **Future impact:** `config.py` became dead code (TD-9 in [11_FUTURE_WORK.md](11_FUTURE_WORK.md)) — never revisited after this commit.

## 2026-06-28 — Initial project setup (commits `1404bcb`, `f4d72f4`)

- **Feature:** Core architecture
- **Files changed:** `app.py`, initial `database/` module (not individually recorded)
- **Why:** Day 1/Day 2 project scaffold.
- **Database changes:** Initial schema (exact original shape not recorded — `schema.sql` has since evolved through 6 commits, see [04_DATABASE_SCHEMA.md](04_DATABASE_SCHEMA.md)).
- **UI changes:** Not recorded (predates changelog).
- **Future impact:** established the Flask-factory + blueprint-registration pattern (`app.py`) still in use today.
