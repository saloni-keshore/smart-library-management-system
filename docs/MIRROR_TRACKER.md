# SQLite Mirror Tracker

## Maintenance Rule

Before removing any mirror, re-grep the current codebase.

Do not rely solely on ADRs or previous dependency reports, as they may become outdated after later migrations.


This file exists to answer one question at any point during the incremental Supabase migration (ADR-16…ADR-21 in [DECISIONS.md](DECISIONS.md)): **which SQLite tables/rows are temporary write-synced mirrors of a Supabase-authoritative table, who still reads/writes each mirror, and exactly what has to happen before that mirror can be deleted.**

It is a **living document** — update it in the same session as every migration slice that creates, shrinks, or removes a mirror, not after the fact. Treat drift between this file and the actual source as a bug, the same standard [README.md](README.md)'s maintenance policy applies to the rest of `docs/`.

## How to update this file

After any session that migrates another route/table to Supabase:

1. Re-run the dependency check for every mirror this file tracks — `grep` every unmigrated route/`database/*_queries.py` module for the mirrored table name (`FROM <table>`, `JOIN <table>`), the way the "Current readers" lists below were built. Don't trust a prior ADR's own claimed consumer list without re-verifying — **ADR-20 undercounted `memberships`' remaining readers** (missed `routes/student.py`'s `view()`, `database/cashbook_queries.py`'s `get_pending_fees()`, and `database/bi_queries.py`), and this file was corrected against the actual code, not against ADR-20's prose. See ADR-21.
2. Move any now-migrated reader out of "Current readers" and into that mirror's own change history.
3. If a mirror's reader list reaches zero, check the **FK dependents** column too — a mirror can have zero readers and still be required, because a downstream unmigrated table's SQLite `FOREIGN KEY` needs the mirrored row to exist for its own inserts to succeed (`PRAGMA foreign_keys = ON` is set on every connection, `database/db.py`). Only delete a mirror-write once both columns are empty.
4. Update the summary table's "Status" and "Blocking on" columns.
5. Add a dated line to that mirror's "Change history" list.
6. If a mirror is fully removed, do **not** delete its section — mark it `Removed` and keep the history, the same way [11_FUTURE_WORK.md](11_FUTURE_WORK.md) keeps resolved `TD-N` rows instead of deleting them.

## The SQLite foreign-key chain (why removal order isn't free choice)

