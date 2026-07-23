# Database Schema

Single SQLite file: `database/library.db`. Source of truth for a fresh DB is `database/schema.sql`, run via `database/seed.py`'s `initialize_database()`. `PRAGMA foreign_keys = ON;` is set at the top of `schema.sql` but is **not** set on regular per-request connections (`database/db.py`'s `get_connection()`), so FK enforcement is effectively inconsistent — see [02_ARCHITECTURE.md](02_ARCHITECTURE.md).

## Tables

### `admins`
| Column | Type | Notes |
|---|---|---|
| `admin_id` | INTEGER PK AUTOINCREMENT | |
| `full_name` | TEXT NOT NULL | |
| `username` | TEXT NOT NULL UNIQUE | |
| `password` | TEXT NOT NULL | Werkzeug hash |
| `mobile` | TEXT NOT NULL UNIQUE | |
| `email` | TEXT | |
| `role` | TEXT DEFAULT `'admin'` | `routes/auth.py` inserts `"Admin"` (capitalized) — inconsistent casing vs. schema default |
| `created_at` | TIMESTAMP DEFAULT CURRENT_TIMESTAMP | |

The tenant root — every other admin-scoped table references `admin_id` back to this table.

**As of 2026-07-23 (ADR-16/ADR-17), `admins` is read/written in two places** — this is the first table in the incremental Supabase cutover, and the split is deliberate but temporary: `routes/auth.py` (login/register/forgot-password) reads/writes the copy in **Supabase** (PostgreSQL, schema defined by `database/supabase_migration.sql` — column shapes are identical to the SQLite table above per ADR-14) via `database/supabase_client.py`. As of the same day (ADR-17), `routes/setting.py`'s `security_settings()` (Settings → Security Settings → Change Password) reads/writes `admins.password` in **Supabase too**, via the same client — `admins.password` now has a single writer again (TD-35, `Resolved`).

Row *existence* (the `admin_id` FK every other admin-scoped table needs) is kept in sync: `routes/auth.py`'s `register()` inserts into Supabase, then mirrors the identical row (same `admin_id`) into SQLite too — this is a deliberate bridge, not an oversight, because all 7 tables listed in the "Multi-tenant (`admin_id`) summary" section below with a real FK (`enquiries`, `students`, `audit_log`, `library_settings`, `membership_settings`, `backup_log`, `security_settings`) still enforce it against `admins.admin_id` (`database/db.py` sets `PRAGMA foreign_keys = ON` on every connection). Without this mirror, a newly registered admin would satisfy Supabase-backed login but get `sqlite3.IntegrityError: FOREIGN KEY constraint failed` the instant they touched any of those seven tables — confirmed live via the full test suite before this bridge was added. This mirror is unaffected by ADR-17 — it exists for `admin_id` row existence, not `password`, and none of the 7 FK-dependent tables were migrated in that slice. Every other table in this file is still SQLite-only.

### `settings` (legacy, superseded)
| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | |
| `library_name` | TEXT NOT NULL | |
| `owner_name`, `mobile`, `address`, `logo` | TEXT | |
| `receipt_mode` | TEXT DEFAULT `'auto'` | |
| `receipt_prefix` | TEXT DEFAULT `'RCP-'` | |
| `next_receipt_number` | INTEGER DEFAULT 1001 | |

No `admin_id` — a single global row. **Not used by any current route** (`routes/setting.py` uses `library_settings` instead). Appears to be an earlier iteration left in the schema. See [11_FUTURE_WORK.md](11_FUTURE_WORK.md).

### `enquiries` (admin-scoped)
| Column | Type | Notes |
|---|---|---|
| `enquiry_id` | INTEGER PK | |
| `admin_id` | INTEGER NOT NULL FK → `admins` | |
| `full_name`, `mobile` | NOT NULL | |
| `purpose`, `preferred_shift`, `remarks` | TEXT | |
| `demo_done` | INTEGER DEFAULT 0 | |
| `followup_date` | DATE | |
| `status` | TEXT DEFAULT `'Interested'` | Set to `'Admitted'` by `routes/student.py`'s `admission()` — **as of 2026-07-23 (ADR-18), this write only reaches the SQLite mirror, not Supabase; see the note below and TD-36** |
| `created_at` | TIMESTAMP DEFAULT CURRENT_TIMESTAMP | |

