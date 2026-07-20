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
| `status` | TEXT DEFAULT `'Interested'` | Set to `'Admitted'` by `routes/student.py`'s `admission()` |
| `created_at` | TIMESTAMP DEFAULT CURRENT_TIMESTAMP | |

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
| `created_at`, `updated_at` | TIMESTAMP DEFAULT CURRENT_TIMESTAMP | |

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
| `auto_expiry`, `allow_early_renewal`, `send_reminders` | INTEGER DEFAULT 1, CHECK(0/1) | Boolean flags |
| `reminder_days` | INTEGER DEFAULT 3 | |
| `created_at`, `updated_at` | TIMESTAMP DEFAULT CURRENT_TIMESTAMP | |

**Note:** this table stores *configured* plan pricing/policy, but `routes/membership.py`'s `create()`/`renew()` do **not** currently read from it — fee amounts are entered manually per-membership in the create/renew forms. There is no wiring yet from Membership Settings → the actual membership-creation flow. See [11_FUTURE_WORK.md](11_FUTURE_WORK.md).

## Multi-tenant (`admin_id`) summary

| Table | Isolation mechanism |
|---|---|
| `enquiries`, `students`, `audit_log`, `library_settings`, `membership_settings` | Direct `admin_id` column with FK (except `expenses`/`cashbook`, see below) |
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

There is **no migrations framework** (no Alembic/Flask-Migrate, no version table) — each script is run manually and independently, and correctness depends on running them in the right order on a fresh DB, or trusting each script's own idempotency guard on an existing one.

## Schema evolution (from git history)

`schema.sql` changed across 6 commits, roughly in this order: initial tables → V1 buildout → multi-tenant `admin_id` isolation retrofit → cashbook/transactions extensions → refactor → membership_settings added (most recent).
