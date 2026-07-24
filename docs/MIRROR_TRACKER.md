# SQLite Mirror Tracker

## Maintenance Rule

Before removing any mirror, re-grep the current codebase.

Do not rely solely on ADRs or previous dependency reports, as they may become outdated after later migrations.


This file exists to answer one question at any point during the incremental Supabase migration (ADR-16…ADR-24 in [DECISIONS.md](DECISIONS.md)): **which SQLite tables/rows are temporary write-synced mirrors of a Supabase-authoritative table, who still reads/writes each mirror, and exactly what has to happen before that mirror can be deleted.**

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

`database/schema.sql` declares this FK graph. As of ADR-25 (2026-07-24), every table in this graph except `expenses`/`settings`/`transactions` (unused legacy tables, see TD-2/TD-3/TD-4) is now either a Supabase-sourced-of-truth mirror or fully migrated with no mirror at all:

```
admins  <──admin_id── enquiries, students, audit_log   (3 tables — library_settings/
                       membership_settings/backup_log/security_settings dropped off
                       this list entirely by ADR-24, see below)
enquiries <──enquiry_id── students
students  <──student_id──  memberships, payments
memberships <──membership_id── payments
payments  <──payment_id── cashbook        (Supabase enforces this FK too — payments migrating,
                                            ADR-25, is what finally let cashbook's Supabase mirror
                                            carry a real payment_id, closing TD-38)
cashbook  <──entry_id── audit_log        (audit_log also FKs admin_id → admins directly)
```