`database/schema.sql` declares this FK graph (every table below still exists **only** in SQLite — `payments`, `cashbook`, `audit_log`, `library_settings`, `membership_settings`, `backup_log`, `security_settings`, `expenses`, `settings`, `transactions` have no Supabase copy at all, they are not mirrors, they're simply unmigrated):

```
admins  <──admin_id── enquiries, students, audit_log, library_settings,
                       membership_settings, backup_log, security_settings   (7 tables)
enquiries <──enquiry_id── students
students  <──student_id──  memberships, payments
memberships <──membership_id── payments
payments  <──payment_id── cashbook
cashbook  <──entry_id── audit_log        (audit_log also FKs admin_id → admins directly)
```

Consequence: a mirror can only be deleted once **every** table downstream of it in this chain either (a) no longer inserts into SQLite at all (i.e., it's been migrated to Supabase too), or (b) has had its FK constraint dropped. Concretely: `payments`, `cashbook`, and `audit_log` are unmigrated and actively written on every single membership/payment/cashbook transaction — so as long as they exist in their current form, the `memberships`/`students`/`enquiries`/`admins` rows their `INSERT`s reference **must** keep existing in SQLite, independent of whether anything still *reads* those mirrors. This is why each mirror's removal conditions below have two parts, not one.

## Summary

| Mirror table | Source of truth since | Readers remaining | FK dependents still requiring it | Status |
|---|---|---|---|---|
| [`admins`](#admins-existence-only-bridge) | Supabase, ADR-16 (2026-07-23) | None (existence-only) | `enquiries`, `students`, `audit_log`, `library_settings`, `membership_settings`, `backup_log`, `security_settings` (7) | **Open** |
| [`enquiries`](#enquiries) | Supabase, ADR-18 (2026-07-23) | `routes/dashboard.py` (1) | `students.enquiry_id` | **Open** |
| [`students`](#students) | Supabase, ADR-19 (2026-07-23) | 9 modules (see below) | `memberships.student_id`, `payments.student_id` | **Open** |
| [`memberships`](#memberships) | Supabase, ADR-20 (2026-07-23) | 6 modules (see below) | `payments.membership_id` | **Open** |

`enquiries.status` and `admins.password` are **not** split anymore — both closed (TD-36 `Resolved` via ADR-19, TD-35 `Resolved` via ADR-17) — see each mirror's section for which columns still mirror-sync vs. which have a single Supabase-only writer.

---

## `admins` (existence-only bridge)

**Source of truth:** Supabase `admins` table, since ADR-16 (2026-07-23). Every actual read (login, forgot-password, Security Settings' password change) goes to Supabase.

**SQLite mirror's role:** row *existence* only — the mirror row's column values (other than `admin_id`) are never read back by any route. It exists purely so 7 other SQLite tables' `FOREIGN KEY (admin_id) REFERENCES admins(admin_id)` constraints resolve when those tables insert a row for a newly-registered admin.

**Current readers:** None. No route or query module `SELECT`s from SQLite `admins` for any business logic.

**Current writers:** `routes/auth.py`'s `register()` — inserts into Supabase first, then mirrors the identical row (`admin_id`, `full_name`, `username`, `mobile`, `email`, hashed `password`, `role`) into SQLite via `database.db.get_connection()`, rolling back the Supabase insert if the SQLite insert raises `sqlite3.Error`. `login()`/`forgot_password()` and `routes/setting.py`'s `security_settings()` password branch touch Supabase's `admins.password` only — they never write SQLite (TD-35, `Resolved` via ADR-17).

**Why the mirror still exists:** 7 tables enforce a real SQLite FK to `admins.admin_id` and are actively inserted into on every request that touches them: `enquiries` (`routes/enquiries.py`'s `add()` mirror-insert), `students` (`routes/student.py`'s `admission()` mirror-insert), `audit_log` (written transitively by `routes/cashbook.py`/`routes/membership.py`/`routes/payment.py` via `database/cashbook_queries.py`'s `insert_income_entry()`/`insert_transaction()` → `database/audit_queries.py`'s `log_entry()`), and `library_settings`/`membership_settings`/`backup_log`/`security_settings` (all four owned by `routes/setting.py`, all four still fully SQLite). Migrating `enquiries`/`students` at the *route* level (ADR-18/ADR-19) did **not** remove them from this list — both still insert their own SQLite mirror rows referencing `admin_id`, so the FK still fires.

**Exact removal conditions (both required):**
1. **Read-side:** none — already zero readers.
2. **FK-side:** all of `audit_log`, `library_settings`, `membership_settings`, `backup_log`, `security_settings` must be migrated to Supabase (so they stop inserting into SQLite), **and** either the `enquiries`/`students` mirrors (below) must themselves be fully removed, or their mirror-inserts must stop being written (which requires those mirrors' own removal conditions first). In practice: this bridge is the *last* thing removable, not the first — it's blocked on every other mirror and every other unmigrated table in this file.

**Change history:**
- 2026-07-23 (ADR-16): bridge introduced — `register()`'s Supabase-only write broke 7 tables' SQLite FK on the very next admin who touched any of them (74 test failures caught this).
- 2026-07-23 (ADR-17): `admins.password`'s split-brain closed (TD-35 `Resolved`) — unrelated to this bridge, which covers row existence, not `password`.

---

## `enquiries`

**Source of truth:** Supabase `enquiries` table, since ADR-18 (2026-07-23), for `index()`/`add()`/`edit()`/`delete()`/`view()` in `routes/enquiries.py`.

**Columns mirror-synced:** `enquiry_id` (explicit, computed as SQLite `MAX(enquiry_id) + 1`, not Supabase's identity column — see ADR-18), `admin_id`, `full_name`, `mobile`, `purpose`, `preferred_shift`, `followup_date`, `remarks`, `demo_done`.
**Column deliberately *not* mirror-synced:** `status` — `routes/student.py`'s `admission()` writes `status='Admitted'` to **Supabase only** (TD-36, `Resolved` via ADR-19). The SQLite mirror's `status` column is stale/frozen at whatever `add()` last wrote and is read by nothing.

**Current readers (SQLite):**
- `routes/dashboard.py`'s `dashboard()` — `SELECT COUNT(*) FROM enquiries WHERE admin_id = ?` for the "Total Enquiries" KPI. The only reader of this mirror's *rows*.

**Current writers (SQLite):**
- `routes/enquiries.py`'s `add()` (mirror-insert, explicit `enquiry_id`), `edit()` (mirror-update, not best-effort), `delete()` (best-effort mirror-delete, swallows `sqlite3.Error` if an already-admitted student's `students.enquiry_id` FK blocks it — see TD-36's row in [11_FUTURE_WORK.md](11_FUTURE_WORK.md) for that specific leftover-row edge case).

**Why the mirror still exists:**
- **Read-side:** `routes/dashboard.py`'s enquiry count (above) is unmigrated.
- **FK-side:** `students.enquiry_id` is a real SQLite FK. `routes/student.py`'s `admission()` inserts a SQLite `students` mirror row (ADR-19) that references `enquiry_id` — that insert requires the `enquiries` row to already exist in SQLite. (Note: `admission()` itself no longer *reads* the enquiries mirror — as of ADR-19 it reads/writes the `enquiries` row it needs directly against Supabase — but its SQLite `students` insert still needs the SQLite `enquiries` row to exist for the FK to resolve.)

**Exact removal conditions (both required):**
1. **Read-side:** migrate `routes/dashboard.py`'s enquiry count to Supabase.
2. **FK-side:** the `students` mirror (below) must stop inserting rows with a real `enquiry_id` FK reference — i.e., either `students`' own mirror is fully removed (see its section), or `students.enquiry_id`'s FK constraint is dropped/relaxed.

**Change history:**
- 2026-07-23 (ADR-18): mirror introduced — needed as an ongoing two-way sync (not a one-shot bridge like `admins`'), since `admission()` (at the time) read live enquiry field values from SQLite, not just row existence.
- 2026-07-23 (ADR-19): `status` column's writer moved to Supabase-only, closing TD-36. `admission()` stopped reading this mirror's field values (`full_name`/`mobile`/`purpose`/`preferred_shift`) — it now reads Supabase directly. Mirror itself (row existence + non-`status` columns) remained required, for the two reasons listed above.

---

## `students`

**Source of truth:** Supabase `students` table, since ADR-19 (2026-07-23), for `index()`/`admission()`/`view()`/`edit()` in `routes/student.py`.

**Columns mirror-synced:** every column — `student_id` (explicit, `MAX(student_id) + 1`, same reasoning as `enquiries.enquiry_id`), `admin_id`, `enquiry_id`, `full_name`, `mobile`, `address`, `id_proof`, `purpose`, `shift`, `join_date`, `status`. Unlike `enquiries`, there is no held-back column — `admission()`/`edit()` write both databases in full, since `students.status` has no split-brain risk analogous to `enquiries.status` (nothing else writes it).

**Current readers (SQLite)** — verified directly against source, not assumed from a prior ADR:
- `routes/payment.py`'s `index()` — `payments p INNER JOIN students s`.
- `routes/dashboard.py`'s `dashboard()` — total-students count, upcoming-expiries `JOIN students`, recent-admissions `JOIN students`.
- `routes/membership_distribution.py`'s `index()` — `memberships m JOIN students s` (twice).
- `routes/notification.py`'s `get_notification_summary()` — `memberships m JOIN students s`.
- `routes/setting.py`'s `backup_export_csv()` — `SELECT * FROM students WHERE admin_id = ?`; `backup_create()` copies the entire `library.db` file (a coarser, non-query form of consuming this mirror — see TD-32 for the unrelated cross-tenant issue in that same route).
- `routes/enquiries.py`'s `index()`/`view()` (`SELECT enquiry_id, student_id FROM students WHERE admin_id = ?`, read-only, for the `enquiry_id → student_id` map) and `delete()` (`SELECT student_id FROM students WHERE enquiry_id=? AND admin_id=?`, to explain an FK-blocked delete).
- `database/bi_queries.py` — `get_monthly_new_memberships()`, `get_membership_retention()`, `get_upcoming_expiries()` (all three `JOIN students`).
- `database/cashbook_queries.py` — `get_pending_fees()`, `get_today_fee_collection()`, `get_total_fee_revenue()` (all three `JOIN students`).
- `database/membership_queries.py` — `get_membership_counts()` (`JOIN students`), called by `routes/dashboard.py` and `routes/membership_distribution.py`.

**Not** a reader: `routes/membership.py` — migrated off this list by ADR-20 (its own student lookups go through Supabase). `routes/payment.py`'s `collect()` — migrated off this list by ADR-21 (its ownership check now reads Supabase `students`); only `routes/payment.py`'s sibling function `index()` still reads the mirror.

**Current writers (SQLite):** `routes/student.py`'s `admission()` (mirror-insert, explicit `student_id`), `edit()` (mirror-update, not best-effort).

**Why the mirror still exists:**
- **Read-side:** the 9 modules/functions listed above, none migrated.
- **FK-side:** `memberships.student_id` and `payments.student_id` are both real SQLite FKs. `routes/membership.py`'s `create()`/`renew()` insert SQLite `memberships` mirror rows (ADR-20) referencing `student_id`; `database/payment_queries.py`'s `record_payment()` (called from both `routes/membership.py` and `routes/payment.py`) inserts `payments` rows referencing `student_id` directly, on every single payment. `payments` is unmigrated and will keep needing this indefinitely until it's migrated too.

**Exact removal conditions (both required):**
1. **Read-side:** migrate all 9 listed consumers (`routes/payment.py`'s `index()`, `routes/dashboard.py`, `routes/membership_distribution.py`, `routes/notification.py`, `routes/setting.py`'s backup functions, `routes/enquiries.py`'s read-only lookups, `database/bi_queries.py`, `database/cashbook_queries.py`, `database/membership_queries.py`) to read Supabase instead.
2. **FK-side:** the `memberships` mirror must stop requiring `student_id` to exist in SQLite (see its own removal conditions — itself blocked on `payments`), **and** `payments` itself must be migrated to Supabase (removing its own SQLite `student_id` FK insert) or have that FK dropped.

**Change history:**
- 2026-07-23 (ADR-19): mirror introduced, widest fan-out found so far (8 modules at the time). Closed TD-36 at the source (`admission()`'s `enquiries.status` write moved to Supabase). `enquiries` mirror confirmed still required, independent of this migration.
- 2026-07-23 (ADR-20): `routes/membership.py` migrated off the reader list (its own student lookups moved to Supabase).
- 2026-07-23 (ADR-21): `routes/payment.py`'s `collect()` migrated off the reader list (ownership check moved to Supabase); `routes/payment.py`'s `index()` remains a reader. Re-verifying the full list against source (not against ADR-19's original prose) also surfaced `routes/setting.py`'s `backup_export_csv()`/`backup_create()` and `routes/enquiries.py`'s read-only lookups explicitly, which prior summaries had described narratively but this file now lists exhaustively.

---

## `memberships`

**Source of truth:** Supabase `memberships` table, since ADR-20 (2026-07-23), for `index()`/`create()`/`renew()` in `routes/membership.py`, and since ADR-21 (2026-07-23) for `paid_amount`/`pending_amount` specifically in `routes/payment.py`'s `collect()`.

**Columns mirror-synced:** every column, from two different writers — `routes/membership.py`'s `create()`/`renew()` write the full row (`membership_id`, explicit `MAX(membership_id) + 1`; `student_id`, `plan_name`, `joining_date`, `duration_days`, `end_date`, `total_fee`, `paid_amount`, `pending_amount`, `remarks`, `membership_status`); `routes/payment.py`'s `collect()` writes only `paid_amount`/`pending_amount` on an existing row (it never inserts a new membership row).

**Current readers (SQLite)** — verified directly against source:
- `routes/dashboard.py`'s `dashboard()` — upcoming-expiries `JOIN memberships`, recent-admissions `LEFT JOIN memberships`; also `database/membership_queries.py`'s `get_membership_counts()` (`JOIN memberships`).
- `routes/membership_distribution.py`'s `index()` — full membership listing (`memberships m JOIN students s`), plus `get_membership_counts()`.
- `routes/notification.py`'s `get_notification_summary()` — `memberships m JOIN students s`.
- `routes/student.py`'s `view()` — `SELECT * FROM memberships WHERE student_id=? ORDER BY membership_id DESC LIMIT 1` (the Student detail page's membership card).
- `database/cashbook_queries.py`'s `get_pending_fees()` — `SUM(memberships.pending_amount)`, feeding Dashboard/Membership Distribution/Cashbook/the BI health score's collection component (ADR-11).
- `database/bi_queries.py` — `get_monthly_new_memberships()`, `get_membership_retention()`, `get_upcoming_expiries()` (all three `JOIN memberships`).

**Not** a reader: `routes/payment.py`'s `collect()` — as of ADR-21 it reads the membership from Supabase, not SQLite, before updating either. `routes/payment.py`'s `index()` never touches `memberships` at all (only `payments`/`students`).

**Current writers (SQLite):** `routes/membership.py`'s `create()`/`renew()` (full mirror), `routes/payment.py`'s `collect()` (`paid_amount`/`pending_amount` only, added ADR-21).

**Why the mirror still exists:**
- **Read-side:** the 6 modules/functions listed above (`routes/dashboard.py`, `routes/membership_distribution.py`, `routes/notification.py`, `routes/student.py`'s `view()`, `database/cashbook_queries.py`'s `get_pending_fees()`, `database/bi_queries.py`), plus the shared `database/membership_queries.py`'s `get_membership_counts()` two of them call.
- **FK-side:** `payments.membership_id` is a real SQLite FK. `database/payment_queries.py`'s `record_payment()` inserts a `payments` row on every membership creation/renewal/collection, referencing `membership_id` — this fires from both `routes/membership.py` and `routes/payment.py`, on every payment, and will keep requiring the SQLite `memberships` row to exist until `payments` itself is migrated.

**Exact removal conditions (both required):**
1. **Read-side:** migrate `routes/dashboard.py`, `routes/membership_distribution.py`, `routes/notification.py`, `routes/student.py`'s `view()`, `database/cashbook_queries.py`'s `get_pending_fees()`, and `database/bi_queries.py` (its three membership-retention/expiry functions) to read Supabase instead.
2. **FK-side:** `payments` must be migrated to Supabase (removing its SQLite `membership_id` FK insert) or that FK must be dropped. Since `database/payment_queries.py`'s `record_payment()` is shared by both `routes/membership.py` and `routes/payment.py`, migrating `payments` is a change to both routes, not one.

**Change history:**
- 2026-07-23 (ADR-20): mirror introduced. `routes/payment.py`'s `collect()`, `routes/dashboard.py`, `routes/membership_distribution.py`, `routes/notification.py` named as remaining readers — this list was **incomplete** (see ADR-21's correction below).
- 2026-07-23 (ADR-21): `routes/payment.py`'s `collect()` migrated off the reader list and onto the writer list for `paid_amount`/`pending_amount` (closing TD-37). Re-verifying the dependency graph directly against source (not against ADR-20's prose) found ADR-20's reader list had missed `routes/student.py`'s `view()`, `database/cashbook_queries.py`'s `get_pending_fees()`, and `database/bi_queries.py` — all three added to this file's tracked list, none of them touched by ADR-21, all still `Open`.

---

## Non-mirror unmigrated tables that gate the mirrors above

These have **no Supabase copy at all** — they are not mirrors, but they are exactly what's blocking every mirror's FK-side removal condition, so they're tracked here for completeness:

| Table | Written by | Blocks removal of |
|---|---|---|
| `payments` | `database/payment_queries.py`'s `record_payment()` (called from `routes/membership.py` and `routes/payment.py`) | `memberships` mirror (FK), `students` mirror (FK, transitively) |
| `cashbook` | `database/cashbook_queries.py`'s `insert_transaction()`/`insert_income_entry()` (called from `routes/cashbook.py`, and transitively via `record_payment()`) | `payments` (FK) — and therefore `memberships`/`students` transitively once `payments` migrates |
| `audit_log` | `database/audit_queries.py`'s `log_entry()` (called from `database/cashbook_queries.py`) | `admins` bridge (FK), `cashbook` (FK) |
| `library_settings`, `membership_settings`, `backup_log`, `security_settings` | `routes/setting.py` (all four, except `security_settings`'s password branch which is Supabase-only, ADR-17) | `admins` bridge (FK) |

Migrating any of these five tables is orthogonal to the four mirrors above in the sense that none of them currently *read* a mirror — but migrating them is exactly what shrinks each mirror's FK-side blocker. `payments` in particular is the single highest-leverage next migration for this file: it simultaneously helps close the FK-side of both `memberships` and (transitively, once `students.student_id`'s reference through `payments` is gone) `students`.

## Related reading

- [DECISIONS.md](DECISIONS.md) — ADR-16 through ADR-21, the full reasoning behind each slice.
- [11_FUTURE_WORK.md](11_FUTURE_WORK.md) — TD-34 (schema-drift risk), TD-35/TD-36/TD-37 (the three split-brain bugs each mirror slice risked, all now `Resolved`).
- [09_DEPENDENCY_MAP.md](09_DEPENDENCY_MAP.md) — the literal import graph this file's "Current readers"/"Current writers" lists are derived from.
- [04_DATABASE_SCHEMA.md](04_DATABASE_SCHEMA.md) — full FK list per table.
