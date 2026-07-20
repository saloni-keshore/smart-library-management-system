# Architecture Decisions

Record of deliberate architectural choices and the reasoning behind them, so future changes can be judged against the original intent rather than guessed at. Entries marked **(inferred)** are reconstructed from reading the code/git history, not from a first-hand statement — treat their "why" as a best-effort explanation, not a certainty.

Add a new entry whenever a change reflects a deliberate architectural choice (not just a bug fix) — see the maintenance policy in [README.md](README.md).

---

### ADR-1: Raw SQL via `sqlite3`, no ORM **(inferred)**

**Decision:** All persistence uses the stdlib `sqlite3` module directly (`database/db.py`'s `get_connection()`), with hand-written SQL in route functions and `database/*_queries.py` modules. No SQLAlchemy or other ORM.

**Why (inferred):** SQLite + raw SQL is the simplest thing that works for a single-file, single-server app at this scale, and avoids the setup overhead of an ORM for a project that started as a fast-moving single-developer build (see the "Day 1"/"Day 2" commit messages).

**Consequence:** `models/` and `services/` folders exist but are empty — there's no natural home for ORM model classes or a separate service layer under this architecture. See [08_UTILS_SERVICES_MODELS.md](08_UTILS_SERVICES_MODELS.md).

### ADR-2: `admin_id`-based multi-tenancy retrofitted, not designed in from day one

**Decision:** Tenant isolation is enforced by an `admin_id` column checked manually in each query, added via `database/migrate.py` (commit `90b65e3`, 2026-07-01) — after `enquiries`/`students` already existed without it.

**Why:** the git history shows this landed as a distinct retrofit commit after the initial buildout, not as part of the original schema design.

**Consequence:** isolation is inconsistent across tables — some (`enquiries`, `students`, `library_settings`, `membership_settings`) have a direct `admin_id` column with an FK; some (`cashbook`, `expenses`) have `admin_id` but no FK (added via `ALTER TABLE`, which SQLite can't constrain); `memberships` and `payments` have no `admin_id` at all and rely on a join back to `students`. There is no framework-level enforcement (e.g. row-level security) — a query that forgets the filter would leak cross-tenant data. See [04_DATABASE_SCHEMA.md](04_DATABASE_SCHEMA.md).

**How to apply:** any new admin-scoped table should follow the `enquiries`/`students` pattern (direct `admin_id` column + FK from table creation, not retrofitted later).

### ADR-3: Cashbook as the single source of truth for financial ledger, not `transactions`/`expenses`

**Decision:** All income/expense recording — both manual entries and automatic entries triggered by memberships/payments — flows through the `cashbook` table via `database/cashbook_queries.py`. The `expenses` and `transactions` tables defined in `schema.sql` are not used by any route.

**Why (inferred):** `cashbook` supports both manual and auto-generated entries with a `source` field distinguishing them, plus an audit trail (`audit_log`) — a more general design than the narrower `expenses`/`transactions` tables, which look like earlier or parallel attempts that were superseded once `cashbook` matured (commit `5b482dd`, 2026-07-05).

**Consequence:** `expenses` and `transactions` are dead schema — see [11_FUTURE_WORK.md](11_FUTURE_WORK.md) items 2–3 for the cleanup recommendation (reconcile or drop them so they don't confuse a future contributor into building against the wrong table).

### ADR-4: Auto-generated cashbook entries are read-only in the UI

**Decision:** `routes/cashbook.py`'s `edit_transaction()` explicitly refuses to edit any `cashbook` row whose `source != "Cashbook Manual Entry"`.

**Why (inferred):** rows created by `insert_income_entry()` (from membership/payment flows) are derived from — and must stay consistent with — their originating `payments`/`memberships` row. Allowing direct edits in the Cashbook UI would let the ledger drift out of sync with the record it was generated from.

**How to apply:** if you need to correct an auto-generated entry, fix it at the source (the membership/payment record), not in the Cashbook edit form. Any new auto-generating flow should set a `source` value other than `"Cashbook Manual Entry"` to get this protection automatically.

### ADR-5: Server-rendered matplotlib PNGs for Dashboard/Distribution charts, Chart.js for Cashbook/BI

**Decision:** Two different charting approaches coexist: `utils/charts.py` (matplotlib, server-side, writes a static PNG) for the Dashboard and Membership Distribution pages, versus client-side Chart.js fed by `window.cashbookChartData`/`window.biChartData` for Cashbook and Business Intelligence.

**Why (inferred):** the matplotlib charts (revenue line, membership pie/donut) predate the Chart.js-based pages chronologically (Dashboard/Distribution came earlier in the git history than Cashbook/BI), suggesting the project moved toward client-side interactive charts for newer features while leaving the original server-rendered ones in place rather than back-porting them.

**Consequence:** two genuinely different code paths to maintain, and the matplotlib path currently has the cross-tenant shared-filename issue described in [11_FUTURE_WORK.md](11_FUTURE_WORK.md) item 1 that the Chart.js path doesn't have (since Chart.js data is embedded per-request, not written to a shared file). If unifying charting approaches is ever on the table, Chart.js's per-request data model is the safer default to standardize on.

### ADR-6: No migrations framework — hand-written idempotent scripts instead

**Decision:** Schema changes are one-off Python scripts in `database/migrate_*.py`, each guarding itself with a `PRAGMA table_info` / `CREATE TABLE IF NOT EXISTS` check rather than using Alembic/Flask-Migrate with a version table.

**Why (inferred):** matches the project's overall lightweight, no-framework-beyond-Flask approach; for a single SQLite file with one active environment, a migrations framework's main benefit (coordinating schema state across many environments) doesn't yet apply.

**Consequence:** there's no single command to "bring the DB up to date" — someone has to know to run each new `migrate_*.py` script manually, in the right order, on the right machine. This has already produced one inconsistency (ADR-3's `transactions` table, defined differently in two places depending on which runs first). If the number of environments/deployments grows, revisit this.