Consequence: a mirror can only be deleted once **every** table downstream of it in this chain either (a) no longer inserts into SQLite at all (i.e., it's been migrated to Supabase too), or (b) has had its FK constraint dropped. `payments` (as of ADR-25) and `cashbook`/`audit_log` (as of ADR-22) are all now Supabase-sourced-of-truth mirrors themselves, but every one of them still keeps a SQLite mirror-write on every single membership/payment/cashbook transaction — so as long as they exist in their current *write* form, the `memberships`/`students`/`enquiries`/`admins` rows their `INSERT`s reference **must** keep existing in SQLite, independent of whether anything still *reads* those mirrors. This is why each mirror's removal conditions below have two parts, not one.

## Fully migrated, no mirror: `library_settings`, `membership_settings`, `backup_log`, `security_settings`

As of ADR-24 (2026-07-24), these four tables are **not** tracked as mirrors below, because they never became one — `database/settings_queries.py`/`receipt_settings_queries.py`/`notification_settings_queries.py` (`library_settings`), `database/membership_settings_queries.py`, `database/backup_queries.py`, and `database/security_settings_queries.py` read/write Supabase exclusively, with **zero** SQLite reads or writes left in any of them. This was possible in one step (unlike `admins`/`enquiries`/`students`/`memberships`/`cashbook`/`payments`, which each needed an ongoing mirror) because these four tables are leaf nodes in the FK graph above — nothing else in `schema.sql` declares a foreign key against any of them, so there was never a downstream unmigrated table that needed their SQLite row to keep existing. `database/migrate_backfill_settings_to_supabase.py` synced SQLite's more-current data into Supabase (a plain `admin_id`-keyed upsert, not the explicit-id/rollback machinery `enquiries`/`students`/`memberships`/`cashbook`/`payments` needed) before the code cutover — see ADR-24. Their old SQLite tables still physically exist (rows frozen at whatever they held at migration time) until Phase 11 (SQLite removal) drops them along with everything else.

This closed 4 of the `admins` bridge's original 7 FK dependents in one slice — see that section below.

## Summary

| Mirror table | Source of truth since | Readers remaining | FK dependents still requiring it | Status |
|---|---|---|---|---|
| [`admins`](#admins-existence-only-bridge) | Supabase, ADR-16 (2026-07-23) | None (existence-only) | `enquiries`, `students`, `audit_log` (3, down from 7 — ADR-24) | **Open** |
| [`enquiries`](#enquiries) | Supabase, ADR-18 (2026-07-23) | None (0, since ADR-23) | `students.enquiry_id` | **Open** |
| [`students`](#students) | Supabase, ADR-19 (2026-07-23) | None (0, since ADR-25) | `memberships.student_id`, `payments.student_id` | **Open** |
| [`memberships`](#memberships) | Supabase, ADR-20 (2026-07-23) | None (0, since ADR-25) | `payments.membership_id` | **Open** |
| [`payments`](#payments) | Supabase, ADR-25 (2026-07-24) | None (0) | `cashbook.payment_id` (Supabase FK only — see below) | **Open** |
| [`cashbook`](#cashbook) | Supabase, ADR-22 (2026-07-23) | `database/migrate_backfill_cashbook_payments.py` (reconciliation script, not a live route) (1) | `audit_log.entry_id` | **Open** |
| [`audit_log`](#audit_log) | Supabase, ADR-22 (2026-07-23) | None (existence-only for the SQLite copy — see below) | none | **Open** |

`enquiries.status` and `admins.password` are **not** split anymore — both closed (TD-36 `Resolved` via ADR-19, TD-35 `Resolved` via ADR-17) — see each mirror's section for which columns still mirror-sync vs. which have a single Supabase-only writer.

---

## `admins` (existence-only bridge)

**Source of truth:** Supabase `admins` table, since ADR-16 (2026-07-23). Every actual read (login, forgot-password, Security Settings' password change) goes to Supabase.

**SQLite mirror's role:** row *existence* only — the mirror row's column values (other than `admin_id`) are never read back by any route. It exists purely so a handful of other SQLite tables' `FOREIGN KEY (admin_id) REFERENCES admins(admin_id)` constraints resolve when those tables insert a row for a newly-registered admin.

**Current readers:** None. No route or query module `SELECT`s from SQLite `admins` for any business logic.

**Current writers:** `routes/auth.py`'s `register()` — inserts into Supabase first, then mirrors the identical row (`admin_id`, `full_name`, `username`, `mobile`, `email`, hashed `password`, `role`) into SQLite via `database.db.get_connection()`, rolling back the Supabase insert if the SQLite insert raises `sqlite3.Error`. `login()`/`forgot_password()` and `routes/setting.py`'s `security_settings()` password branch touch Supabase's `admins.password` only — they never write SQLite (TD-35, `Resolved` via ADR-17).

**Why the mirror still exists:** 3 tables enforce a real SQLite FK to `admins.admin_id` and are actively inserted into on every request that touches them: `enquiries` (`routes/enquiries.py`'s `add()` mirror-insert), `students` (`routes/student.py`'s `admission()` mirror-insert), `audit_log` (written transitively by `routes/cashbook.py`/`routes/membership.py`/`routes/payment.py` via `database/cashbook_queries.py`'s `insert_income_entry()`/`insert_transaction()` → `database/audit_queries.py`'s `log_entry()`). Migrating `enquiries`/`students` at the *route* level (ADR-18/ADR-19) did **not** remove them from this list — both still insert their own SQLite mirror rows referencing `admin_id`, so the FK still fires. `audit_log` joined them 2026-07-23 (ADR-22): its reads moved to Supabase too, but `log_entry()`'s SQLite mirror-write is completely unchanged, so it didn't shrink this list either. **`library_settings`/`membership_settings`/`backup_log`/`security_settings` dropped off this list entirely 2026-07-24 (ADR-24)** — unlike `enquiries`/`students`/`audit_log`, they don't just have a Supabase-backed read side now, they stopped inserting into SQLite *at all* (no mirror kept, see the "Fully migrated, no mirror" section above), so their FK to `admins.admin_id` is never exercised by this app anymore. The bridge now needs only the remaining 3, unconditionally.

**Exact removal conditions (both required):**
1. **Read-side:** none — already zero readers.
2. **FK-side:** `audit_log` must be migrated to Supabase so it stops inserting into SQLite (i.e., `log_entry()`'s mirror-write removed, which needs `cashbook`'s own mirror gone first — see that section), **and** either the `enquiries`/`students` mirrors (below) must themselves be fully removed, or their mirror-inserts must stop being written (which requires those mirrors' own removal conditions first, both gated on `payments`). In practice: this bridge is still one of the *last* things removable — it's blocked on `payments` migrating (transitively, via `enquiries`/`students`) and on `cashbook`'s mirror coming down (transitively, via `audit_log`).

**Change history:**
- 2026-07-23 (ADR-16): bridge introduced — `register()`'s Supabase-only write broke 7 tables' SQLite FK on the very next admin who touched any of them (74 test failures caught this).
- 2026-07-23 (ADR-17): `admins.password`'s split-brain closed (TD-35 `Resolved`) — unrelated to this bridge, which covers row existence, not `password`.
- 2026-07-23 (post-ADR-22 full-codebase re-grep): re-verified against source — no production route/query module reads SQLite `admins` for any purpose (the only non-`register()` hits are `database/migrate.py`, a one-time script, and test files). List unchanged; `audit_log` remains one of the 7 FK dependents (see its own section — migrating its reads to Supabase, ADR-22, did not remove it from this list).
- 2026-07-24 (ADR-24): `library_settings`/`membership_settings`/`backup_log`/`security_settings` migrated to Supabase with no SQLite mirror kept at all (they're leaf tables, nothing downstream needed them) — dropped off this bridge's dependent list entirely, shrinking it from 7 to 3 (`enquiries`, `students`, `audit_log`).

---

## `enquiries`

**Source of truth:** Supabase `enquiries` table, since ADR-18 (2026-07-23), for `index()`/`add()`/`edit()`/`delete()`/`view()` in `routes/enquiries.py`.

**Columns mirror-synced:** `enquiry_id` (explicit, computed as SQLite `MAX(enquiry_id) + 1`, not Supabase's identity column — see ADR-18), `admin_id`, `full_name`, `mobile`, `purpose`, `preferred_shift`, `followup_date`, `remarks`, `demo_done`.
**Column deliberately *not* mirror-synced:** `status` — `routes/student.py`'s `admission()` writes `status='Admitted'` to **Supabase only** (TD-36, `Resolved` via ADR-19). The SQLite mirror's `status` column is stale/frozen at whatever `add()` last wrote and is read by nothing.

**Current readers (SQLite):** None (since ADR-23) — `routes/dashboard.py`'s enquiry count moved to a Supabase `count="exact", head=True` query.

**Current writers (SQLite):**
- `routes/enquiries.py`'s `add()` (mirror-insert, explicit `enquiry_id`), `edit()` (mirror-update, not best-effort), `delete()` (best-effort mirror-delete, swallows `sqlite3.Error` if an already-admitted student's `students.enquiry_id` FK blocks it — see TD-36's row in [11_FUTURE_WORK.md](11_FUTURE_WORK.md) for that specific leftover-row edge case).

**Why the mirror still exists:**
- **Read-side:** none — zero readers as of ADR-23.
- **FK-side:** `students.enquiry_id` is a real SQLite FK. `routes/student.py`'s `admission()` inserts a SQLite `students` mirror row (ADR-19) that references `enquiry_id` — that insert requires the `enquiries` row to already exist in SQLite. (Note: `admission()` itself no longer *reads* the enquiries mirror — as of ADR-19 it reads/writes the `enquiries` row it needs directly against Supabase — but its SQLite `students` insert still needs the SQLite `enquiries` row to exist for the FK to resolve.)

**Exact removal conditions (both required):**
1. **Read-side:** already done (ADR-23) — zero readers remain.
2. **FK-side:** the `students` mirror (below) must stop inserting rows with a real `enquiry_id` FK reference — i.e., either `students`' own mirror is fully removed (see its section), or `students.enquiry_id`'s FK constraint is dropped/relaxed. This is the only thing still blocking this mirror's removal.

**Change history:**
- 2026-07-23 (ADR-18): mirror introduced — needed as an ongoing two-way sync (not a one-shot bridge like `admins`'), since `admission()` (at the time) read live enquiry field values from SQLite, not just row existence.
- 2026-07-23 (ADR-19): `status` column's writer moved to Supabase-only, closing TD-36. `admission()` stopped reading this mirror's field values (`full_name`/`mobile`/`purpose`/`preferred_shift`) — it now reads Supabase directly. Mirror itself (row existence + non-`status` columns) remained required, for the two reasons listed above.
- 2026-07-23 (post-ADR-22 full-codebase re-grep): re-verified against source — `routes/dashboard.py` is still the only production reader of SQLite `enquiries`; no additional reader surfaced (unlike `students`/`memberships`, see their sections). List unchanged.
- 2026-07-23 (ADR-23): `routes/dashboard.py`'s enquiry count migrated to Supabase (`.select("enquiry_id", count="exact", head=True).eq("admin_id", admin_id)`) — this mirror's read-side condition is now fully satisfied. Still blocked purely on the FK-side (`students` mirror).

---

## `students`

**Source of truth:** Supabase `students` table, since ADR-19 (2026-07-23), for `index()`/`admission()`/`view()`/`edit()` in `routes/student.py`.

**Columns mirror-synced:** every column — `student_id` (explicit, `MAX(student_id) + 1`, same reasoning as `enquiries.enquiry_id`), `admin_id`, `enquiry_id`, `full_name`, `mobile`, `address`, `id_proof`, `purpose`, `shift`, `join_date`, `status`. Unlike `enquiries`, there is no held-back column — `admission()`/`edit()` write both databases in full, since `students.status` has no split-brain risk analogous to `enquiries.status` (nothing else writes it).

**Current readers (SQLite):** None (query-based) — see change history for the ADR-25 closure. `routes/setting.py`'s `backup_create()` still consumes this mirror via a whole-file copy, not a query — tracked separately, since it's a non-query concern (see Phase 11 planning).

**Migrated to Supabase by ADR-23 (2026-07-23):** `routes/dashboard.py` (total-students count, upcoming-expiries, recent-admissions — now via `database.membership_queries.get_admin_students()`/`get_memberships_for_admin()`), `routes/membership_distribution.py`'s `index()` (total/plan-wise counts and the listing's non-payment columns), `routes/notification.py`'s `get_notification_summary()`, `database/bi_queries.py` (`get_monthly_new_memberships()`/`get_membership_retention()`/`get_upcoming_expiries()`), `database/cashbook_queries.py`'s `get_pending_fees()`, `database/membership_queries.py`'s `get_membership_counts()`, `utils/charts.py`'s `generate_membership_chart()`/`generate_membership_distribution_donut()`, `routes/enquiries.py`'s `index()`/`view()`/`delete()`, and `routes/student.py`'s own `index()` self-join.

**Migrated to Supabase by ADR-24 (2026-07-24):** `routes/setting.py`'s `backup_export_csv()` (its `students` CSV export).

**Migrated to Supabase by ADR-25 (2026-07-24), closing the last 3 readers:** `routes/payment.py`'s `index()`, `database/payment_queries.py`'s `generate_receipt_number()` fallback branch, and `utils/charts.py`'s `generate_revenue_chart()` — all three via the new `database.payment_queries.get_payments_for_admin()` helper, now that `payments` itself has a Supabase copy.

**Not** a reader: `routes/membership.py` — migrated off this list by ADR-20 (its own student lookups go through Supabase). `routes/payment.py`'s `collect()` — migrated off this list by ADR-21 (its ownership check now reads Supabase `students`).

**Current writers (SQLite):** `routes/student.py`'s `admission()` (mirror-insert, explicit `student_id`), `edit()` (mirror-update, not best-effort).

**Why the mirror still exists:**
- **Read-side:** none, as of ADR-25 — zero query-based readers. `routes/setting.py`'s `backup_create()`'s whole-file copy is the only remaining consumer, tracked separately.
- **FK-side:** `memberships.student_id` and `payments.student_id` are both still real SQLite FKs, and both tables' SQLite mirror-writes are unchanged by ADR-25 (`payments` migrating added a Supabase mirror-write, it did not remove the SQLite one) — `routes/membership.py`'s `create()`/`renew()` and `database/payment_queries.py`'s `record_payment()` both still insert into their SQLite mirrors on every membership/payment, referencing `student_id` each time.

**Exact removal conditions (both required):**
1. **Read-side:** done as of ADR-25 (query-based). `routes/setting.py`'s `backup_create()` still needs a plan for what "backup" means once SQLite itself is removed (Phase 11 concern, not a read to migrate).
2. **FK-side:** `routes/membership.py`'s `create()`/`renew()` and `database/payment_queries.py`'s `record_payment()` must stop writing their SQLite mirrors (`memberships`, `payments`) — this is a **write-path** decision now, not a migration-of-a-reader decision, since every read is already closed. See Phase 10 (Mirror Removal) for whether/when to make that call.

**Change history:**
- 2026-07-23 (ADR-19): mirror introduced, widest fan-out found so far (8 modules at the time). Closed TD-36 at the source (`admission()`'s `enquiries.status` write moved to Supabase). `enquiries` mirror confirmed still required, independent of this migration.
- 2026-07-23 (ADR-20): `routes/membership.py` migrated off the reader list (its own student lookups moved to Supabase).
- 2026-07-23 (ADR-21): `routes/payment.py`'s `collect()` migrated off the reader list (ownership check moved to Supabase); `routes/payment.py`'s `index()` remains a reader. Re-verifying the full list against source (not against ADR-19's original prose) also surfaced `routes/setting.py`'s `backup_export_csv()`/`backup_create()` and `routes/enquiries.py`'s read-only lookups explicitly, which prior summaries had described narratively but this file now lists exhaustively.
- 2026-07-23 (post-ADR-22 full-codebase re-grep): widened from 9 to 11 tracked consumers — `utils/charts.py` (3 chart functions) and `database/payment_queries.py`'s `generate_receipt_number()` fallback branch were both real, executable SQLite readers that no prior version of this file named explicitly. Also documented `routes/student.py`'s own `index()` self-join against SQLite `students`, previously described only as a `memberships` read. No removal condition changed as a result — a completeness correction.
- 2026-07-23 (ADR-23): shrank from 11 to 4 tracked consumers in one slice — see ADR-23 in [DECISIONS.md](DECISIONS.md). The 4 remaining readers were gated on either `payments` migrating (`routes/payment.py`'s `index()`, `database/payment_queries.py`'s receipt-fallback branch, `utils/charts.py`'s `generate_revenue_chart()`) or Settings migrating (`routes/setting.py`'s backup functions).
- 2026-07-24 (ADR-24): `routes/setting.py`'s `backup_export_csv()` migrated to Supabase while Settings was already being touched for the 4 Settings tables — shrinking the tracked query-based reader list from 4 to 3, all now gated purely on `payments`.
- 2026-07-24 (ADR-25): `payments` itself migrated to Supabase, closing all 3 remaining readers in one slice. Read-side condition now fully satisfied — only the FK-side (SQLite mirror-*writes*, not reads) remains open. Backfilling `payments` also surfaced and fixed **TD-42**: Supabase `students` (and `enquiries`/`memberships`) had a large pre-existing gap of rows never copied from SQLite, unrelated to this mirror's reader list but a real data-integrity issue this slice's investigation caught — see ADR-25 and TD-42 in [11_FUTURE_WORK.md](11_FUTURE_WORK.md).

---

## `memberships`

**Source of truth:** Supabase `memberships` table, since ADR-20 (2026-07-23), for `index()`/`create()`/`renew()` in `routes/membership.py`, and since ADR-21 (2026-07-23) for `paid_amount`/`pending_amount` specifically in `routes/payment.py`'s `collect()`.

**Columns mirror-synced:** every column, from two different writers — `routes/membership.py`'s `create()`/`renew()` write the full row (`membership_id`, explicit `MAX(membership_id) + 1`; `student_id`, `plan_name`, `joining_date`, `duration_days`, `end_date`, `total_fee`, `paid_amount`, `pending_amount`, `remarks`, `membership_status`); `routes/payment.py`'s `collect()` writes only `paid_amount`/`pending_amount` on an existing row (it never inserts a new membership row).

**Current readers (SQLite):** None, as of ADR-25.

**Migrated to Supabase by ADR-23 (2026-07-23):** `routes/dashboard.py` (upcoming-expiries, recent-admissions), `database/membership_queries.py`'s `get_membership_counts()`, `routes/membership_distribution.py`'s `index()` (full membership listing's non-payment columns, plus `get_membership_counts()`), `routes/notification.py`'s `get_notification_summary()`, `routes/student.py`'s own `index()` self-join, `database/cashbook_queries.py`'s `get_pending_fees()`, `database/bi_queries.py` (`get_monthly_new_memberships()`/`get_membership_retention()`/`get_upcoming_expiries()`), and `utils/charts.py`'s `generate_membership_chart()`/`generate_membership_distribution_donut()`.

**Migrated to Supabase by ADR-25 (2026-07-24), closing the last reader:** `routes/student.py`'s `view()` — now reads both Supabase `memberships` (latest row for this student) and Supabase `payments` (this student's full payment history) directly, since `payments` migrating in the same slice removed the reason this one held out during ADR-23.

**Not** a reader: `routes/payment.py`'s `collect()` — as of ADR-21 it reads the membership from Supabase, not SQLite, before updating either. `routes/payment.py`'s `index()` never touches `memberships` at all (only `payments`/`students`).

**Current writers (SQLite):** `routes/membership.py`'s `create()`/`renew()` (full mirror), `routes/payment.py`'s `collect()` (`paid_amount`/`pending_amount` only, added ADR-21).

**Why the mirror still exists:**
- **Read-side:** none, as of ADR-25 — zero readers.
- **FK-side:** `payments.membership_id` is a real SQLite FK, and `payments`' own SQLite mirror-write (`database/payment_queries.py`'s `record_payment()`) is unchanged by ADR-25 — it still inserts into SQLite `payments` on every membership creation/renewal/collection, referencing `membership_id`, so the SQLite `memberships` row this mirror maintains still needs to exist for that insert's FK to resolve.

**Exact removal conditions (both required):**
1. **Read-side:** done as of ADR-25 — zero readers remain.
2. **FK-side:** `routes/membership.py`'s `create()`/`renew()` and `database/payment_queries.py`'s `record_payment()` must stop writing their SQLite mirrors — a write-path decision for Phase 10 (Mirror Removal), not a reader-migration.

**Change history:**
- 2026-07-23 (ADR-20): mirror introduced. `routes/payment.py`'s `collect()`, `routes/dashboard.py`, `routes/membership_distribution.py`, `routes/notification.py` named as remaining readers — this list was **incomplete** (see ADR-21's correction below).
- 2026-07-23 (ADR-21): `routes/payment.py`'s `collect()` migrated off the reader list and onto the writer list for `paid_amount`/`pending_amount` (closing TD-37). Re-verifying the dependency graph directly against source (not against ADR-20's prose) found ADR-20's reader list had missed `routes/student.py`'s `view()`, `database/cashbook_queries.py`'s `get_pending_fees()`, and `database/bi_queries.py` — all three added to this file's tracked list, none of them touched by ADR-21, all still `Open`.
- 2026-07-23 (post-ADR-22 full-codebase re-grep): widened from 6 to 7 tracked consumers — `utils/charts.py`'s `generate_membership_chart()`/`generate_membership_distribution_donut()` were real, executable SQLite readers not previously named (same class of gap as `students`' section), and `routes/student.py`'s own `index()` self-join was clarified as a second, independent `memberships` read distinct from `view()`. No removal condition changed (still blocked on `payments`) — a completeness correction, not a new blocker.
- 2026-07-23 (ADR-23): shrank from 7 to 1 tracked consumer in one slice — every reader except `routes/student.py`'s `view()` migrated to Supabase via the new shared `get_memberships_for_admin()` helper (see ADR-23 in [DECISIONS.md](DECISIONS.md)).
- 2026-07-24 (ADR-25): `routes/student.py`'s `view()` migrated, closing the last reader — read-side condition now fully satisfied, only the FK-side (SQLite mirror-writes) remains open.

---

## `payments`

**Source of truth:** Supabase `payments` table, since ADR-25 (2026-07-24), for every read across the app (`routes/payment.py`'s `index()`, `routes/student.py`'s `view()`, `utils/charts.py`'s `generate_revenue_chart()`, `database/cashbook_queries.py`'s `get_today_fee_collection()`/`get_total_fee_revenue()`, `routes/membership_distribution.py`'s per-row receipt columns, `database/payment_queries.py`'s own receipt-fallback branch).

**Columns mirror-synced:** every column — `payment_id` (explicit, computed as SQLite `MAX(payment_id) + 1`, the same reasoning as `enquiry_id`/`student_id`/`membership_id`/`entry_id` in ADR-18/19/20/22), `membership_id`, `student_id`, `receipt_number`, `payment_mode`, `amount_paid`, `payment_date`, `remarks`.

**Current readers (SQLite):** None — `_receipt_number_taken()` (`database/payment_queries.py`) still queries SQLite `payments` for the global-uniqueness check inside `generate_receipt_number()`, deliberately: SQLite is the immediately-consistent primary write, and the Supabase mirror-write is best-effort (see below), so checking against SQLite avoids a false negative if a recent mirror-write is still catching up (or failed outright). This is not a "reader" in the mirror-removal sense — it's a correctness-critical internal check that stays on the primary write path by design, not a stale consumer waiting to be migrated.

**Current writers (SQLite):** `database/payment_queries.py`'s `record_payment()` — SQLite is the **primary, unchanged** write (called from `routes/membership.py`'s `create()`/`renew()` and `routes/payment.py`'s `collect()`, both out of scope for this slice — same reasoning ADR-22 established for `insert_income_entry()`), and the identical row is best-effort mirrored into Supabase afterward, swallowing `postgrest.exceptions.APIError` (TD-41).

**Why the mirror still exists:**
- **Read-side:** none — already zero.
- **FK-side:** `cashbook.payment_id` is a live *Supabase* FK (not SQLite) — see `cashbook`'s section below for why this migration is what let `insert_income_entry()` start sending a real `payment_id` there (closing TD-38's common case). On the SQLite side, nothing FKs to `payments.payment_id` at all, so there's no FK-side blocker here — but `payments` itself still needs `memberships`/`students`' SQLite mirrors to exist for its *own* SQLite insert's FKs (`membership_id`, `student_id`) to resolve, which is why those two mirrors' FK-side conditions (see their own sections) are gated on `payments`' SQLite write stopping, not the other way around.

**Exact removal conditions (both required):**
1. **Read-side:** already done — zero readers.
2. **FK-side:** `record_payment()` must stop writing the SQLite mirror — a write-path decision for Phase 10 (Mirror Removal), which also then finally frees `memberships`/`students`' own SQLite mirrors from their last FK dependent.

**Change history:**
- 2026-07-24 (ADR-25): mirror introduced. Backfilling it first required fixing a much larger, previously-undocumented gap in `enquiries`/`students`/`memberships`' own Supabase parity (**TD-42**, `Resolved` in the same slice) — see `database/migrate_backfill_mirror_parity.py` and ADR-25 in [DECISIONS.md](DECISIONS.md). Closed the last 3 `students`-mirror readers and the last 1 `memberships`-mirror reader in the same slice, since all four were gated on this table migrating.

---

## `cashbook`

**Source of truth:** Supabase `cashbook` table, since ADR-22 (2026-07-23), for `index()`/`add_transaction()`/`edit_transaction()` in `routes/cashbook.py`, and for every getter in `database/cashbook_queries.py` (totals, monthly series, category breakdowns, payment-method distribution, cash balance, the paginated ledger).

**Columns mirror-synced:** every column, including `payment_id` for automatic entries as of 2026-07-24 (ADR-25) — `entry_id` (explicit, computed as SQLite `MAX(entry_id) + 1`, the same reasoning as `enquiry_id`/`student_id`/`membership_id` in ADR-18/19/20), `admin_id`, `type`, `category`, `person`, `description`, `amount`, `payment_method`, `entry_date`, `reference_id`, `source`, `payment_id`. Before ADR-25, `payment_id` was written to the SQLite mirror for automatic entries (`insert_income_entry()`) but never sent to Supabase — Supabase's `cashbook.payment_id` has a real Postgres FK to `payments`, and `payments` was still SQLite-only, so a real `payment_id` there always failed with a `23503` FK violation (verified live, TD-38). Now that `payments` has a Supabase row (ADR-25, also best-effort), `payment_id` is sent — best-effort, so if that payments mirror-write happened to fail moments earlier, this insert falls back to the same best-effort miss described below (TD-41).

**Current readers (SQLite)** — verified directly against source:
- `database/migrate_backfill_cashbook_payments.py` — a one-time reconciliation script (not called from any live route), matches `payments` rows to `cashbook` rows by `(admin_id, person, amount, entry_date)` for pre-`payment_id` historical rows. Reads SQLite directly.
- No live route or `database/*_queries.py` module reads the SQLite `cashbook` mirror for actual ledger/KPI data any more — `routes/cashbook.py`/`database/cashbook_queries.py`'s own getters, and `database/bi_queries.py` (via `get_monthly_income`/`get_monthly_expense`/`get_income_category_totals`/`get_expense_category_totals`/`get_recent_transactions`, all re-exported from `cashbook_queries.py`), all now read Supabase.

**Current writers (SQLite):** `database/cashbook_queries.py`'s `insert_transaction()` (mirror-write, strict — rolled back if it fails, since Supabase is written first), `insert_income_entry()` (primary write, unchanged from pre-migration — Supabase is the best-effort mirror here, not the other way around, see ADR-22's "Why `insert_income_entry()` couldn't just adopt the strict...` section), `update_manual_transaction()` (mirror-write, strict).

**Why the mirror still exists:**
- **Read-side:** `database/migrate_backfill_cashbook_payments.py` (above) — a script, not a request-path reader, but still a real consumer of SQLite `cashbook` rows/columns (including `payment_id`) if ever re-run.
- **FK-side:** `audit_log.entry_id` is a real SQLite FK to `cashbook.entry_id`. `database/audit_queries.py`'s `log_entry()` inserts a SQLite `audit_log` row on every single cashbook write (manual or automatic), referencing `entry_id` — that insert requires the SQLite `cashbook` row to already exist.

**Exact removal conditions (both required):**
1. **Read-side:** confirm `database/migrate_backfill_cashbook_payments.py` will never be re-run against current data (or update it to read Supabase/SQLite's `payments` — whichever hasn't migrated yet — instead).
2. **FK-side:** `audit_log`'s own SQLite mirror (below) must stop inserting rows with a real `entry_id` FK reference — i.e., either that mirror is fully removed, or `audit_log.entry_id`'s FK is dropped/relaxed.

**Change history:**
- 2026-07-23 (ADR-22): mirror introduced. Automatic entries (`insert_income_entry()`) keep the SQLite write as primary and best-effort mirror to Supabase, unlike every prior slice's "Supabase first, roll back on SQLite failure" shape — because that function's caller (`database/payment_queries.py`'s `record_payment()`, called from `routes/membership.py`/`routes/payment.py`) is out of scope and can't be given a new caught exception type. Manual entries (`insert_transaction()`, called directly from the in-scope `routes/cashbook.py`) do use the strict Supabase-first shape. Introduced TD-38 (`payment_id` can't round-trip through Supabase for automatic entries) and TD-39 (best-effort mirror can leave a narrow, bounded staleness window on Supabase after a transient failure).
- 2026-07-23 (post-ADR-22 full-codebase re-grep): re-verified against source — `database/migrate_backfill_cashbook_payments.py` is confirmed the only remaining reader of raw SQLite `cashbook` anywhere outside `cashbook_queries.py`/tests (it is a one-time reconciliation script, not on the live request path). List unchanged.
- 2026-07-24 (ADR-25): `payments` migrated to Supabase, letting `insert_income_entry()` start sending a real `payment_id` to Supabase `cashbook` (closing **TD-38**'s common case — best-effort, so a rare Supabase blip can still leave a gap here, tracked as **TD-41**). This mirror's own removal conditions are unchanged by ADR-25 — still gated on `audit_log`'s mirror.

---

## `audit_log`

**Source of truth:** Supabase `audit_log` table, since ADR-22 (2026-07-23), for `database/audit_queries.py`'s `get_recent_audit_log()` — the only reader, called from `routes/cashbook.py`'s `index()` for the "Audit Trail" activity log.

**SQLite mirror's role:** unlike `cashbook`, this mirror carries **every** column (there's no held-back field analogous to `payment_id`) but has **zero application-level readers** — `log_entry(cursor, ...)` (`database/audit_queries.py`) is a pure mirror-write, called from `cashbook_queries.py`'s `insert_transaction()`/`insert_income_entry()`/`update_manual_transaction()` on every cashbook write, same transaction. Nothing in the app ever reads the SQLite copy back.

**Current readers (SQLite):** None.

**Current writers (SQLite):** `database/audit_queries.py`'s `log_entry(cursor, admin_id, entry_id, action, details)` — called by every write path in `database/cashbook_queries.py` (unconditionally, not best-effort — the SQLite `audit_log` row is written in the same local transaction as the SQLite `cashbook` row it documents, exactly as before this migration).

**Why the mirror still exists:**
- **Read-side:** none — already zero readers.
- **FK-side:** `audit_log.admin_id` is a real SQLite FK to `admins.admin_id`, and `audit_log.entry_id` is a real SQLite FK to `cashbook.entry_id` — both still enforced (`PRAGMA foreign_keys = ON`, `database/db.py`), and `log_entry()` still fires on every single cashbook write. This is exactly the FK dependency `routes/auth.py`'s `register()` mirror-insert bridge (see `admins`' section above) exists for — migrating `audit_log` at the route/read level did **not** remove it from that bridge's dependent list (7 tables at the time, ADR-22; now 3 after ADR-24 dropped the 4 Settings tables), the same way migrating `enquiries`/`students` at the route level didn't remove them (ADR-18/19).

**Exact removal conditions (both required):**
1. **Read-side:** none — already zero.
2. **FK-side:** `cashbook`'s own SQLite mirror (above) must be fully removed, **and** the `admins` bridge's other FK dependents must clear too (see the `admins` section's own removal conditions — this table is one of its 7).

**Change history:**
- 2026-07-23 (ADR-22): mirror's *reads* moved to Supabase (`get_recent_audit_log()`); the mirror-write itself (`log_entry()`) is unchanged from before this migration, kept as a pure SQLite write with no application reader, purely to satisfy `cashbook.entry_id`'s and `admins.admin_id`'s SQLite FKs.
- 2026-07-23 (post-ADR-22 full-codebase re-grep): re-verified against source — zero reads of raw SQLite `audit_log` anywhere outside `audit_queries.py` itself (which only writes it) and test files. List unchanged.

---

## Non-mirror unmigrated tables that gate the mirrors above

These have **no Supabase copy at all** — they are not mirrors, but they are exactly what's blocking every mirror's FK-side removal condition, so they're tracked here for completeness:

| Table | Written by | Blocks removal of |
|---|---|---|
| `payments` | `database/payment_queries.py`'s `record_payment()` (called from `routes/membership.py` and `routes/payment.py`) | `memberships` mirror (FK), `students` mirror (FK, transitively), `cashbook` mirror's `payment_id` column (Supabase FK — TD-38) |

Migrating `payments` is the single highest-leverage next migration for this file: it simultaneously helps close the FK-side of `memberships`, (transitively, once `students.student_id`'s reference through `payments` is gone) `students`, and lets `cashbook`'s Supabase mirror finally carry a real `payment_id` for automatic entries (closing TD-38, and letting `insert_income_entry()` adopt the strict Supabase-first shape, closing TD-39 too). `cashbook`/`audit_log` are no longer listed here — as of ADR-22 they're both Supabase-sourced mirrors themselves, tracked in their own sections above, not gating tables for something else. `library_settings`/`membership_settings`/`backup_log`/`security_settings` are no longer listed here either — as of ADR-24 they're fully migrated with no SQLite mirror at all (see the "Fully migrated, no mirror" section above), so `payments` is now the only table left in this list.

## Removal priority: state after the Payments migration (ADR-25)

The analytics slice (ADR-23), Settings slice (ADR-24), and Payments slice (ADR-25) are all **done**. This is the first time every read-side condition in this file is simultaneously closed — what's left is entirely FK-side, i.e. entirely about whether each mirror's SQLite *write* can stop, not about migrating any more readers.

Working through each of the 7 active mirrors' **both** conditions (read-side and FK-side — a mirror needs both clear, not just one):

| Mirror | Read-side after ADR-25 | FK-side after ADR-25 | Removable? |
|---|---|---|---|
| `admins` | Already 0 | Down to **3** bridge tables (`enquiries`/`students`/`audit_log`) | No — blocked on those 3 mirrors' own writes stopping |
| `enquiries` | **0** | Needs `students`' SQLite mirror-write to stop | No |
| `students` | **0** (closed by ADR-25) | Needs `routes/membership.py`'s `create()`/`renew()` and `database/payment_queries.py`'s `record_payment()` to stop writing their SQLite mirrors (`memberships`/`payments`) | No — but this is now a pure write-path decision, not a migration |
| `memberships` | **0** (closed by ADR-25) | Needs `database/payment_queries.py`'s `record_payment()` to stop writing its SQLite mirror (`payments`) | No — same, pure write-path decision |
| `payments` | **0** | No SQLite FK dependents at all (only a *Supabase* FK from `cashbook`, already satisfied) — the only remaining question is whether `record_payment()` itself should stop writing SQLite | No — but the *only* blocker is `record_payment()`'s own write, nothing downstream |
| `cashbook` | Already effectively 0 (only a dormant reconciliation script) | Needs `audit_log`'s SQLite mirror-write to stop | No |
| `audit_log` | Already 0 | Needs `cashbook`'s mirror-write to stop **and** the `admins` bridge's other 2 dependents (`enquiries`/`students`) cleared | No |

**Conclusion:** every mirror in this file is now read-side-closed. The entire remaining question is a single, connected write-path decision: do `routes/enquiries.py`'s `add()`/`edit()`/`delete()`, `routes/student.py`'s `admission()`/`edit()`, `routes/membership.py`'s `create()`/`renew()`, `routes/payment.py`'s `collect()`, and `database/payment_queries.py`'s `record_payment()` stop writing their SQLite mirrors? Nothing reads any of those mirrors anymore — the only thing still requiring them is each other, transitively, down the FK chain (`admins` ← `enquiries`/`students`/`audit_log`; `students`/`enquiries` ← `memberships`/`payments`'s SQLite inserts; `cashbook` ← `audit_log`'s SQLite insert). This is exactly Phase 9 (Final Dependency Audit) and Phase 10 (Mirror Removal)'s job — verify this conclusion directly against source one more time (per this file's own maintenance rule), then remove the SQLite mirror-writes in dependency order.

**Practical recommendation, in order:**
1. ~~Do the analytics migration slice~~ — **done** (ADR-23, 2026-07-23).
2. ~~Migrate Settings~~ — **done** (ADR-24, 2026-07-24).
3. ~~Migrate `payments`~~ — **done** (ADR-25, 2026-07-24). Closed every remaining reader in this file, and surfaced/fixed a pre-existing Supabase parity gap in `enquiries`/`students`/`memberships` (TD-42).
4. Run the Phase 9 dependency audit directly against source (not against this file's own claims) to confirm every mirror really is read-side-closed.
5. Remove SQLite mirror-writes in FK-safe order (Phase 10): `payments` (frees `memberships`/`students`' last FK dependent) → `memberships`/`students`/`enquiries` mirror-writes → `audit_log`/`cashbook` mirror-writes → `admins` bridge (`register()`'s mirror-insert) last, since it's downstream of all three remaining dependents.
6. Once every mirror-write is gone, Phase 11 removes SQLite entirely.

## Related reading

- [DECISIONS.md](DECISIONS.md) — ADR-16 through ADR-25, the full reasoning behind each slice.
- [11_FUTURE_WORK.md](11_FUTURE_WORK.md) — TD-34 (schema-drift risk), TD-35/TD-36/TD-37 (the three split-brain bugs each mirror slice risked, all now `Resolved`), TD-42 (the Supabase parity gap ADR-25 found and fixed).
- [09_DEPENDENCY_MAP.md](09_DEPENDENCY_MAP.md) — the literal import graph this file's "Current readers"/"Current writers" lists are derived from.
- [04_DATABASE_SCHEMA.md](04_DATABASE_SCHEMA.md) — full FK list per table.




## Hidden Dependencies Found During Re-Grep

Date
Reason discovered
Previous documentation missed
Corrected by