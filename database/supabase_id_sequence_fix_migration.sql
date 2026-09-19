-- Smart Library App - Deterministic global-ID collision fix (ADR-79/ADR-81,
-- TD-108)
--
-- Root cause: several `database/*_queries.py` modules (and, for
-- `enquiries`/`students`/`shift_slots`, the now-retired
-- `insert_with_next_id()`) used to compute `MAX(id) + 1` through the app's
-- tenant-scoped, Row-Level-Security-filtered Supabase client. Every id
-- column below is a single GLOBAL identity primary key shared by every
-- tenant (`database/supabase_migration.sql`), not a per-tenant sequence -
-- so a brand-new tenant's RLS-filtered view is always empty, making that
-- computed `next_id` deterministically `1` and guaranteed to collide with
-- whatever tenant already owns global id `1`. Not a race - it failed on
-- literally the first insert from any new tenant.
--
-- 2026-09-18 (ADR-79) fixed this for `enquiries.enquiry_id` /
-- `students.student_id` / `shift_slots.slot_id`, all three funneled through
-- `database/id_sequence.py`'s `insert_with_next_id()`. A full codebase audit
-- (2026-09-19, ADR-81) found the identical pattern, independently
-- implemented, in three more places: `database/membership_queries.py`'s
-- `insert_membership()` (called from `routes/membership.py`'s `create()`/
-- `renew()`, which previously computed `membership_id` themselves),
-- `database/payment_queries.py`'s `record_payment()` (`payment_id`), and
-- `database/cashbook_queries.py`'s `insert_transaction()`/
-- `insert_income_entry()` (`entry_id`, via the now-removed
-- `_next_entry_id()`). This migration and the application code fix use the
-- exact same mechanism for all six tables - one consistent strategy, not
-- six one-off patches.
--
-- Fix: every affected insert now happens WITHOUT an explicit id, letting
-- the identity column's own `nextval()` default assign it - atomic,
-- globally unique, and not subject to RLS (RLS gates table rows, not
-- sequence objects). That default is only trustworthy once each sequence
-- sits at or above the true global MAX(id) already in the table - the
-- identity sequence was originally seeded once from a one-time SQLite ->
-- Supabase data copy (ADR-15) and may have trailed real usage ever since
-- (TD-78, the original reason application code never trusted the default
-- in the first place). This migration performs that one-time realignment
-- for all six tables.
--
-- NOT in scope here (found during the same audit, flagged not fixed - see
-- TD-113): `payments.receipt_number` generation
-- (`database/payment_queries.py`'s `generate_receipt_number()`/
-- `_max_claimed_sequence()`/`_receipt_number_taken()`) is documented as
-- needing to see every tenant's claimed numbers (the column is `UNIQUE`
-- *globally*, not per-admin) but is also RLS-blinded to this tenant's own
-- rows - a different failure shape (a caught-and-retried `APIError` that
-- can loop indefinitely for an affected admin, not a raw crash) needing a
-- different fix (a SECURITY DEFINER RPC to bypass RLS for the global
-- uniqueness check, since there is no Postgres identity sequence behind a
-- formatted text column) and already flagged by TD-108 itself as an open
-- product decision ("decide whether receipt numbering should become
-- per-tenant"), not a mechanical oversight. `cashbook.reference_id` has the
-- same RLS-blindness but no UNIQUE constraint - cosmetic only (two tenants
-- could show the same reference_id string), no crash risk.
--
-- IMPORTANT: run this in the Supabase SQL Editor (a superuser/table-owner
-- connection) - NEVER through the app's tenant-scoped RLS client, which
-- would only see one tenant's rows via `MAX(id)` and produce a wrong
-- (too-low) realignment value, i.e. the exact bug this migration fixes.
--
-- Read-only against row data: every statement below only reads MAX(id) /
-- sequence state and calls `setval()` (sequence metadata). It contains no
-- UPDATE/DELETE/INSERT against any of these six tables (or any other
-- table) and cannot alter, renumber, or remove any existing row.
-- GREATEST(...) can only move a sequence forward, never backward, so this
-- is idempotent and safe to re-run - including re-running it after it was
-- already applied for the first three tables only (2026-09-18).
--
-- Apply in order:
--   1. Run this whole file once, in the Supabase SQL Editor, against the
--      target project (test project first, production only after
--      verification and explicit approval).
--   2. Deploy the application code changes (`database/id_sequence.py`,
--      `database/membership_queries.py`, `database/payment_queries.py`,
--      `database/cashbook_queries.py`, `routes/membership.py`).
--   3. Confirm via `tests/test_18_id_allocation.py`/
--      `tests/test_19_money_id_allocation.py`, or manually: register a
--      brand-new admin and create one enquiry/student/shift-slot/
--      membership+payment/cashbook entry.

BEGIN;

-- GREATEST(...) floors at 1, not 0: an empty table (e.g. a project where
-- shift_slots has no rows yet) has both MAX(id) and the sequence's own
-- last_value come back NULL/0, and setval(seq, 0, ...) errors ("value 0 is
-- out of bounds") because a fresh identity sequence's MINVALUE is 1, not 0.

SELECT setval(
  pg_get_serial_sequence('enquiries', 'enquiry_id'),
  GREATEST(
    1,
    (SELECT COALESCE(MAX(enquiry_id), 0) FROM enquiries),
    COALESCE(pg_sequence_last_value(pg_get_serial_sequence('enquiries', 'enquiry_id')), 0)
  ),
  true
);

SELECT setval(
  pg_get_serial_sequence('students', 'student_id'),
  GREATEST(
    1,
    (SELECT COALESCE(MAX(student_id), 0) FROM students),
    COALESCE(pg_sequence_last_value(pg_get_serial_sequence('students', 'student_id')), 0)
  ),
  true
);

SELECT setval(
  pg_get_serial_sequence('shift_slots', 'slot_id'),
  GREATEST(
    1,
    (SELECT COALESCE(MAX(slot_id), 0) FROM shift_slots),
    COALESCE(pg_sequence_last_value(pg_get_serial_sequence('shift_slots', 'slot_id')), 0)
  ),
  true
);

SELECT setval(
  pg_get_serial_sequence('memberships', 'membership_id'),
  GREATEST(
    1,
    (SELECT COALESCE(MAX(membership_id), 0) FROM memberships),
    COALESCE(pg_sequence_last_value(pg_get_serial_sequence('memberships', 'membership_id')), 0)
  ),
  true
);

SELECT setval(
  pg_get_serial_sequence('payments', 'payment_id'),
  GREATEST(
    1,
    (SELECT COALESCE(MAX(payment_id), 0) FROM payments),
    COALESCE(pg_sequence_last_value(pg_get_serial_sequence('payments', 'payment_id')), 0)
  ),
  true
);

SELECT setval(
  pg_get_serial_sequence('cashbook', 'entry_id'),
  GREATEST(
    1,
    (SELECT COALESCE(MAX(entry_id), 0) FROM cashbook),
    COALESCE(pg_sequence_last_value(pg_get_serial_sequence('cashbook', 'entry_id')), 0)
  ),
  true
);

COMMIT;

-- Sanity check - each seq_last_value should be >= that table's own
-- table_max_id. Run manually after applying to confirm the realignment.
SELECT 'enquiries' AS table_name,
       pg_sequence_last_value(pg_get_serial_sequence('enquiries', 'enquiry_id')) AS seq_last_value,
       (SELECT MAX(enquiry_id) FROM enquiries) AS table_max_id
UNION ALL
SELECT 'students',
       pg_sequence_last_value(pg_get_serial_sequence('students', 'student_id')),
       (SELECT MAX(student_id) FROM students)
UNION ALL
SELECT 'shift_slots',
       pg_sequence_last_value(pg_get_serial_sequence('shift_slots', 'slot_id')),
       (SELECT MAX(slot_id) FROM shift_slots)
UNION ALL
SELECT 'memberships',
       pg_sequence_last_value(pg_get_serial_sequence('memberships', 'membership_id')),
       (SELECT MAX(membership_id) FROM memberships)
UNION ALL
SELECT 'payments',
       pg_sequence_last_value(pg_get_serial_sequence('payments', 'payment_id')),
       (SELECT MAX(payment_id) FROM payments)
UNION ALL
SELECT 'cashbook',
       pg_sequence_last_value(pg_get_serial_sequence('cashbook', 'entry_id')),
       (SELECT MAX(entry_id) FROM cashbook);