**As of 2026-07-23 (ADR-18), `enquiries` is read/written in two places**, the same pattern as `admins` above: `routes/enquiries.py` (`index()`/`add()`/`edit()`/`delete()`/`view()`) reads/writes the copy in **Supabase** (schema defined by `database/supabase_migration.sql`) via `database/supabase_client.py`, and is the source of truth for every read. SQLite is kept as a write-synced **mirror** — `add()`/`edit()` write the identical row to both, `delete()` deletes from Supabase then best-effort deletes the SQLite mirror — purely because `routes/student.py`'s `admission()` (unmigrated, out of scope for this slice) reads the enquiry row and inserts `students` against a real SQLite FK to `enquiry_id`. That route's own write, `UPDATE enquiries SET status='Admitted' ...`, only ever touches the SQLite mirror — Supabase's `status` column is never told, so it goes stale the moment a student is admitted (TD-36; same shape as TD-35's `admins.password` split, on a different column). Every other column mirror-syncs correctly (`full_name`/`mobile`/`purpose`/`preferred_shift`/`followup_date`/`remarks`), since `routes/enquiries.py` itself writes both copies for those.

### `students` (admin-scoped)
| Column | Type | Notes |
|---|---|---|
| `student_id` | INTEGER PK | |
| `admin_id` | INTEGER NOT NULL FK → `admins` | |
| `enquiry_id` | INTEGER FK → `enquiries` | Null if admitted without a prior enquiry |
| `full_name`, `mobile` | NOT NULL | |
| `address`, `id_proof`, `purpose`, `shift` | TEXT | |
| `join_date` | DATE | |
| `status` | TEXT DEFAULT `'Active'` | |
| `created_at` | TIMESTAMP DEFAULT CURRENT_TIMESTAMP | |
| — | **UNIQUE(`mobile`, `admin_id`)** | Same mobile number can exist for different admins, not twice for the same admin |

### `memberships`
| Column | Type | Notes |
|---|---|---|
| `membership_id` | INTEGER PK | |
| `student_id` | INTEGER NOT NULL FK → `students` | **No direct `admin_id` column** — tenant isolation is via `student_id → students.admin_id` join |
| `plan_name` | TEXT NOT NULL | `"Monthly"`, `"Quarterly"`, `"Half-Yearly"`, `"Yearly"` |
| `joining_date` | DATE NOT NULL | |
| `duration_days` | INTEGER | |
| `end_date` | DATE NOT NULL | |
| `total_fee` | REAL NOT NULL | |
| `paid_amount` | REAL DEFAULT 0 | |
| `pending_amount` | REAL DEFAULT 0 | |
| `remarks` | TEXT | |
| `membership_status` | TEXT DEFAULT `'Active'` | `'Active'` / `'Expired'` — set programmatically, not by a scheduled job (see below) |
| `created_at` | TIMESTAMP DEFAULT CURRENT_TIMESTAMP | |

**Note:** `membership_status` is only flipped to `'Expired'` explicitly when `routes/membership.py`'s `renew()` runs. There is no background job — a membership whose `end_date` has passed but was never renewed stays `membership_status = 'Active'` in the DB. Every route that needs the "really active" answer recomputes it at query time (e.g. `end_date >= DATE('now')` in `routes/dashboard.py`, `routes/student.py`, `routes/membership_distribution.py`). This "effective status" pattern is duplicated across at least 3 route files rather than centralized — see [11_FUTURE_WORK.md](11_FUTURE_WORK.md).

### `payments`
| Column | Type | Notes |
|---|---|---|
| `payment_id` | INTEGER PK | |
| `membership_id` | INTEGER NOT NULL FK → `memberships` | |
| `student_id` | INTEGER NOT NULL FK → `students` | Denormalized — also derivable via `membership_id` |
| `receipt_number` | TEXT UNIQUE | Format `REC-YYYYMMDD-...`, generated in the route, not the DB |
| `payment_mode` | TEXT NOT NULL | |
| `amount_paid` | REAL NOT NULL | |
| `payment_date` | DATE DEFAULT CURRENT_DATE | |
| `remarks` | TEXT | |
| `created_at` | TIMESTAMP DEFAULT CURRENT_TIMESTAMP | |

