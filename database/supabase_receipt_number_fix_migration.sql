-- Smart Library App - Global receipt-number uniqueness fix (ADR-82, TD-113)
--
-- Root cause: `payments.receipt_number` is `UNIQUE` *globally*, not per
-- admin (database/supabase_migration.sql) - by design, per
-- `database/payment_queries.py`'s own `generate_receipt_number()`
-- docstring: "Two different admins who share the same prefix... reach the
-- same sequence position... and collide". `_max_claimed_sequence()` /
-- `_receipt_number_taken()` were written to see every tenant's claimed
-- receipt numbers before ADR-75's shared-database multi-tenant conversion,
-- but both query through the app's tenant-scoped, Row-Level-Security-
-- filtered client - so under RLS they can only ever see the CALLING
-- tenant's own receipts, silently reintroducing the exact cross-tenant
-- collision they exist to prevent. Confirmed live on the test project
-- (2026-09-19): a brand-new admin's very first payment failed with
-- `duplicate key value violates unique constraint "payments_receipt_
-- number_key"` - not hypothetical, and already caught (but not explained)
-- by the pre-existing regression test
-- `tests/test_09_full_workflow_chain.py::
-- test_receipt_numbers_globally_unique_across_two_fresh_admins`.
--
-- Found during the same ADR-81 audit that fixed `memberships.membership_id`
-- / `payments.payment_id` / `cashbook.entry_id` (see
-- database/supabase_id_sequence_fix_migration.sql) - but this one needs a
-- different fix shape: `receipt_number` is a formatted TEXT column
-- ("LIB-01001"), not an integer identity PK, so there is no Postgres
-- sequence to fall back on the way ADR-79/81 do.
--
-- Fix: a SECURITY DEFINER RPC computes the next available receipt sequence
-- number for a prefix, checking global uniqueness entirely in Postgres
-- (bypassing RLS, same mechanism as ADR-80's rpc_verify_current_password) -
-- Python no longer does the uniqueness loop itself against an
-- RLS-filtered view.
--
-- Run by hand, once, in the Supabase SQL Editor (ADR-14) - AFTER
-- database/supabase_security_fixes_migration.sql (depends on `payments`
-- existing and RLS being enabled). Idempotent - CREATE OR REPLACE.

BEGIN;

CREATE OR REPLACE FUNCTION public.rpc_next_receipt_number(p_prefix text, p_floor integer)
RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  candidate integer;
BEGIN
  SELECT GREATEST(
    p_floor,
    COALESCE(
      (
        SELECT MAX(substring(receipt_number from length(p_prefix) + 2)::integer)
        FROM payments
        WHERE receipt_number LIKE p_prefix || '-%'
          AND substring(receipt_number from length(p_prefix) + 2) ~ '^[0-9]+$'
      ),
      0
    ) + 1
  ) INTO candidate;

  WHILE EXISTS (
    SELECT 1 FROM payments
    WHERE receipt_number = p_prefix || '-' || lpad(candidate::text, 5, '0')
  ) LOOP
    candidate := candidate + 1;
  END LOOP;

  RETURN candidate;
END;
$$;

REVOKE ALL ON FUNCTION public.rpc_next_receipt_number(text, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.rpc_next_receipt_number(text, integer) TO authenticated;

COMMIT;

NOTIFY pgrst, 'reload schema';
