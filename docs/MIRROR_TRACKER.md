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

Consequence: a mirror can only be deleted once **every** table downstream of it in this chain either (a) no longer inserts into SQLite at all (i.e., it's been migrated to Supabase too), or (b) has had its FK constraint dropped. `payments` (as of ADR-25) and `cashbook`/`audit_log` (as of ADR-22) are all now Supabase-sourced-of-truth mirrors themselves, but every one of them still keeps a SQLite mirror-write on every single membership/payment/cashbook transaction — so as long as they exist in their current *write* form, the `memberships`/`students`/`enquiries`/`admins` rows their `INSERT`s reference **must** keep existing in SQLite, independent of whether anything still *reads* those mirrors. This is why each mirror's removal conditions below have two parts, not one. **As of 2026-07-25 (ADR-32, Phase 11), this entire FK graph is moot — `schema.sql` itself is deleted, along with every other SQLite file, so there is no live SQLite schema left for these FK constraints to exist against.** (Historical note, describing the state through Phase 10: as each mirror's SQLite `INSERT`/`UPDATE` was removed — `audit_log` (ADR-26), `cashbook` (ADR-27), `payments` (ADR-28), `memberships`/`students` (ADR-29), `enquiries` (ADR-30), `admins` (ADR-31) — its FK edge above stopped being exercised by any live write, one at a time, before the underlying schema was removed entirely in this ADR.)

## Fully migrated, no mirror: `library_settings`, `membership_settings`, `backup_log`, `security_settings`

As of ADR-24 (2026-07-24), these four tables are **not** tracked as mirrors below, because they never became one — `database/settings_queries.py`/`receipt_settings_queries.py`/`notification_settings_queries.py` (`library_settings`), `database/membership_settings_queries.py`, `database/backup_queries.py`, and `database/security_settings_queries.py` read/write Supabase exclusively, with **zero** SQLite reads or writes left in any of them. This was possible in one step (unlike `admins`/`enquiries`/`students`/`memberships`/`cashbook`/`payments`, which each needed an ongoing mirror) because these four tables are leaf nodes in the FK graph above — nothing else in `schema.sql` declares a foreign key against any of them, so there was never a downstream unmigrated table that needed their SQLite row to keep existing. `database/migrate_backfill_settings_to_supabase.py` synced SQLite's more-current data into Supabase (a plain `admin_id`-keyed upsert, not the explicit-id/rollback machinery `enquiries`/`students`/`memberships`/`cashbook`/`payments` needed) before the code cutover — see ADR-24. As of 2026-07-25 (ADR-32, Phase 11), SQLite is gone entirely — `database/schema.sql` and every `migrate_*.py` script (including this one) are deleted; the on-disk `database/library.db` file itself is left untouched (already `.gitignore`d, receives no further writes) rather than deleted.

This closed 4 of the `admins` bridge's original 7 FK dependents in one slice — see that section below.

The tables added after the SQLite era — `ai_center_settings`, `panda_conversations`/`panda_messages`, and (2026-09-02, ADR-65/66) `shift_slots` and `membership_charges` — never had a SQLite mirror and never will; there is no live SQLite schema left to mirror into. They are Supabase-only from creation.

## Summary

| Mirror table | Source of truth since | Readers remaining | FK dependents still requiring it | Status |
|---|---|---|---|---|
| [`admins`](#admins-existence-only-bridge---removed-2026-07-25-adr-31) | Supabase, ADR-16 (2026-07-23) | None (existence-only) | none (cleared, ADR-30) | **Removed** (ADR-31) |
| [`enquiries`](#enquiries--removed-2026-07-24-adr-30) | Supabase, ADR-18 (2026-07-23) | None | none | **Removed** (ADR-30) |
| [`students`](#students--removed-2026-07-24-adr-29) | Supabase, ADR-19 (2026-07-23) | None | none | **Removed** (ADR-29) |
| [`memberships`](#memberships--removed-2026-07-24-adr-29) | Supabase, ADR-20 (2026-07-23) | None | none | **Removed** (ADR-29) |
| [`payments`](#payments--removed-2026-07-24-adr-28) | Supabase, ADR-25 (2026-07-24) | None | none | **Removed** (ADR-28) |
| [`cashbook`](#cashbook--removed-2026-07-24-adr-27) | Supabase, ADR-22 (2026-07-23) | None | none | **Removed** (ADR-27) |
| [`audit_log`](#audit_log--removed-2026-07-24-adr-26) | Supabase, ADR-22 (2026-07-23) | None | none | **Removed** (ADR-26) |

`enquiries.status` and `admins.password` are **not** split anymore — both closed (TD-36 `Resolved` via ADR-19, TD-35 `Resolved` via ADR-17) — see each mirror's section for which columns still mirror-sync vs. which have a single Supabase-only writer.

---

## `admins` (existence-only bridge) — **Removed** (2026-07-25, ADR-31)

**Source of truth:** Supabase `admins` table, since ADR-16 (2026-07-23). Every actual read (login, forgot-password, Security Settings' password change) goes to Supabase. As of ADR-31, it is also the only store — there is no SQLite copy receiving writes anymore.

**SQLite mirror's role (historical):** row *existence* only — the mirror row's column values (other than `admin_id`) were never read back by any route. It existed purely so a handful of other SQLite tables' `FOREIGN KEY (admin_id) REFERENCES admins(admin_id)` constraints resolved when those tables inserted a row for a newly-registered admin.

**Current readers:** None. No route or query module `SELECT`s from SQLite `admins` for any business logic.

**Current writers:** None — `routes/auth.py`'s `register()` had its SQLite mirror-insert deleted outright in ADR-31, along with the now-unused `sqlite3`/`database.db.get_connection` imports and the `insert_response`/`new_admin_id` variables that only existed to feed it. `login()`/`forgot_password()` and `routes/setting.py`'s `security_settings()` password branch still touch Supabase's `admins.password` only, unaffected (TD-35, `Resolved` via ADR-17).

**Why this bridge was removable:** `enquiries`' own SQLite mirror-write (ADR-30) was the last thing exercising any SQLite FK back to `admins.admin_id`. With that gone (following `audit_log` at ADR-26 and `students` at ADR-29), nothing in the SQLite FK graph required an `admins` row to exist for a write to succeed — this was the **last** mirror/bridge in the entire app.

**Exact removal conditions:** none remaining — fully removed. **This is the final entry in this file's "active mirror" tracking** — see the "Fully migrated, no mirror" note at the top: every table in the app is now either Supabase-only with no SQLite dependency, or (for `expenses`/`settings`/`transactions`) unused legacy tables never touched by the migration at all.

**Change history:**
- 2026-07-23 (ADR-16): bridge introduced — `register()`'s Supabase-only write broke 7 tables' SQLite FK on the very next admin who touched any of them (74 test failures caught this).
- 2026-07-23 (ADR-17): `admins.password`'s split-brain closed (TD-35 `Resolved`) — unrelated to this bridge, which covers row existence, not `password`.
- 2026-07-23 (post-ADR-22 full-codebase re-grep): re-verified against source — no production route/query module reads SQLite `admins` for any purpose (the only non-`register()` hits are `database/migrate.py`, a one-time script, and test files). List unchanged; `audit_log` remains one of the 7 FK dependents (see its own section — migrating its reads to Supabase, ADR-22, did not remove it from this list).
- 2026-07-24 (ADR-24): `library_settings`/`membership_settings`/`backup_log`/`security_settings` migrated to Supabase with no SQLite mirror kept at all (they're leaf tables, nothing downstream needed them) — dropped off this bridge's dependent list entirely, shrinking it from 7 to 3 (`enquiries`, `students`, `audit_log`).
- 2026-07-24 (ADR-26): `audit_log`'s SQLite mirror-write removed outright — dropped off this bridge's dependent list, shrinking it from 3 to 2 (`enquiries`, `students`).
- 2026-07-24 (ADR-29): `students`' SQLite mirror-write removed outright — dropped off this bridge's dependent list, shrinking it to 1 (`enquiries` only).
- 2026-07-24 (ADR-30): `enquiries`' SQLite mirror-write removed outright — dropped off this bridge's dependent list, shrinking it to **0**.
- 2026-07-25 (ADR-31): `register()`'s SQLite mirror-insert deleted outright. **This was the last mirror/bridge in the entire app** — every table Phase 6-10 touched is now Supabase-only. See ADR-31 in `DECISIONS.md`. Phase 11 (full SQLite removal — connections, `database/db.py`, `schema.sql`, obsolete `migrate_*.py` scripts) can now begin.
- 2026-07-25 (ADR-32): **Phase 11 complete.** `database/db.py`, `database/schema.sql`, `database/seed.py`, `database/init_db.py`, and all fourteen `database/migrate_*.py` scripts deleted outright. `routes/setting.py`'s `backup_create()` — the very last thing in the app still touching the SQLite *file* (a whole-file copy, unrelated to this bridge's row-existence concern but the last SQLite dependency anywhere) — rebuilt as a per-admin Supabase export, which also fixed **TD-32** (a critical cross-tenant data leak in the old whole-file copy) as a side effect. No `sqlite3`, `get_connection`, or `database.db` reference remains anywhere in the app's Python code. See ADR-32 in `DECISIONS.md`. This file's active-mirror tracking is now entirely historical — every table it describes reached Supabase-only status, and the infrastructure that once wrote their SQLite mirrors no longer exists to write anything at all.

---

## `enquiries` — **Removed** (2026-07-24, ADR-30)

**Source of truth:** Supabase `enquiries` table, since ADR-18 (2026-07-23), for `index()`/`add()`/`edit()`/`delete()`/`view()` in `routes/enquiries.py`. As of ADR-30, it is also the only store — there is no SQLite copy receiving writes anymore.

**Columns (historical, SQLite mirror):** `enquiry_id` (explicit, computed from `MAX(enquiry_id) + 1` — SQLite's before ADR-30, Supabase's own as of ADR-30, not Supabase's identity column — see ADR-18), `admin_id`, `full_name`, `mobile`, `purpose`, `preferred_shift`, `followup_date`, `remarks`, `demo_done`.
**Column that was deliberately *not* mirror-synced (historical):** `status` — `routes/student.py`'s `admission()` wrote `status='Admitted'` to **Supabase only** (TD-36, `Resolved` via ADR-19). The SQLite mirror's `status` column was stale/frozen at whatever `add()` last wrote and was read by nothing.

**Current readers (SQLite):** None.

**Current writers (SQLite):** None — `add()`/`edit()`/`delete()` had their SQLite `INSERT`/`UPDATE`/`DELETE` calls deleted outright in ADR-30. `enquiry_id` is now computed from Supabase's own `MAX(enquiry_id)`.

**Why this mirror was removable:** `students`' own SQLite mirror-write (ADR-29) was the last thing exercising `students.enquiry_id`'s SQLite FK. With that gone, nothing in the SQLite FK graph required an `enquiries` row to exist for a write to succeed.

**Exact removal conditions:** none remaining — fully removed.

**Change history:**
- 2026-07-23 (ADR-18): mirror introduced — needed as an ongoing two-way sync (not a one-shot bridge like `admins`'), since `admission()` (at the time) read live enquiry field values from SQLite, not just row existence.
- 2026-07-23 (ADR-19): `status` column's writer moved to Supabase-only, closing TD-36. `admission()` stopped reading this mirror's field values (`full_name`/`mobile`/`purpose`/`preferred_shift`) — it now read Supabase directly. Mirror itself (row existence + non-`status` columns) remained required, for the two reasons listed above.
- 2026-07-23 (post-ADR-22 full-codebase re-grep): re-verified against source — `routes/dashboard.py` was still the only production reader of SQLite `enquiries`; no additional reader surfaced (unlike `students`/`memberships`, see their sections). List unchanged.
- 2026-07-23 (ADR-23): `routes/dashboard.py`'s enquiry count migrated to Supabase (`.select("enquiry_id", count="exact", head=True).eq("admin_id", admin_id)`) — this mirror's read-side condition became fully satisfied. Still blocked purely on the FK-side (`students` mirror).
- 2026-07-24 (ADR-29): `students`' SQLite mirror-write removed, clearing the FK-side condition entirely. `enquiries` became the next removal candidate in Phase 10.
- 2026-07-24 (ADR-30): `add()`/`edit()`/`delete()`'s SQLite writes deleted outright, alongside the now-unused `sqlite3`/`database.db.get_connection` imports. Verified via `tests/test_02_enquiry.py`/`test_03_student_membership_payment.py`/`test_08_cross_tenant_isolation.py`/`test_09_full_workflow_chain.py` plus the full suite. `admins`' `register()` bridge is now the last remaining mirror/bridge — with `enquiries` gone, it has zero dependent tables left.

---

## `students` — **Removed** (2026-07-24, ADR-29)

**Source of truth:** Supabase `students` table, since ADR-19 (2026-07-23), for `index()`/`admission()`/`view()`/`edit()` in `routes/student.py`. As of ADR-29, it is also the only store — there is no SQLite copy receiving writes anymore.

**Columns mirror-synced:** every column — `student_id` (explicit, `MAX(student_id) + 1`, same reasoning as `enquiries.enquiry_id`), `admin_id`, `enquiry_id`, `full_name`, `mobile`, `address`, `id_proof`, `purpose`, `shift`, `join_date`, `status`. Unlike `enquiries`, there is no held-back column — `admission()`/`edit()` write both databases in full, since `students.status` has no split-brain risk analogous to `enquiries.status` (nothing else writes it).

**Current readers (SQLite):** None. `routes/setting.py`'s `backup_create()` used to consume this mirror via a whole-file copy (a non-query concern, tracked separately from the reader list above) — as of 2026-07-25 (ADR-32, Phase 11), that whole-file copy is gone too, replaced by a per-admin Supabase export.

**Migrated to Supabase by ADR-23 (2026-07-23):** `routes/dashboard.py` (total-students count, upcoming-expiries, recent-admissions — now via `database.membership_queries.get_admin_students()`/`get_memberships_for_admin()`), `routes/membership_distribution.py`'s `index()` (total/plan-wise counts and the listing's non-payment columns), `routes/notification.py`'s `get_notification_summary()`, `database/bi_queries.py` (`get_monthly_new_memberships()`/`get_membership_retention()`/`get_upcoming_expiries()`), `database/cashbook_queries.py`'s `get_pending_fees()`, `database/membership_queries.py`'s `get_membership_counts()`, `utils/charts.py`'s `generate_membership_chart()`/`generate_membership_distribution_donut()`, `routes/enquiries.py`'s `index()`/`view()`/`delete()`, and `routes/student.py`'s own `index()` self-join.

**Migrated to Supabase by ADR-24 (2026-07-24):** `routes/setting.py`'s `backup_export_csv()` (its `students` CSV export).

**Migrated to Supabase by ADR-25 (2026-07-24), closing the last 3 readers:** `routes/payment.py`'s `index()`, `database/payment_queries.py`'s `generate_receipt_number()` fallback branch, and `utils/charts.py`'s `generate_revenue_chart()` — all three via the new `database.payment_queries.get_payments_for_admin()` helper, now that `payments` itself has a Supabase copy.

**Not** a reader: `routes/membership.py` — migrated off this list by ADR-20 (its own student lookups go through Supabase). `routes/payment.py`'s `collect()` — migrated off this list by ADR-21 (its ownership check now reads Supabase `students`).

**Current writers (SQLite):** None — `routes/student.py`'s `admission()`/`edit()` had their SQLite `INSERT`/`UPDATE` calls deleted outright in ADR-29, along with the now-unused `sqlite3`/`database.db.get_connection` imports. `student_id` is now computed from Supabase's own `MAX(student_id)`.

**Why this mirror was removable:** `payments`' SQLite mirror-write (ADR-28) was the last thing exercising `payments.student_id`'s SQLite FK; `memberships`' SQLite mirror-write (removed in the same slice as this table, ADR-29) was the last thing exercising `memberships.student_id`'s SQLite FK. With both gone, nothing in the SQLite FK graph required a `students` row to exist for a write to succeed.

**Exact removal conditions:** none remaining — fully removed. `routes/setting.py`'s `backup_create()` whole-file SQLite copy, the last thing anywhere in the app still touching the SQLite file itself, was rebuilt as a per-admin Supabase export in the same slice as SQLite's removal (ADR-32, Phase 11) — see the `admins` section below for the full closing note.

**Change history:**
- 2026-07-23 (ADR-19): mirror introduced, widest fan-out found so far (8 modules at the time). Closed TD-36 at the source (`admission()`'s `enquiries.status` write moved to Supabase). `enquiries` mirror confirmed still required, independent of this migration.
- 2026-07-23 (ADR-20): `routes/membership.py` migrated off the reader list (its own student lookups moved to Supabase).
- 2026-07-23 (ADR-21): `routes/payment.py`'s `collect()` migrated off the reader list (ownership check moved to Supabase); `routes/payment.py`'s `index()` remains a reader. Re-verifying the full list against source (not against ADR-19's original prose) also surfaced `routes/setting.py`'s `backup_export_csv()`/`backup_create()` and `routes/enquiries.py`'s read-only lookups explicitly, which prior summaries had described narratively but this file now lists exhaustively.
- 2026-07-23 (post-ADR-22 full-codebase re-grep): widened from 9 to 11 tracked consumers — `utils/charts.py` (3 chart functions) and `database/payment_queries.py`'s `generate_receipt_number()` fallback branch were both real, executable SQLite readers that no prior version of this file named explicitly. Also documented `routes/student.py`'s own `index()` self-join against SQLite `students`, previously described only as a `memberships` read. No removal condition changed as a result — a completeness correction.
- 2026-07-23 (ADR-23): shrank from 11 to 4 tracked consumers in one slice — see ADR-23 in [DECISIONS.md](DECISIONS.md). The 4 remaining readers were gated on either `payments` migrating (`routes/payment.py`'s `index()`, `database/payment_queries.py`'s receipt-fallback branch, `utils/charts.py`'s `generate_revenue_chart()`) or Settings migrating (`routes/setting.py`'s backup functions).
- 2026-07-24 (ADR-24): `routes/setting.py`'s `backup_export_csv()` migrated to Supabase while Settings was already being touched for the 4 Settings tables — shrinking the tracked query-based reader list from 4 to 3, all now gated purely on `payments`.
- 2026-07-24 (ADR-25): `payments` itself migrated to Supabase, closing all 3 remaining readers in one slice. Read-side condition now fully satisfied — only the FK-side (SQLite mirror-*writes*, not reads) remains open. Backfilling `payments` also surfaced and fixed **TD-42**: Supabase `students` (and `enquiries`/`memberships`) had a large pre-existing gap of rows never copied from SQLite, unrelated to this mirror's reader list but a real data-integrity issue this slice's investigation caught — see ADR-25 and TD-42 in [11_FUTURE_WORK.md](11_FUTURE_WORK.md).
- 2026-07-24 (ADR-28): `payments`' SQLite mirror-write removed, clearing one of this mirror's two FK dependents. `memberships`' own SQLite mirror-write is the only one left — see that section for why it's now the next removal candidate.
- 2026-07-24 (ADR-29): `admission()`/`edit()`'s SQLite writes deleted outright, alongside `memberships`' own removal in the same slice. `enquiries` is now the next removal candidate.

---

## `memberships` — **Removed** (2026-07-24, ADR-29)

**Source of truth:** Supabase `memberships` table, since ADR-20 (2026-07-23), for `index()`/`create()`/`renew()` in `routes/membership.py`, and since ADR-21 (2026-07-23) for `paid_amount`/`pending_amount` specifically in `routes/payment.py`'s `collect()`. As of ADR-29, it is also the only store — there is no SQLite copy receiving writes anymore.

**Columns (historical, SQLite mirror):** every column, from two different writers — `routes/membership.py`'s `create()`/`renew()` wrote the full row (`membership_id`, explicit `MAX(membership_id) + 1`; `student_id`, `plan_name`, `joining_date`, `duration_days`, `end_date`, `total_fee`, `paid_amount`, `pending_amount`, `remarks`, `membership_status`); `routes/payment.py`'s `collect()` wrote only `paid_amount`/`pending_amount` on an existing row (it never inserted a new membership row).

**Current readers (SQLite):** None.

**Migrated to Supabase by ADR-23 (2026-07-23):** `routes/dashboard.py` (upcoming-expiries, recent-admissions), `database/membership_queries.py`'s `get_membership_counts()`, `routes/membership_distribution.py`'s `index()` (full membership listing's non-payment columns, plus `get_membership_counts()`), `routes/notification.py`'s `get_notification_summary()`, `routes/student.py`'s own `index()` self-join, `database/cashbook_queries.py`'s `get_pending_fees()`, `database/bi_queries.py` (`get_monthly_new_memberships()`/`get_membership_retention()`/`get_upcoming_expiries()`), and `utils/charts.py`'s `generate_membership_chart()`/`generate_membership_distribution_donut()`.

**Migrated to Supabase by ADR-25 (2026-07-24), closing the last reader:** `routes/student.py`'s `view()` — now reads both Supabase `memberships` (latest row for this student) and Supabase `payments` (this student's full payment history) directly, since `payments` migrating in the same slice removed the reason this one held out during ADR-23.

**Not** a reader: `routes/payment.py`'s `collect()` — as of ADR-21 it reads the membership from Supabase, not SQLite, before updating either. `routes/payment.py`'s `index()` never touches `memberships` at all (only `payments`/`students`).

**Current writers (SQLite):** None — `routes/membership.py`'s `create()`/`renew()` and `routes/payment.py`'s `collect()` all had their SQLite `INSERT`/`UPDATE` calls deleted outright in ADR-29. `membership_id` is now computed from Supabase's own `MAX(membership_id)`.

**Why this mirror was removable:** `payments`' own SQLite mirror-write (ADR-28) was the last thing exercising `payments.membership_id`'s SQLite FK. With that gone, nothing in the SQLite FK graph required a `memberships` row to exist for a write to succeed.

**Exact removal conditions:** none remaining — fully removed.

**Change history:**
- 2026-07-23 (ADR-20): mirror introduced. `routes/payment.py`'s `collect()`, `routes/dashboard.py`, `routes/membership_distribution.py`, `routes/notification.py` named as remaining readers — this list was **incomplete** (see ADR-21's correction below).
- 2026-07-23 (ADR-21): `routes/payment.py`'s `collect()` migrated off the reader list and onto the writer list for `paid_amount`/`pending_amount` (closing TD-37). Re-verifying the dependency graph directly against source (not against ADR-20's prose) found ADR-20's reader list had missed `routes/student.py`'s `view()`, `database/cashbook_queries.py`'s `get_pending_fees()`, and `database/bi_queries.py` — all three added to this file's tracked list, none of them touched by ADR-21, all still `Open`.
- 2026-07-23 (post-ADR-22 full-codebase re-grep): widened from 6 to 7 tracked consumers — `utils/charts.py`'s `generate_membership_chart()`/`generate_membership_distribution_donut()` were real, executable SQLite readers not previously named (same class of gap as `students`' section), and `routes/student.py`'s own `index()` self-join was clarified as a second, independent `memberships` read distinct from `view()`. No removal condition changed (still blocked on `payments`) — a completeness correction, not a new blocker.
- 2026-07-23 (ADR-23): shrank from 7 to 1 tracked consumer in one slice — every reader except `routes/student.py`'s `view()` migrated to Supabase via the new shared `get_memberships_for_admin()` helper (see ADR-23 in [DECISIONS.md](DECISIONS.md)).
- 2026-07-24 (ADR-25): `routes/student.py`'s `view()` migrated, closing the last reader — read-side condition now fully satisfied, only the FK-side (SQLite mirror-writes) remains open.
- 2026-07-24 (ADR-28): `payments`' SQLite mirror-write removed, clearing the FK-side condition entirely. `memberships` is now the **next removal candidate** in Phase 10.
- 2026-07-24 (ADR-29): `create()`/`renew()`/`collect()`'s SQLite writes deleted outright, alongside `students`' own removal in the same slice. `enquiries` is now the next removal candidate.

---

## `payments` — **Removed** (2026-07-24, ADR-28)

**Source of truth:** Supabase `payments` table, since ADR-25 (2026-07-24), for every read across the app (`routes/payment.py`'s `index()`, `routes/student.py`'s `view()`, `utils/charts.py`'s `generate_revenue_chart()`, `database/cashbook_queries.py`'s `get_today_fee_collection()`/`get_total_fee_revenue()`, `routes/membership_distribution.py`'s per-row receipt columns, `database/payment_queries.py`'s own receipt-fallback branch). As of ADR-28, it is also the only store — there is no SQLite copy receiving writes anymore.

**Columns (historical, SQLite mirror):** every column — `payment_id` (explicit, computed from `MAX(payment_id) + 1` — SQLite's before ADR-28, Supabase's own as of ADR-28, same reasoning as `enquiry_id`/`student_id`/`membership_id`/`entry_id` in ADR-18/19/20/22/27), `membership_id`, `student_id`, `receipt_number`, `payment_mode`, `amount_paid`, `payment_date`, `remarks`.

**Current readers (SQLite):** None. `_receipt_number_taken()` (`database/payment_queries.py`) — the one internal consistency check that deliberately stayed on SQLite while it was the primary write (to avoid a false negative against a lagging best-effort Supabase mirror) — now queries Supabase directly, since Supabase is the only copy left and checking anywhere else would mean checking stale data.

**Current writers (SQLite):** None — `record_payment()`'s SQLite `INSERT` was deleted outright in ADR-28, along with its `conn` parameter (no longer needed for anything). `generate_receipt_number()` similarly dropped its `conn` parameter and now queries Supabase for the uniqueness check.

**Why this mirror was removable next:** `cashbook`'s SQLite mirror-write (ADR-27) was the last thing that would have required a `payments` row to exist in SQLite for a *downstream* write's FK to resolve — the FK itself (`cashbook.payment_id → payments.payment_id`) was never exercised on the Supabase side by SQLite data, only by `cashbook_queries.py`'s own Supabase insert. With `cashbook`'s SQLite insert gone, nothing in the SQLite FK graph required `payments`' SQLite row to exist for a write to succeed — the only remaining question was `record_payment()`'s own SQLite insert stopping, a pure write-path decision.

**Consequence — a real behavior change, not just a deletion:** before ADR-28, `record_payment()`'s SQLite write was primary and any failure there was a genuine `sqlite3.Error`, caught by `routes/membership.py`'s/`routes/payment.py`'s existing `except sqlite3.Error:` blocks (which also roll back the SQLite `memberships` mirror-write and the Supabase `memberships` update). As of ADR-28, the Supabase `payments` insert is **strict** (raises `postgrest.exceptions.APIError` on failure, not swallowed) — deliberately, since there's no SQLite fallback left to silently keep the payment in. All three call sites (`routes/membership.py`'s `create()`/`renew()`, `routes/payment.py`'s `collect()`) now catch `(sqlite3.Error, APIError)` instead of just `sqlite3.Error`, preserving the exact same rollback/flash UX for a payment failure. Unlike `insert_income_entry()`'s design (ADR-27, best-effort, no fallback, new debt TD-43), `record_payment()`'s own write did **not** become best-effort — it's the core "money was recorded" write, and letting a failure surface loudly (caught, rolled back, flashed) is the correct choice here, not silent data loss.

**Exact removal conditions:** none remaining — fully removed.

**Change history:**
- 2026-07-24 (ADR-25): mirror introduced. Backfilling it first required fixing a much larger, previously-undocumented gap in `enquiries`/`students`/`memberships`' own Supabase parity (**TD-42**, `Resolved` in the same slice) — see `database/migrate_backfill_mirror_parity.py` and ADR-25 in [DECISIONS.md](DECISIONS.md). Closed the last 3 `students`-mirror readers and the last 1 `memberships`-mirror reader in the same slice, since all four were gated on this table migrating.
- 2026-07-24 (ADR-27): `cashbook`'s SQLite mirror-write removed, clearing the last thing that would have required this table's SQLite row for a downstream FK.
- 2026-07-24 (ADR-28): `record_payment()`'s SQLite insert deleted outright; `_receipt_number_taken()`/`generate_receipt_number()` switched to Supabase; the Supabase insert made strict (raises on failure) with its three callers' `except` clauses widened to catch `APIError`. Verified via the full pytest suite. `memberships` is now the next removal candidate.
- 2026-07-24 (ADR-27): `cashbook`'s SQLite mirror-write removed (see below), making `payments` the **next removal candidate** in Phase 10.

---

## `cashbook` — **Removed** (2026-07-24, ADR-27)

**Source of truth:** Supabase `cashbook` table, since ADR-22 (2026-07-23), for `index()`/`add_transaction()`/`edit_transaction()` in `routes/cashbook.py`, and for every getter in `database/cashbook_queries.py` (totals, monthly series, category breakdowns, payment-method distribution, cash balance, the paginated ledger). As of ADR-27, it is also the only store — there is no SQLite copy receiving writes anymore.

**Columns (historical, SQLite mirror):** every column, including `payment_id` for automatic entries as of 2026-07-24 (ADR-25) — `entry_id` (explicit, computed from `MAX(entry_id) + 1` — SQLite's before ADR-27, Supabase's own as of ADR-27, same reasoning as `enquiry_id`/`student_id`/`membership_id` in ADR-18/19/20), `admin_id`, `type`, `category`, `person`, `description`, `amount`, `payment_method`, `entry_date`, `reference_id`, `source`, `payment_id`.

**Current readers (SQLite):** None. `database/migrate_backfill_cashbook_payments.py` — the one-time reconciliation script that was this mirror's last read-side justification — was deleted in the same slice (ADR-27); its entire approach (matching `payments` rows to `cashbook` rows via raw SQLite `JOIN`s, then reconciling into SQLite `cashbook`) had nothing left to reconcile into once this mirror stopped receiving writes.

**Current writers (SQLite):** None — `insert_transaction()`, `insert_income_entry()`, and `update_manual_transaction()` (`database/cashbook_queries.py`) all had their SQLite `INSERT`/`UPDATE` and `get_connection()` calls deleted outright in ADR-27, not just stopped-and-left-dead. `_generate_reference_id()`/`_next_entry_id()` (the explicit-ID helpers) now query Supabase's own `COUNT`/`MAX` instead of SQLite's.

**Why this mirror was removable next:** `audit_log`'s SQLite mirror-write (ADR-26) was the only thing still exercising `cashbook.entry_id`'s SQLite FK on every insert — once that stopped, nothing in the SQLite FK graph still required a `cashbook` row to exist for a *write* to succeed. The one remaining justification (the dormant backfill script) was a read-side concern, resolved by deleting the script rather than keeping the mirror alive to feed it.

**Consequence:** the SQLite `cashbook` table's DDL is gone (Phase 11, ADR-32, along with the rest of `schema.sql`); the on-disk `database/library.db` data file itself is left untouched, unread by any code. `payments` was the next removal candidate at the time: `cashbook`'s SQLite insert was the only thing still requiring `payments.payment_id`/`membership_id`/`student_id`'s SQLite rows to exist as *write-time FK targets* from this table's side (though `payments`' own SQLite insert has its own separate FK needs against `memberships`/`students`, unaffected by this change — see `payments`' section above). Also, as of ADR-27, `insert_income_entry()`'s Supabase failure mode changed from "leaves a stale mirror" (TD-39/TD-41) to "loses the entry entirely" (no SQLite fallback left) — tracked as new debt, **TD-43** in `docs/11_FUTURE_WORK.md`, not a continuation of TD-39/TD-41.

**Change history:**
- 2026-07-23 (ADR-22): mirror introduced. Automatic entries (`insert_income_entry()`) kept the SQLite write as primary and best-effort mirrored to Supabase, unlike every prior slice's "Supabase first, roll back on SQLite failure" shape — because that function's caller (`database/payment_queries.py`'s `record_payment()`, called from `routes/membership.py`/`routes/payment.py`) is out of scope and can't be given a new caught exception type. Manual entries (`insert_transaction()`, called directly from the in-scope `routes/cashbook.py`) used the strict Supabase-first shape. Introduced TD-38 (`payment_id` can't round-trip through Supabase for automatic entries) and TD-39 (best-effort mirror can leave a narrow, bounded staleness window on Supabase after a transient failure).
- 2026-07-23 (post-ADR-22 full-codebase re-grep): re-verified against source — `database/migrate_backfill_cashbook_payments.py` confirmed the only remaining reader of raw SQLite `cashbook` anywhere outside `cashbook_queries.py`/tests. List unchanged.
- 2026-07-24 (ADR-25): `payments` migrated to Supabase, letting `insert_income_entry()` start sending a real `payment_id` to Supabase `cashbook` (closing **TD-38**'s common case — best-effort, so a rare Supabase blip can still leave a gap here, tracked as **TD-41**).
- 2026-07-24 (ADR-26): `audit_log`'s SQLite mirror-write removed, clearing this mirror's FK-side condition entirely.
- 2026-07-24 (ADR-27): `insert_transaction()`/`insert_income_entry()`/`update_manual_transaction()`'s SQLite writes deleted outright; `_generate_reference_id()`/`_next_entry_id()` switched to Supabase; `database/migrate_backfill_cashbook_payments.py` deleted. Verified via the full pytest suite. `payments` is now the next removal candidate.

---

## `audit_log` — **Removed** (2026-07-24, ADR-26)

**Source of truth:** Supabase `audit_log` table, since ADR-22 (2026-07-23), for `database/audit_queries.py`'s `get_recent_audit_log()` — the only reader, called from `routes/cashbook.py`'s `index()` for the "Audit Trail" activity log.

**SQLite mirror's role (historical):** unlike `cashbook`, this mirror carried **every** column (there was no held-back field analogous to `payment_id`) but had **zero application-level readers** — `log_entry(cursor, ...)` (`database/audit_queries.py`) was a pure mirror-write, called from `cashbook_queries.py`'s `insert_transaction()`/`insert_income_entry()`/`update_manual_transaction()` on every cashbook write, same transaction. Nothing in the app ever read the SQLite copy back.

**Current readers (SQLite):** None (never had any).

**Current writers (SQLite):** None — `log_entry()` and its three call sites were deleted outright in ADR-26, not just stopped-and-left-dead. `get_recent_audit_log()` (Supabase) is the only function left in `database/audit_queries.py`.

**Why this mirror was removable first:** `audit_log` is a genuine leaf in the SQLite FK graph — nothing in `schema.sql` declares a foreign key against `audit_log` (its own two FKs, `admin_id → admins` and `entry_id → cashbook`, are *outgoing*, not incoming). The Phase 9 dependency audit confirmed every mirror in the app was already at zero read-side consumers by ADR-25; `audit_log` was the one place where the FK-side condition was also independently satisfiable, since removing its write doesn't require any *other* table's write to stop first.

**Consequence:** the SQLite `audit_log` table's DDL is gone (Phase 11, ADR-32, along with the rest of `schema.sql`); the on-disk `database/library.db` data file itself is left untouched, unread by any code. `cashbook`'s SQLite mirror-write was the next candidate at the time: `audit_log.entry_id`'s FK to `cashbook.entry_id` is no longer being exercised by any new insert, so `cashbook`'s mirror-write is no longer required by anything downstream.

**Change history:**
- 2026-07-23 (ADR-22): mirror's *reads* moved to Supabase (`get_recent_audit_log()`); the mirror-write itself (`log_entry()`) was unchanged from before this migration, kept as a pure SQLite write with no application reader, purely to satisfy `cashbook.entry_id`'s and `admins.admin_id`'s SQLite FKs.
- 2026-07-23 (post-ADR-22 full-codebase re-grep): re-verified against source — zero reads of raw SQLite `audit_log` anywhere outside `audit_queries.py` itself (which only wrote it) and test files. List unchanged.
- 2026-07-24 (ADR-26): `log_entry()` and its three call sites in `database/cashbook_queries.py` deleted outright — the first mirror in this file to be fully removed, not just migrated. Verified via `tests/test_04_cashbook.py`/`test_09_full_workflow_chain.py` (45 passed) plus the full suite.

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
4. ~~Run the Phase 9 dependency audit directly against source~~ — **done**, see "Phase 9: Final Dependency Audit" below.
5. Remove SQLite mirror-writes in FK-safe order (Phase 10) — **reverse** of the FK chain, starting from the table nothing else FKs to: ~~`audit_log`~~ — **done** (ADR-26) → ~~`cashbook`~~ — **done** (ADR-27) → ~~`payments`~~ — **done** (ADR-28) → ~~`memberships`/`students`~~ — **done** (ADR-29) → ~~`enquiries`~~ — **done** (ADR-30) → `admins` bridge last (next — `enquiries` no longer needs it, now true; the final mirror/bridge in the app).
6. Once every mirror-write is gone, Phase 11 removes SQLite entirely — **done**, 2026-07-25, ADR-32.

## Phase 9: Final Dependency Audit (2026-07-24, post-ADR-25)

Verified directly against source — not against this file's own prior claims — by re-grepping every `.py` file in `routes/`/`database/`/`utils/` (excluding `database/migrate_*.py` and `database/migrate.py`, all one-time/historical scripts not on the live request path) for `sqlite3`, `get_connection()`, `SELECT`, `INSERT INTO`, `UPDATE`, `DELETE FROM`, `FROM`, `JOIN`.

**Confirmed: zero raw `JOIN`/cross-table SQL reads remain anywhere in live code.** Every remaining SQLite access is one of exactly two kinds:

| Table | Live SQLite readers | Live SQLite writers | Real SQLite FK dependents (from `schema.sql`) |
|---|---|---|---|
| `admins` | None | `routes/auth.py`'s `register()` (mirror-insert) | `enquiries.admin_id`, `students.admin_id`, `audit_log.admin_id`, `library_settings`/`membership_settings`/`backup_log`/`security_settings.admin_id` (last 4 tables no longer insert into SQLite at all, ADR-24, so don't actually exercise this FK anymore — only `enquiries`/`students`/`audit_log` do) |
| `enquiries` | None | `routes/enquiries.py`'s `add()`/`edit()`/`delete()` (mirror-write) | `students.enquiry_id` |
| `students` | None | `routes/student.py`'s `admission()`/`edit()` (mirror-write) | `memberships.student_id`, `payments.student_id` |
| `memberships` | None | `routes/membership.py`'s `create()`/`renew()`, `routes/payment.py`'s `collect()` (mirror-write) | `payments.membership_id` |
| `payments` | None (`database/payment_queries.py`'s `_receipt_number_taken()` reads SQLite `payments` for its uniqueness check — a correctness-critical internal check on the primary write path, not a stale mirror reader, see `payments`' section above) | `database/payment_queries.py`'s `record_payment()` (primary write, explicit `payment_id`) | `cashbook.payment_id` (**a real SQLite FK**, `schema.sql` line 142-143 — not just the Supabase FK documented earlier; automatic Cashbook entries write a real `payment_id` into the SQLite `cashbook` row, so this FK is actively exercised) |
| `cashbook` | `database/migrate_backfill_cashbook_payments.py` (dormant one-time script, not on the live request path) | `database/cashbook_queries.py`'s `insert_transaction()`/`insert_income_entry()`/`update_manual_transaction()` (mirror-write) | `audit_log.entry_id` |
| `audit_log` | None | `database/audit_queries.py`'s `log_entry()` (mirror-write) | None — leaf table, nothing in `schema.sql` FKs to `audit_log` |

**Conclusion:** every mirror is at **zero live read-side consumers**. The only thing keeping any SQLite mirror-write alive is another mirror-write's own FK requirement, in a single connected chain: `admins` ← `enquiries`/`students`/`audit_log` ← `memberships` (via `students`) ← `payments` (via `students`/`memberships`) ← `cashbook` (via `payments.payment_id`) ← `audit_log` (via `cashbook.entry_id`). `audit_log` is the one table nothing downstream FKs to — it's the correct starting point for Phase 10, not `payments` (a prior draft of this section's "practical recommendation" had the order backwards; corrected here).

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