No `admin_id` column — isolation via `student_id`/`membership_id` join.

### `cashbook` (the financial ledger)
Base columns from `CREATE TABLE`, extended later in the same `schema.sql` via inline `ALTER TABLE ADD COLUMN` statements:

| Column | Type | Notes |
|---|---|---|
| `entry_id` | INTEGER PK | |
| `type` | TEXT NOT NULL | `"Income"` / `"Expense"` |
| `description` | TEXT | |
| `amount` | REAL | |
| `entry_date` | DATE | |
| `payment_id` | INTEGER FK → `payments` | Only set for auto-generated income entries |
| `category` | TEXT | added via ALTER |
| `person` | TEXT | added via ALTER |
| `admin_id` | INTEGER | added via ALTER — **no FK constraint** (SQLite can't add an FK via `ALTER TABLE ADD COLUMN`) |
| `payment_method` | TEXT | added via ALTER — `"Cash"` / `"UPI"` / `"Bank Transfer"` |
| `reference_id` | TEXT | added via `migrate_cashbook_ledger.py`, format `PREFIX-YYYYMMDD-00001` |
| `source` | TEXT | added via `migrate_cashbook_ledger.py` — `"Cashbook Manual Entry"` marks a row as user-editable; anything else (`"Membership Fee"`, `"Renewal"`, etc.) marks it as system-generated and read-only in the UI |

Rows are created two ways: `insert_transaction()` (manual, user-facing form) and `insert_income_entry()` (automatic, called from `routes/membership.py` and `routes/payment.py` inside the same transaction as the membership/payment insert). See [database/cashbook_queries.py](../database/cashbook_queries.py) and [09_DEPENDENCY_MAP.md](09_DEPENDENCY_MAP.md).

### `expenses`
| Column | Type | Notes |
|---|---|---|
| `expense_id` | INTEGER PK | |
| `admin_id` | INTEGER NOT NULL | No FK declared |
| `title`, `category` | NOT NULL | |
| `amount` | REAL NOT NULL | |
| `payment_method`, `vendor`, `notes` | TEXT | |
| `expense_date` | DATE NOT NULL | |
| `created_at` | TIMESTAMP DEFAULT CURRENT_TIMESTAMP | |

**Not currently written or read by any route** — no `database/*_queries.py` module or route references this table. Expense tracking in practice happens through `cashbook` (`type = 'Expense'`) instead. Likely an earlier or abandoned design; see [11_FUTURE_WORK.md](11_FUTURE_WORK.md).

### `transactions` — ⚠ defined twice, inconsistently
`schema.sql` defines one shape:

| Column | Type |
|---|---|
| `id` | INTEGER PK |
| `transaction_type`, `category` | NOT NULL |
| `person` | TEXT |
| `amount` | REAL NOT NULL |
| `payment_method` | TEXT |
| `transaction_date` | TEXT |
| `description` | TEXT |
| `created_at` | TIMESTAMP DEFAULT CURRENT_TIMESTAMP |

`database/migrate_transactions.py` separately does `CREATE TABLE IF NOT EXISTS transactions` with a **different** shape: PK named `transaction_id` (not `id`), an added `admin_id INTEGER NOT NULL FK → admins`, and `transaction_date DATE` (not `TEXT`). Because both use `IF NOT EXISTS`, whichever one runs first "wins" and the other becomes a silent no-op — the two files disagree on the table's actual shape depending on run order. **No route or query module currently reads/writes this table at all** (confirmed no `FROM transactions` / `INTO transactions` outside these two schema-definition files) — it appears to be superseded by `cashbook`. Flagged in [11_FUTURE_WORK.md](11_FUTURE_WORK.md) as needing reconciliation or removal.

### `audit_log`
| Column | Type | Notes |
|---|---|---|
| `log_id` | INTEGER PK | |
| `admin_id` | INTEGER NOT NULL FK → `admins` | |
| `entry_id` | INTEGER FK → `cashbook` | |
| `action` | TEXT NOT NULL | `"Created"` / `"Updated"` / `"Auto-Created"` |
| `details` | TEXT | |
| `created_at` | TIMESTAMP DEFAULT CURRENT_TIMESTAMP | |

Append-only trail for cashbook changes. Written via `database/audit_queries.py`'s `log_entry(cursor, ...)`, always called inside the same transaction/cursor as the cashbook change it documents (from `cashbook_queries.insert_transaction`, `insert_income_entry`, `update_manual_transaction`) — an audit row can never exist without its corresponding change actually having happened.

### `library_settings` (one row per admin)
| Column | Type | Notes |
|---|---|---|
| `setting_id` | INTEGER PK | |
| `admin_id` | INTEGER NOT NULL **UNIQUE** FK → `admins` | |
| `library_name` NOT NULL, `owner_name`, `phone` NOT NULL, `email`, `address`, `city`, `state`, `pincode` | TEXT | |
| `opening_time`, `closing_time`, `weekly_holiday` | TEXT | |
| `logo_path`, `stamp_path`, `signature_path` | TEXT | Relative to `static/`, e.g. `uploads/settings/logo_1_foo.png` |
| `receipt_footer` | TEXT | Added later by `migrate_settings_receipt_footer.py` — absent from the original `migrate_library_settings.py` |
| `receipt_prefix` TEXT DEFAULT 'LIB', `next_receipt_number` INTEGER DEFAULT 1001, `auto_increment_receipt` INTEGER DEFAULT 1 | | Added by `migrate_receipt_settings.py` — receipt numbering |
| `print_logo`, `print_stamp`, `print_signature` | INTEGER DEFAULT 1 | Added by `migrate_receipt_settings.py` — which Library Profile assets to print on the receipt |
| `paper_size` | TEXT DEFAULT 'A4' | Added by `migrate_receipt_settings.py` — `A4`, `thermal_80mm`, or `thermal_58mm` |
| `auto_print`, `auto_email`, `duplicate_copy` | INTEGER DEFAULT 0 | Added by `migrate_receipt_settings.py` — printing/emailing preferences; not wired to any actual print/email logic yet, see [11_FUTURE_WORK.md](11_FUTURE_WORK.md) |
| `open_pdf_after_save` | INTEGER DEFAULT 1 | Added by `migrate_receipt_settings.py` |
| `reminder_7_days`, `reminder_3_days`, `reminder_1_day`, `notify_on_expiry_day`, `notify_after_expiry` | INTEGER DEFAULT 1 | Added by `migrate_notification_settings.py` — Notification Settings' Reminder Rules section |
| `notify_in_app` | INTEGER DEFAULT 1 | Added by `migrate_notification_settings.py` |
| `notify_sms`, `notify_email`, `notify_whatsapp` | INTEGER DEFAULT 0 | Added by `migrate_notification_settings.py` — channel toggles; no SMS/Email/WhatsApp dispatch engine exists, save-only (see [11_FUTURE_WORK.md](11_FUTURE_WORK.md) TD-24) |
| `quiet_hours_enabled` | INTEGER DEFAULT 0 | Added by `migrate_notification_settings.py` |
| `quiet_hours_start` TEXT DEFAULT `'22:00'`, `quiet_hours_end` TEXT DEFAULT `'07:00'` | | Added by `migrate_notification_settings.py` |
| `quiet_hours_allow_critical` | INTEGER DEFAULT 1 | Added by `migrate_notification_settings.py` |
| `dash_show_badge_count`, `dash_show_expiry_today`, `dash_show_expiry_tomorrow`, `dash_show_overdue`, `dash_show_pending_fees`, `dash_show_new_admissions` | INTEGER DEFAULT 1 | Added by `migrate_notification_settings.py` — control the navbar bell/dashboard. `dash_show_pending_fees` is read by `routes/dashboard.py`; the badge/today/tomorrow/overdue flags are read by `app.py`'s `inject_notification_summary` context processor for `components/notification_dropdown.html`; `dash_show_new_admissions` has no consumer yet (TD-25) |
| `created_at`, `updated_at` | TIMESTAMP DEFAULT CURRENT_TIMESTAMP | |

Receipt Settings (`routes/setting.py`'s `receipt_settings()`) and Notification Settings (`notification_settings()`) both read/write columns on this same row as Library Profile — there is no separate receipt-settings or notification-settings table (see ADR-7/ADR-8 in [DECISIONS.md](DECISIONS.md)).

### `membership_settings` (one row per admin)
| Column | Type | Notes |
|---|---|---|
| `setting_id` | INTEGER PK | |
| `admin_id` | INTEGER NOT NULL **UNIQUE** FK → `admins` | |
| `monthly_fee` REAL DEFAULT 0, `monthly_days` INTEGER DEFAULT 30 | | |
| `quarterly_fee` REAL DEFAULT 0, `quarterly_days` INTEGER DEFAULT 90 | | |
| `half_yearly_fee` REAL DEFAULT 0, `half_yearly_days` INTEGER DEFAULT 180 | | |
| `yearly_fee` REAL DEFAULT 0, `yearly_days` INTEGER DEFAULT 365 | | |
| `admission_fee` REAL DEFAULT 0, `late_fee_per_day` REAL DEFAULT 0 | | |
| `renewal_grace_days` INTEGER DEFAULT 7 | | |
| `auto_expiry`, `allow_early_renewal` | INTEGER DEFAULT 1, CHECK(0/1) | Boolean flags |
| `send_reminders` | INTEGER DEFAULT 1, CHECK(0/1) | **Unused as of 2026-07-21** — superseded by `library_settings.notify_*`/`reminder_*` columns (Notification Settings). Column left in place, no longer written by `save_membership_settings()`. See TD-23 in [11_FUTURE_WORK.md](11_FUTURE_WORK.md) |
| `reminder_days` | INTEGER DEFAULT 3 | **Unused as of 2026-07-21** — same as `send_reminders` above |
| `created_at`, `updated_at` | TIMESTAMP DEFAULT CURRENT_TIMESTAMP | |

**Note:** this table stores *configured* plan pricing/policy, but `routes/membership.py`'s `create()`/`renew()` do **not** currently read from it — fee amounts are entered manually per-membership in the create/renew forms. There is no wiring yet from Membership Settings → the actual membership-creation flow. See [11_FUTURE_WORK.md](11_FUTURE_WORK.md).

### `backup_log` (one row per admin)
| Column | Type | Notes |
|---|---|---|
| `log_id` | INTEGER PK | |
| `admin_id` | INTEGER NOT NULL **UNIQUE** FK → `admins` | |
| `last_backup_at` | TIMESTAMP | Set to `CURRENT_TIMESTAMP` each time a backup is taken |
| `backup_filename` | TEXT | Filename only (e.g. `library_backup_3_20260721_143000.db`), not a full path — the actual file lives under the project-root `backups/` folder |

Created by `database/migrate_backup_log.py`. Deliberately **not** a column on `library_settings` — a backup can be taken before a Library Profile row exists (`library_settings.library_name`/`phone` are `NOT NULL`, so it can't hold a lazily-created bare row). See ADR-9 in [DECISIONS.md](DECISIONS.md). Written via `database/backup_queries.py`'s `record_backup(admin_id, backup_filename)` (upsert), called only from `routes/setting.py`'s `backup_create()` — there is no automatic/scheduled backup job (PF-5 in [11_FUTURE_WORK.md](11_FUTURE_WORK.md)).

### `security_settings` (one row per admin)
| Column | Type | Notes |
|---|---|---|
| `setting_id` | INTEGER PK | |
| `admin_id` | INTEGER NOT NULL **UNIQUE** FK → `admins` | |
| `session_timeout_minutes` | INTEGER NOT NULL DEFAULT 60 | One of `15`/`30`/`60`/`0` (`0` = "Never") — **not enforced**, no session-expiry middleware exists |
| `remember_me_enabled` | INTEGER NOT NULL DEFAULT 0, CHECK(0/1) | **Not enforced** — no "remember me" cookie/token logic exists |
| `login_notifications_enabled` | INTEGER NOT NULL DEFAULT 0, CHECK(0/1) | **Not enforced** — no login-notification delivery mechanism exists |
| `created_at`, `updated_at` | TIMESTAMP DEFAULT CURRENT_TIMESTAMP | |

Created by `database/migrate_security_settings.py`. Deliberately separate from `library_settings` for the same reason as `backup_log` (ADR-9). Password change (Settings → Security Settings' "Change Password" form) does **not** use this table at all — it updates `admins.password` directly via `routes/setting.py`'s `security_settings()` and is fully functional; only the three columns above are persisted-but-unenforced (TD-26 in [11_FUTURE_WORK.md](11_FUTURE_WORK.md)).

## Multi-tenant (`admin_id`) summary

| Table | Isolation mechanism |
|---|---|
| `enquiries`, `students`, `audit_log`, `library_settings`, `membership_settings`, `backup_log`, `security_settings` | Direct `admin_id` column with FK (except `expenses`/`cashbook`, see below) |
| `expenses` | Direct `admin_id` column, **no FK declared** |
| `cashbook` | Direct `admin_id` column, added via `ALTER TABLE` — **no FK possible** in SQLite for altered columns |
| `memberships`, `payments` | No `admin_id` column — isolated indirectly via `student_id → students.admin_id` |
| `settings`, `transactions` | Not admin-scoped at all (unused/legacy tables) |

## Migration scripts (all in `database/`, run manually/individually — no migration runner or version tracking)

| Script | Effect | Idempotent? |
|---|---|---|
| `migrate.py` | Adds `admin_id` to `enquiries`; recreates `students` with `admin_id` + `UNIQUE(mobile, admin_id)`, backfilling existing rows to the first admin found | Yes for `enquiries` (checks column first); the `students` recreate is destructive-by-rebuild if run on an already-migrated table (guarded, but worth caution) |
| `migrate_audit_log.py` | Creates `audit_log` | Yes (`IF NOT EXISTS`) |
| `migrate_transactions.py` | Creates `transactions` (own shape, see warning above) | Yes in isolation, but conflicts with `schema.sql`'s version |
| `migrate_cashbook_ledger.py` | Adds `cashbook.reference_id`, `cashbook.source` | Yes (checks `PRAGMA table_info` first) |
| `migrate_backfill_cashbook_payments.py` | Data backfill: creates missing `cashbook` rows for historical `payments` | Effectively yes (dedupes via existence check), though the matching heuristic could theoretically miss/duplicate in edge cases |
| `migrate_library_settings.py` | Creates `library_settings` (without `receipt_footer`) | Yes |
| `migrate_settings_receipt_footer.py` | Adds `library_settings.receipt_footer` | Yes (checks `PRAGMA table_info` first) |
| `migrate_membership_setting.py` | Creates `membership_settings`; validates existing schema against expected columns and raises if incompatible | Yes, with an explicit safety check |
| `migrate_receipt_settings.py` | Adds `library_settings.receipt_prefix`, `next_receipt_number`, `auto_increment_receipt`, `print_logo`, `print_stamp`, `print_signature`, `paper_size`, `auto_print`, `auto_email`, `open_pdf_after_save`, `duplicate_copy` | Yes (checks `PRAGMA table_info` first) |
| `migrate_notification_settings.py` | Adds 19 `library_settings` columns for Notification Settings (reminder rules, channels, quiet hours, dashboard-display) | Yes (checks `PRAGMA table_info` first) |
| `migrate_backup_log.py` | Creates `backup_log`; validates existing schema against expected columns and raises if incompatible | Yes, with an explicit safety check |
| `migrate_security_settings.py` | Creates `security_settings`; validates existing schema against expected columns and raises if incompatible | Yes, with an explicit safety check |

There is **no migrations framework** (no Alembic/Flask-Migrate, no version table) — each script is run manually and independently, and correctness depends on running them in the right order on a fresh DB, or trusting each script's own idempotency guard on an existing one.

## Schema evolution (from git history)

`schema.sql` changed across 6 commits, roughly in this order: initial tables → V1 buildout → multi-tenant `admin_id` isolation retrofit → cashbook/transactions extensions → refactor → membership_settings added (most recent).
