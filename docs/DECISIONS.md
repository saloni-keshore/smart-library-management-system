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

### ADR-7: Receipt Settings extends the `library_settings` row instead of a new table, update-only

**Decision:** Receipt numbering/branding/printing preferences (`receipt_prefix`, `next_receipt_number`, `paper_size`, etc.) were added as columns on the existing `library_settings` table rather than a new `receipt_settings` table, and `database/receipt_settings_queries.py`'s `save_receipt_settings()` only supports `UPDATE` — there is no insert/upsert path. `routes/setting.py`'s `receipt_settings()` redirects to `library_profile` if no row exists yet.

**Why:** every receipt setting is inherently tied to one library profile (one row per `admin_id` already existed, one-to-one), and the page reuses that row's `logo_path`/`stamp_path`/`signature_path`/`receipt_footer` directly for its branding preview — splitting it into a second table would mean joining back to `library_settings` on every read for no isolation benefit. Requiring the profile to exist first (rather than allowing an insert with `NULL` `library_name`) avoids violating that column's `NOT NULL` constraint and keeps "receipt settings" from being independently creatable without a library profile behind it.

**Consequence:** an admin must save Library Profile at least once before Receipt Settings becomes usable — this is enforced by the redirect, not by a database constraint. If Receipt Settings is ever split out for reasons unrelated to Library Profile (e.g. a future multi-branch model with one library profile but several receipt configs), this decision would need to be revisited.

### ADR-8: Notification Settings is the single owner of reminder/channel/quiet-hour/dashboard-display preferences

**Decision:** All reminder-day, notification-channel, quiet-hours, and dashboard-display preferences live on the `library_settings` row and are read/written exclusively through `database/notification_settings_queries.py`, surfaced at Settings → Notification Settings. `membership_settings.reminder_days`/`send_reminders` — which previously held the reminder-day/send-reminders concept — are left in the table but `database/membership_settings_queries.py`'s `save_membership_settings()` no longer includes them in its INSERT/UPDATE, and `templates/settings/membership_settings.html` no longer exposes editable inputs for them. Instead, Membership Settings renders a read-only "Reminders & Notifications" summary sourced from `get_notification_settings(admin_id)`, with a link to Notification Settings.

**Why:** the same concept (which reminder days trigger a notification) had drifted into two places — `membership_settings.reminder_days`/`send_reminders` (a single day + on/off flag) and the richer `library_settings.reminder_7_days`/`reminder_3_days`/`reminder_1_day`/etc. added for Notification Settings. Keeping both editable would mean two forms writing to two different representations of the same behavior, with no clear rule for which one wins if they disagree. Notification Settings' representation is strictly more expressive (three independent day-toggles plus expiry-day/after-expiry, versus one day + one flag), so it was picked as the single source of truth; Membership Settings becomes a read-only consumer instead of a second writer.

**Consequence:** the old `membership_settings` columns are now dead weight (see TD-23 in [11_FUTURE_WORK.md](11_FUTURE_WORK.md)) — kept rather than dropped to avoid a destructive schema change for a save-only config table. Anyone extending reminder behavior should treat `library_settings`'s `reminder_*`/`notify_*` columns as the only place to add new reminder-related fields; do not resurrect `membership_settings.reminder_days`/`send_reminders` as a second writable path.

### ADR-9: Data & Backup and Security Settings use dedicated new tables, not `library_settings`

**Decision:** Unlike Receipt Settings and Notification Settings (both of which extend the existing `library_settings` row), Data & Backup uses a new `backup_log` table (one row per admin, tracking `last_backup_at`/`backup_filename`) and Security Settings uses a new `security_settings` table (one row per admin, `session_timeout_minutes`/`remember_me_enabled`/`login_notifications_enabled`), each created by their own `database/migrate_*.py` script and defined directly in `schema.sql` for fresh installs.

**Why:** Receipt Settings and Notification Settings are both legitimately tied to "does this admin have a Library Profile yet" — `receipt_settings()`/`notification_settings()` redirect to `library_profile` if the row doesn't exist, because `library_settings.library_name`/`phone` are `NOT NULL` and there's no sensible lazily-created bare row to insert. Backups and security preferences have no such dependency: an admin should be able to take a backup or set a session timeout before ever filling in a Library Profile. Extending `library_settings` for these would have imported that same "profile must exist first" restriction for no reason, or forced a workaround (allowing `NULL` on columns that are supposed to be required). Separate tables sidestep the coupling entirely — `database/backup_queries.py`'s `record_backup()` and `database/security_settings_queries.py`'s `save_security_settings()` are both plain upserts (`INSERT ... ON CONFLICT(admin_id) DO UPDATE`), no existence guard needed.

**Consequence:** two more single-purpose one-row-per-admin tables to maintain, but no artificial dependency on Library Profile being filled in first. `get_security_settings(admin_id)` returns an in-memory defaults dict (not `None`) when no row exists yet, since there's nothing to redirect to — contrast with `get_notification_settings`/`get_receipt_settings`, which return `None` and rely on the route's redirect-to-`library_profile` guard.

### ADR-10: Data & Backup exposes one backup/export action per distinct output, not one per code path

**Decision:** Data & Backup offers exactly two user-facing actions — `Export CSV` (`backup_export_csv`) and `Create Backup` (`backup_create`) — instead of separately exposing every route that can produce a `.db` file. The `backup_export_db` route (a bare `send_file(DATABASE_PATH)` passthrough with no server-side trace) was removed even though it was technically a distinct code path from `backup_create`, because both produced the same `library.db` content for the user.

**Why:** `backup_export_db` and `backup_create` differed only in bookkeeping — `backup_create` additionally copies the file into `backups/` and calls `record_backup()` to keep `backup_log`'s `last_backup_at` accurate. Exposing both as separate buttons meant a user could download an identical file via the untracked path and be left with a stale "Last Backup Date" stat, with no way to tell from the UI that one button "counts" and the other doesn't.

**How to apply:** if a future Data & Backup addition would produce output that's byte-identical (or near-identical) to an existing action, don't add a new button for it just because the underlying route differs — either fold it into the existing tracked action or make sure it does its own equivalent bookkeeping. A new route/button pair is only warranted when it produces a genuinely different artifact (as `Export CSV` does).
