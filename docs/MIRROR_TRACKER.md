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

`database/schema.sql` declares this FK graph. As of ADR-22 (2026-07-23), `cashbook` and `audit_log` are Supabase-sourced-of-truth mirrors like `admins`/`enquiries`/`students`/`memberships` (see their own sections below). As of ADR-24 (2026-07-24), `library_settings`/`membership_settings`/`backup_log`/`security_settings` are fully migrated too — but unlike every table above, they were dropped as **mirrors entirely** rather than shrunk to one, since nothing else in this FK graph references them (see the "Fully migrated, no mirror" section below). Only `payments`, `expenses`, `settings`, `transactions` still exist **only** in SQLite, with no Supabase copy read/written by any route (they are not mirrors, they're simply unmigrated):

```
admins  <──admin_id── enquiries, students, audit_log   (3 tables — library_settings/
                       membership_settings/backup_log/security_settings dropped off
                       this list entirely by ADR-24, see below)
enquiries <──enquiry_id── students
students  <──student_id──  memberships, payments
memberships <──membership_id── payments
payments  <──payment_id── cashbook        (Supabase enforces this FK too — see cashbook's section:
                                            this is why cashbook's Supabase mirror can't carry a real
                                            payment_id until payments itself migrates, TD-38)
cashbook  <──entry_id── audit_log        (audit_log also FKs admin_id → admins directly)
```

Consequence: a mirror can only be deleted once **every** table downstream of it in this chain either (a) no longer inserts into SQLite at all (i.e., it's been migrated to Supabase too), or (b) has had its FK constraint dropped. Concretely: `payments` is unmigrated and actively written on every single membership/payment transaction, and `cashbook`/`audit_log` (though now Supabase-sourced for reads) still keep a SQLite mirror actively written on every single membership/payment/cashbook transaction too — so as long as they exist in their current form, the `memberships`/`students`/`enquiries`/`admins` rows their `INSERT`s reference **must** keep existing in SQLite, independent of whether anything still *reads* those mirrors. This is why each mirror's removal conditions below have two parts, not one.

## Fully migrated, no mirror: `library_settings`, `membership_settings`, `backup_log`, `security_settings`

As of ADR-24 (2026-07-24), these four tables are **not** tracked as mirrors below, because they never became one — `database/settings_queries.py`/`receipt_settings_queries.py`/`notification_settings_queries.py` (`library_settings`), `database/membership_settings_queries.py`, `database/backup_queries.py`, and `database/security_settings_queries.py` read/write Supabase exclusively, with **zero** SQLite reads or writes left in any of them. This was possible in one step (unlike `admins`/`enquiries`/`students`/`memberships`/`cashbook`, which each needed an ongoing mirror) because these four tables are leaf nodes in the FK graph above — nothing else in `schema.sql` declares a foreign key against any of them, so there was never a downstream unmigrated table that needed their SQLite row to keep existing. `database/migrate_backfill_settings_to_supabase.py` synced SQLite's more-current data into Supabase (a plain `admin_id`-keyed upsert, not the explicit-id/rollback machinery `enquiries`/`students`/`memberships`/`cashbook` needed) before the code cutover — see ADR-24. Their old SQLite tables still physically exist (rows frozen at whatever they held at migration time) until Phase 11 (SQLite removal) drops them along with everything else.

This closed 4 of the `admins` bridge's original 7 FK dependents in one slice — see that section below.

## Summary

| Mirror table | Source of truth since | Readers remaining | FK dependents still requiring it | Status |
|---|---|---|---|---|
| [`admins`](#admins-existence-only-bridge) | Supabase, ADR-16 (2026-07-23) | None (existence-only) | `enquiries`, `students`, `audit_log` (3, down from 7 — ADR-24) | **Open** |
| [`enquiries`](#enquiries) | Supabase, ADR-18 (2026-07-23) | None (0, since ADR-23) | `students.enquiry_id` | **Open** |
| [`students`](#students) | Supabase, ADR-19 (2026-07-23) | 3 modules/functions (see below), down from 11 (ADR-23/24) | `memberships.student_id`, `payments.student_id` | **Open** |
| [`memberships`](#memberships) | Supabase, ADR-20 (2026-07-23) | `routes/student.py`'s `view()` (1), down from 7 (ADR-23) | `payments.membership_id` | **Open** |
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

**Current readers (SQLite)** — re-verified directly against source on 2026-07-23 (post-ADR-23 re-grep), by grepping every `.py` file outside `tests/`/`migrate_*.py` for `FROM students`/`JOIN students`:
- `routes/payment.py`'s `index()` — `payments p INNER JOIN students s`. Still SQLite: `payments` is unmigrated.
- `routes/setting.py`'s `backup_create()` — copies the entire `library.db` file (a coarser, non-query form of consuming this mirror — see TD-32 for the unrelated cross-tenant issue in that same route). Not a `SELECT`, so not counted among the tracked query-based readers below, but a real consumer if the SQLite mirror were ever removed. **`backup_export_csv()` migrated to Supabase 2026-07-24 (ADR-24)** — no longer a reader.
- `database/payment_queries.py`'s `generate_receipt_number()` — its no-Library-Profile-yet fallback branch (`SELECT COUNT(*) ... FROM payments p JOIN students s ON s.student_id = p.student_id WHERE s.admin_id = ?`) — still SQLite: needs `payments`.
- `utils/charts.py`'s `generate_revenue_chart()` — `payments p JOIN students s`, called from `routes/dashboard.py`. Still SQLite: needs `payments`. (Its sibling functions, `generate_membership_chart()`/`generate_membership_distribution_donut()`, migrated to Supabase in this same slice — see below.)

**Migrated to Supabase by ADR-23 (2026-07-23), no longer readers of this mirror:** `routes/dashboard.py` (total-students count, upcoming-expiries, recent-admissions — now via `database.membership_queries.get_admin_students()`/`get_memberships_for_admin()`), `routes/membership_distribution.py`'s `index()` (total/plan-wise counts and the listing's non-payment columns), `routes/notification.py`'s `get_notification_summary()`, `database/bi_queries.py` (`get_monthly_new_memberships()`/`get_membership_retention()`/`get_upcoming_expiries()`), `database/cashbook_queries.py`'s `get_pending_fees()`, `database/membership_queries.py`'s `get_membership_counts()`, `utils/charts.py`'s `generate_membership_chart()`/`generate_membership_distribution_donut()` (its third chart function, `generate_revenue_chart()`, is unchanged/still SQLite — needs `payments`), `routes/enquiries.py`'s `index()`/`view()`/`delete()` (all three now query Supabase `students` directly), and `routes/student.py`'s own `index()` self-join (now via `get_memberships_for_admin()`).

**Not** a reader: `routes/membership.py` — migrated off this list by ADR-20 (its own student lookups go through Supabase). `routes/payment.py`'s `collect()` — migrated off this list by ADR-21 (its ownership check now reads Supabase `students`); only `routes/payment.py`'s sibling function `index()` still reads the mirror.

**Current writers (SQLite):** `routes/student.py`'s `admission()` (mirror-insert, explicit `student_id`), `edit()` (mirror-update, not best-effort).

**Why the mirror still exists:**
- **Read-side:** the 3 modules/functions above (down from 11 pre-ADR-23, then 4 post-ADR-23, then 3 post-ADR-24), all gated on `payments` migrating. `routes/setting.py`'s `backup_create()` also still consumes this mirror via a whole-file copy, not a query — tracked separately, not part of this count.
- **FK-side:** `memberships.student_id` and `payments.student_id` are both real SQLite FKs. `routes/membership.py`'s `create()`/`renew()` insert SQLite `memberships` mirror rows (ADR-20) referencing `student_id`; `database/payment_queries.py`'s `record_payment()` (called from both `routes/membership.py` and `routes/payment.py`) inserts `payments` rows referencing `student_id` directly, on every single payment. `payments` is unmigrated and will keep needing this indefinitely until it's migrated too.

**Exact removal conditions (both required):**
1. **Read-side:** migrate the 3 remaining listed consumers (`routes/payment.py`'s `index()`, `database/payment_queries.py`'s receipt-fallback branch, `utils/charts.py`'s `generate_revenue_chart()` — all three gated on `payments`) to read Supabase instead; also update `routes/setting.py`'s `backup_create()` to no longer depend on a SQLite file snapshot (a separate, non-query concern — see Phase 11 planning).
2. **FK-side:** the `memberships` mirror must stop requiring `student_id` to exist in SQLite (see its own removal conditions — itself blocked on `payments`), **and** `payments` itself must be migrated to Supabase (removing its own SQLite `student_id` FK insert) or have that FK dropped.

**Change history:**
- 2026-07-23 (ADR-19): mirror introduced, widest fan-out found so far (8 modules at the time). Closed TD-36 at the source (`admission()`'s `enquiries.status` write moved to Supabase). `enquiries` mirror confirmed still required, independent of this migration.
- 2026-07-23 (ADR-20): `routes/membership.py` migrated off the reader list (its own student lookups moved to Supabase).
- 2026-07-23 (ADR-21): `routes/payment.py`'s `collect()` migrated off the reader list (ownership check moved to Supabase); `routes/payment.py`'s `index()` remains a reader. Re-verifying the full list against source (not against ADR-19's original prose) also surfaced `routes/setting.py`'s `backup_export_csv()`/`backup_create()` and `routes/enquiries.py`'s read-only lookups explicitly, which prior summaries had described narratively but this file now lists exhaustively.
- 2026-07-23 (post-ADR-22 full-codebase re-grep): widened from 9 to 11 tracked consumers — `utils/charts.py` (3 chart functions) and `database/payment_queries.py`'s `generate_receipt_number()` fallback branch were both real, executable SQLite readers that no prior version of this file named explicitly. Also documented `routes/student.py`'s own `index()` self-join against SQLite `students`, previously described only as a `memberships` read. No removal condition changed as a result — a completeness correction.
- 2026-07-23 (ADR-23): shrank from 11 to 4 tracked consumers in one slice — `routes/dashboard.py`, `routes/membership_distribution.py`, `routes/notification.py`, `database/bi_queries.py`, `database/cashbook_queries.py`'s `get_pending_fees()`, `database/membership_queries.py`'s `get_membership_counts()`, two of `utils/charts.py`'s three chart functions, `routes/enquiries.py`'s read-only lookups, and `routes/student.py`'s own `index()` self-join were all migrated to Supabase in this slice, via a new shared helper (`database.membership_queries.get_memberships_for_admin()`). The 4 remaining readers were gated on either `payments` migrating (`routes/payment.py`'s `index()`, `database/payment_queries.py`'s receipt-fallback branch, `utils/charts.py`'s `generate_revenue_chart()`) or Settings migrating (`routes/setting.py`'s backup functions) — see ADR-23 in [DECISIONS.md](DECISIONS.md).
- 2026-07-24 (ADR-24): `routes/setting.py`'s `backup_export_csv()` migrated to Supabase while Settings was already being touched for the 4 Settings tables — shrinking the tracked query-based reader list from 4 to 3, all now gated purely on `payments`. `backup_create()`'s whole-file SQLite copy still consumes this mirror, tracked separately (not a query).

---

## `memberships`

**Source of truth:** Supabase `memberships` table, since ADR-20 (2026-07-23), for `index()`/`create()`/`renew()` in `routes/membership.py`, and since ADR-21 (2026-07-23) for `paid_amount`/`pending_amount` specifically in `routes/payment.py`'s `collect()`.

**Columns mirror-synced:** every column, from two different writers — `routes/membership.py`'s `create()`/`renew()` write the full row (`membership_id`, explicit `MAX(membership_id) + 1`; `student_id`, `plan_name`, `joining_date`, `duration_days`, `end_date`, `total_fee`, `paid_amount`, `pending_amount`, `remarks`, `membership_status`); `routes/payment.py`'s `collect()` writes only `paid_amount`/`pending_amount` on an existing row (it never inserts a new membership row).

**Current readers (SQLite):**
- `routes/student.py`'s `view()` — `SELECT * FROM memberships WHERE student_id=? ORDER BY membership_id DESC LIMIT 1` (the Student detail page's membership card). The only remaining reader as of ADR-23.

**Migrated to Supabase by ADR-23 (2026-07-23), no longer readers of this mirror:** `routes/dashboard.py` (upcoming-expiries, recent-admissions), `database/membership_queries.py`'s `get_membership_counts()`, `routes/membership_distribution.py`'s `index()` (full membership listing's non-payment columns, plus `get_membership_counts()`), `routes/notification.py`'s `get_notification_summary()`, `routes/student.py`'s own `index()` (its separate self-join, distinct from `view()` above, which remains), `database/cashbook_queries.py`'s `get_pending_fees()`, `database/bi_queries.py` (`get_monthly_new_memberships()`/`get_membership_retention()`/`get_upcoming_expiries()`), and `utils/charts.py`'s `generate_membership_chart()`/`generate_membership_distribution_donut()` — all now read Supabase `students`/`memberships` via the new shared `database.membership_queries.get_memberships_for_admin()` helper.

**Not** a reader: `routes/payment.py`'s `collect()` — as of ADR-21 it reads the membership from Supabase, not SQLite, before updating either. `routes/payment.py`'s `index()` never touches `memberships` at all (only `payments`/`students`).

**Current writers (SQLite):** `routes/membership.py`'s `create()`/`renew()` (full mirror), `routes/payment.py`'s `collect()` (`paid_amount`/`pending_amount` only, added ADR-21).

**Why the mirror still exists:**
- **Read-side:** `routes/student.py`'s `view()` alone (down from 7 pre-ADR-23) — not migrated in this slice because it renders the raw membership row plus its full payment history from SQLite `payments` (unmigrated), rather than the `get_memberships_for_admin()` shape the rest of this slice used.
- **FK-side:** `payments.membership_id` is a real SQLite FK. `database/payment_queries.py`'s `record_payment()` inserts a `payments` row on every membership creation/renewal/collection, referencing `membership_id` — this fires from both `routes/membership.py` and `routes/payment.py`, on every payment, and will keep requiring the SQLite `memberships` row to exist until `payments` itself is migrated.

**Exact removal conditions (both required):**
1. **Read-side:** migrate `routes/student.py`'s `view()` to read Supabase instead — the one remaining consumer.
2. **FK-side:** `payments` must be migrated to Supabase (removing its SQLite `membership_id` FK insert) or that FK must be dropped. Since `database/payment_queries.py`'s `record_payment()` is shared by both `routes/membership.py` and `routes/payment.py`, migrating `payments` is a change to both routes, not one.

**Change history:**
- 2026-07-23 (ADR-20): mirror introduced. `routes/payment.py`'s `collect()`, `routes/dashboard.py`, `routes/membership_distribution.py`, `routes/notification.py` named as remaining readers — this list was **incomplete** (see ADR-21's correction below).
- 2026-07-23 (ADR-21): `routes/payment.py`'s `collect()` migrated off the reader list and onto the writer list for `paid_amount`/`pending_amount` (closing TD-37). Re-verifying the dependency graph directly against source (not against ADR-20's prose) found ADR-20's reader list had missed `routes/student.py`'s `view()`, `database/cashbook_queries.py`'s `get_pending_fees()`, and `database/bi_queries.py` — all three added to this file's tracked list, none of them touched by ADR-21, all still `Open`.
- 2026-07-23 (post-ADR-22 full-codebase re-grep): widened from 6 to 7 tracked consumers — `utils/charts.py`'s `generate_membership_chart()`/`generate_membership_distribution_donut()` were real, executable SQLite readers not previously named (same class of gap as `students`' section), and `routes/student.py`'s own `index()` self-join was clarified as a second, independent `memberships` read distinct from `view()`. No removal condition changed (still blocked on `payments`) — a completeness correction, not a new blocker.
- 2026-07-23 (ADR-23): shrank from 7 to 1 tracked consumer in one slice — every reader except `routes/student.py`'s `view()` migrated to Supabase via the new shared `get_memberships_for_admin()` helper (see ADR-23 in [DECISIONS.md](DECISIONS.md)). `routes/student.py`'s `view()` is now the single remaining reader and the natural next follow-up — it also reads SQLite `payments` for the same student, so migrating it fully is gated on `payments` too, same as this mirror's own FK-side condition.

---

## `cashbook`

**Source of truth:** Supabase `cashbook` table, since ADR-22 (2026-07-23), for `index()`/`add_transaction()`/`edit_transaction()` in `routes/cashbook.py`, and for every getter in `database/cashbook_queries.py` (totals, monthly series, category breakdowns, payment-method distribution, cash balance, the paginated ledger).

**Columns mirror-synced:** every column **except** `payment_id` for automatic entries — `entry_id` (explicit, computed as SQLite `MAX(entry_id) + 1`, the same reasoning as `enquiry_id`/`student_id`/`membership_id` in ADR-18/19/20), `admin_id`, `type`, `category`, `person`, `description`, `amount`, `payment_method`, `entry_date`, `reference_id`, `source`. `payment_id` is written to the SQLite mirror for automatic entries (`insert_income_entry()`) but deliberately **never sent to Supabase** — Supabase's `cashbook.payment_id` has a real Postgres FK to `payments`, and `payments` is still SQLite-only; sending a real `payment_id` there always fails with a `23503` FK violation (verified live). See TD-38.

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

---

## `audit_log`

**Source of truth:** Supabase `audit_log` table, since ADR-22 (2026-07-23), for `database/audit_queries.py`'s `get_recent_audit_log()` — the only reader, called from `routes/cashbook.py`'s `index()` for the "Audit Trail" activity log.

**SQLite mirror's role:** unlike `cashbook`, this mirror carries **every** column (there's no held-back field analogous to `payment_id`) but has **zero application-level readers** — `log_entry(cursor, ...)` (`database/audit_queries.py`) is a pure mirror-write, called from `cashbook_queries.py`'s `insert_transaction()`/`insert_income_entry()`/`update_manual_transaction()` on every cashbook write, same transaction. Nothing in the app ever reads the SQLite copy back.

**Current readers (SQLite):** None.

**Current writers (SQLite):** `database/audit_queries.py`'s `log_entry(cursor, admin_id, entry_id, action, details)` — called by every write path in `database/cashbook_queries.py` (unconditionally, not best-effort — the SQLite `audit_log` row is written in the same local transaction as the SQLite `cashbook` row it documents, exactly as before this migration).

**Why the mirror still exists:**
- **Read-side:** none — already zero readers.
- **FK-side:** `audit_log.admin_id` is a real SQLite FK to `admins.admin_id`, and `audit_log.entry_id` is a real SQLite FK to `cashbook.entry_id` — both still enforced (`PRAGMA foreign_keys = ON`, `database/db.py`), and `log_entry()` still fires on every single cashbook write. This is exactly the FK dependency `routes/auth.py`'s `register()` mirror-insert bridge (see `admins`' section above) exists for — migrating `audit_log` at the route/read level did **not** remove it from that bridge's 7-table list, the same way migrating `enquiries`/`students`/at the route level didn't remove them (ADR-18/19).

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

## Removal priority: state after the analytics migration (ADR-23)

The analytics migration slice (ADR-23, 2026-07-23) and the Settings migration slice (ADR-24, 2026-07-24) are both **done** — this section previously analyzed ADR-23 as a hypothetical "next slice"; it's now actual history, updated below against the real post-ADR-24 state.

Working through each of the 6 active mirrors' **both** conditions (read-side and FK-side — a mirror needs both clear, not just one):

| Mirror | Read-side after ADR-23/24 | FK-side after ADR-23/24 | Removable? |
|---|---|---|---|
| `admins` | Already 0 (unaffected either way) | Down to **3** bridge tables (`enquiries`/`students`/`audit_log`) — ADR-24 dropped the other 4 entirely | No — but closer: only `payments` (transitively, via `enquiries`/`students`) and `audit_log`/`cashbook` stand between this and removal now |
| `enquiries` | **0** (`routes/dashboard.py` was its only reader, migrated) | Unchanged — still needs `students`' own mirror gone, which is gated on `payments` | No — FK-side is the blocker |
| `students` | Down to **3**: `database/payment_queries.py`'s receipt-fallback branch, `routes/payment.py`'s `index()`, `utils/charts.py`'s `generate_revenue_chart()` — all three gated on `payments` (`routes/setting.py`'s backup functions migrated off this list, ADR-24) | Unchanged — still needs `payments` migrated | No — read-side alone still rules it out, but every remaining reader is now gated on the same single table |
| `memberships` | Down to **1**: only `routes/student.py`'s `view()` remains | Unchanged — still needs `payments` migrated (shared with `students`) | Not fully, but closest on the read-side |
| `cashbook` | Already effectively 0 (only `database/migrate_backfill_cashbook_payments.py`, a dormant script) — unaffected by Settings either way | Unchanged — needs `audit_log`'s mirror gone | No |
| `audit_log` | Already 0 — unaffected | Down to needing `cashbook`'s mirror gone **and** the now-smaller `admins` bridge (3 tables, not 7) cleared | No — but the `admins` half of this condition is much closer now |

**Conclusion:** `payments` is now unambiguously the single highest-leverage remaining migration — every open read-side condition left in this file (`students`' 3 readers, `memberships`' 1 reader) and every open FK-side condition (`students`/`memberships`' own mirrors, transitively `enquiries`/`admins`/`cashbook`/`audit_log`) traces back to it, directly or transitively. Settings (ADR-24) was the one path that was genuinely independent of `payments` — it's now done, and shrank the `admins` bridge from 7 to 3 dependents, but didn't remove it (still needs `enquiries`/`students`/`audit_log` gated on `payments` too).

**Practical recommendation, in order:**
1. ~~Do the analytics migration slice~~ — **done** (ADR-23, 2026-07-23).
2. ~~Migrate Settings (`library_settings`/`membership_settings`/`backup_log`/`security_settings`)~~ — **done** (ADR-24, 2026-07-24). Shrank the `admins` bridge from 7 to 3 dependents; also closed `students`' `routes/setting.py` reader while in the same file.
3. Migrate `payments` — this is now the only remaining lever. It clears the FK-side for both `memberships` and (transitively) `students`, closes `students`' 3 remaining readers (`routes/payment.py`'s `index()`, `database/payment_queries.py`'s receipt-fallback branch, `utils/charts.py`'s `generate_revenue_chart()`) and `memberships`' 1 remaining reader (`routes/student.py`'s `view()`) in the same slice (since `view()` reads both tables together), lets `cashbook` carry a real `payment_id` (closing TD-38/TD-39), and closes TD-40 (`generate_receipt_number()`'s now-separate Supabase/SQLite transaction boundary).
4. Once `payments` is migrated, `students`/`memberships` become removable, which in turn clears `enquiries`' FK-side (already at 0 readers) and 2 of the `admins` bridge's remaining 3 dependents.
5. Migrate `audit_log`'s SQLite mirror-write (`log_entry()`) — the last thing blocking `cashbook`'s mirror removal and the `admins` bridge's final dependent. Likely needs `cashbook`'s mirror to come down first (or simultaneously), since `audit_log.entry_id` FKs to `cashbook.entry_id`.

## Related reading

- [DECISIONS.md](DECISIONS.md) — ADR-16 through ADR-24, the full reasoning behind each slice.
- [11_FUTURE_WORK.md](11_FUTURE_WORK.md) — TD-34 (schema-drift risk), TD-35/TD-36/TD-37 (the three split-brain bugs each mirror slice risked, all now `Resolved`).
- [09_DEPENDENCY_MAP.md](09_DEPENDENCY_MAP.md) — the literal import graph this file's "Current readers"/"Current writers" lists are derived from.
- [04_DATABASE_SCHEMA.md](04_DATABASE_SCHEMA.md) — full FK list per table.




## Hidden Dependencies Found During Re-Grep

Date
Reason discovered
Previous documentation missed
Corrected by