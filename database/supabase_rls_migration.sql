-- Smart Library App - Shared-instance multi-tenant conversion (ADR-75/ADR-76)
--
-- Converts this database from "one admin per Supabase project" (ADR-53) to
-- a shared database where many libraries (tenants) coexist, isolated from
-- each other by Postgres Row-Level Security - not merely by application
-- code remembering an .eq("admin_id", ...) filter.
--
-- Run by hand, once, in the Supabase SQL Editor (this app has no DDL/
-- exec_sql RPC path, ADR-14) - AFTER database/supabase_migration.sql has
-- already been applied. Idempotent: every statement can be re-run safely.
--
-- IMPORTANT - apply in this exact order, on a fresh dev/test project
-- first, never directly on a project already serving real traffic:
--   1. Run the "1a: schema" section below alone and confirm it completes
--      cleanly (this is a pure additive/backfill change - the app can keep
--      running unmodified against the service-role key while this runs).
--   2. Deploy the application code changes (database/supabase_client.py,
--      app.py, routes/auth.py, utils/security.py) - with RLS still not
--      enabled yet, so a code bug surfaces as an error, not a silent
--      cross-tenant policy gap.
--   3. Run the "1b/1c: RLS + RPCs" and "Data lifecycle" sections below.
--   4. Run scripts/verify_tenant_isolation.py and confirm every check
--      passes before removing routes/auth.py's old registration gate (that
--      change ships separately, in application code).
--
-- Enabling RLS before step 1's backfill completes would make every
-- existing memberships/payments/membership_charges/panda_messages row
-- invisible to everyone at once (NULL admin_id never matches
-- current_admin_id()) - so 1a must fully commit before 1b runs.

-- =========================================================================
-- 1a. Close the admin_id-scoping gaps: add a direct column, backfill from
--     the existing join path, add the FK. Tables that had no tenant column
--     at all before this (ADR-2's "memberships and payments have no
--     admin_id at all" consequence).
-- =========================================================================

BEGIN;

ALTER TABLE memberships ADD COLUMN IF NOT EXISTS admin_id INTEGER;

UPDATE memberships m
SET admin_id = s.admin_id
FROM students s
WHERE m.student_id = s.student_id
  AND m.admin_id IS NULL;

ALTER TABLE memberships ALTER COLUMN admin_id SET NOT NULL;

ALTER TABLE memberships DROP CONSTRAINT IF EXISTS memberships_admin_id_fkey;
ALTER TABLE memberships
  ADD CONSTRAINT memberships_admin_id_fkey
  FOREIGN KEY (admin_id) REFERENCES admins(admin_id);


ALTER TABLE payments ADD COLUMN IF NOT EXISTS admin_id INTEGER;

UPDATE payments p
SET admin_id = s.admin_id
FROM students s
WHERE p.student_id = s.student_id
  AND p.admin_id IS NULL;

ALTER TABLE payments ALTER COLUMN admin_id SET NOT NULL;

ALTER TABLE payments DROP CONSTRAINT IF EXISTS payments_admin_id_fkey;
ALTER TABLE payments
  ADD CONSTRAINT payments_admin_id_fkey
  FOREIGN KEY (admin_id) REFERENCES admins(admin_id);


-- Must run after the memberships backfill above - depends on it.
ALTER TABLE membership_charges ADD COLUMN IF NOT EXISTS admin_id INTEGER;

UPDATE membership_charges mc
SET admin_id = m.admin_id
FROM memberships m
WHERE mc.membership_id = m.membership_id
  AND mc.admin_id IS NULL;

ALTER TABLE membership_charges ALTER COLUMN admin_id SET NOT NULL;

ALTER TABLE membership_charges DROP CONSTRAINT IF EXISTS membership_charges_admin_id_fkey;
ALTER TABLE membership_charges
  ADD CONSTRAINT membership_charges_admin_id_fkey
  FOREIGN KEY (admin_id) REFERENCES admins(admin_id);


ALTER TABLE panda_messages ADD COLUMN IF NOT EXISTS admin_id INTEGER;

UPDATE panda_messages pm
SET admin_id = pc.admin_id
FROM panda_conversations pc
WHERE pm.conversation_id = pc.conversation_id
  AND pm.admin_id IS NULL;

ALTER TABLE panda_messages ALTER COLUMN admin_id SET NOT NULL;

ALTER TABLE panda_messages DROP CONSTRAINT IF EXISTS panda_messages_admin_id_fkey;
ALTER TABLE panda_messages
  ADD CONSTRAINT panda_messages_admin_id_fkey
  FOREIGN KEY (admin_id) REFERENCES admins(admin_id);


-- expenses/cashbook already have admin_id (ADR-2) but no FK - add it while
-- touching every tenant-owned table for RLS anyway. cashbook.admin_id is
-- nullable (auto-generated rows may not always set it, see
-- docs/11_FUTURE_WORK.md TD-108) - NOT forced NOT NULL here; a NULL row
-- simply won't match any tenant's RLS policy (safe-by-default, invisible
-- to everyone) rather than blocking this migration.
ALTER TABLE expenses DROP CONSTRAINT IF EXISTS expenses_admin_id_fkey;
ALTER TABLE expenses
  ADD CONSTRAINT expenses_admin_id_fkey
  FOREIGN KEY (admin_id) REFERENCES admins(admin_id);

ALTER TABLE cashbook DROP CONSTRAINT IF EXISTS cashbook_admin_id_fkey;
ALTER TABLE cashbook
  ADD CONSTRAINT cashbook_admin_id_fkey
  FOREIGN KEY (admin_id) REFERENCES admins(admin_id);

-- Data lifecycle (ADR-76) columns - added here, before section 1c below
-- creates rpc_login_lookup() (which selects admins.status), not in the
-- "Data lifecycle" section further down, so that function's column
-- reference resolves at CREATE FUNCTION time.
ALTER TABLE admins ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active';
ALTER TABLE admins ADD COLUMN IF NOT EXISTS archived_at TIMESTAMP;

COMMIT;


-- =========================================================================
-- 1b. current_admin_id() helper + RLS on every tenant-owned table.
--
-- current_admin_id() reads the `admin_id` custom claim out of the request
-- JWT that database/supabase_client.py's build_tenant_client() mints per
-- request (role: authenticated). The anon role (pre-login) has no such
-- claim and current_admin_id() returns NULL for it, which never matches
-- any admin_id - so anon has zero table access anywhere, by construction.
-- =========================================================================

BEGIN;

CREATE OR REPLACE FUNCTION public.current_admin_id() RETURNS integer
LANGUAGE sql STABLE
AS $$
  SELECT NULLIF(
    current_setting('request.jwt.claims', true)::json->>'admin_id',
    ''
  )::integer
$$;

DO $$
DECLARE
  t text;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'enquiries', 'students', 'audit_log', 'library_settings',
    'membership_settings', 'backup_log', 'security_settings',
    'ai_center_settings', 'panda_conversations', 'shift_slots',
    'expenses', 'cashbook',
    'memberships', 'payments', 'membership_charges', 'panda_messages'
  ]
  LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('DROP POLICY IF EXISTS tenant_isolation ON %I', t);
    EXECUTE format(
      'CREATE POLICY tenant_isolation ON %I
         FOR ALL
         USING (admin_id = public.current_admin_id())
         WITH CHECK (admin_id = public.current_admin_id())',
      t
    );
  END LOOP;
END $$;

-- Dead/legacy tables (no route reads or writes them, docs/04_DATABASE_SCHEMA.md).
-- RLS enabled with zero policies = deny-all for anon/authenticated; costs
-- nothing, closes a theoretical future misuse.
ALTER TABLE settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE transactions ENABLE ROW LEVEL SECURITY;

-- A CREATE POLICY above is necessary but not sufficient - Postgres checks
-- the ordinary table-level GRANT first, and only evaluates RLS policies
-- once that passes. These tables were created by hand in the SQL Editor
-- (not the Supabase dashboard's Table Editor, which auto-grants anon/
-- authenticated on every table it creates), so `authenticated` - the role
-- every per-request app client authenticates as post-ADR-75
-- (database/supabase_client.py's build_tenant_client()) - was never
-- granted anything on them at all. Same class of gap TD-69 already found
-- for service_role's initial provisioning; this one went unnoticed until
-- now because every request used the service-role key (which needs no
-- grant - it bypasses privilege checks same as RLS) before ADR-75. Without
-- this, every tenant-scoped query fails with "permission denied for table
-- X" even though the policy above it is correct.
GRANT SELECT, INSERT, UPDATE, DELETE ON
  enquiries, students, audit_log, library_settings,
  membership_settings, backup_log, security_settings,
  ai_center_settings, panda_conversations, shift_slots,
  expenses, cashbook,
  memberships, payments, membership_charges, panda_messages
TO authenticated;

-- Several of these tables assign their own id explicitly (MAX+1, see
-- database/id_sequence.py and TD-108) rather than relying on the identity
-- column's default, but any that don't still need sequence USAGE to
-- accept an authenticated-role insert.
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO authenticated;

COMMIT;


-- =========================================================================
-- 1c. admins table policy + pre-login bootstrap RPCs.
--
-- admins has no broad SELECT/INSERT policy for anon - login, registration,
-- and forgot-password all go through these narrowly-scoped SECURITY
-- DEFINER functions instead, since "look up a row across all tenants by
-- username/mobile" can't be expressed as an admin_id-scoped RLS policy (no
-- tenant identity exists yet at that point in the flow).
-- =========================================================================

BEGIN;

ALTER TABLE admins ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS admins_self_select ON admins;
CREATE POLICY admins_self_select ON admins
  FOR SELECT
  USING (admin_id = public.current_admin_id());

DROP POLICY IF EXISTS admins_self_update ON admins;
CREATE POLICY admins_self_update ON admins
  FOR UPDATE
  USING (admin_id = public.current_admin_id())
  WITH CHECK (admin_id = public.current_admin_id());

-- Deliberately no INSERT/DELETE policy for any role - account creation and
-- deletion only ever happen through rpc_register_admin() and
-- rpc_delete_tenant_data() below, which run with the definer's elevated
-- privileges.

-- Matches the two policies above - SELECT/UPDATE only, no table-level
-- INSERT/DELETE grant (those only ever happen through the SECURITY DEFINER
-- RPCs, which don't need one). Same GRANT-before-RLS requirement as the
-- tenant-owned tables above.
GRANT SELECT, UPDATE ON admins TO authenticated;

CREATE OR REPLACE FUNCTION public.rpc_login_lookup(p_identifier text)
RETURNS TABLE (admin_id integer, username text, password text, status text)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT admin_id, username, password, status
  FROM admins
  WHERE username = p_identifier OR mobile = p_identifier
  LIMIT 1;
$$;

CREATE OR REPLACE FUNCTION public.rpc_forgot_password_lookup(p_mobile text)
RETURNS TABLE (admin_id integer, full_name text)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT admin_id, full_name FROM admins WHERE mobile = p_mobile LIMIT 1;
$$;

CREATE OR REPLACE FUNCTION public.rpc_reset_password(
  p_admin_id integer, p_new_password_hash text
) RETURNS void
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
  UPDATE admins SET password = p_new_password_hash WHERE admin_id = p_admin_id;
$$;

CREATE OR REPLACE FUNCTION public.rpc_register_admin(
  p_full_name text, p_username text, p_mobile text,
  p_email text, p_password_hash text
) RETURNS integer
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  new_id integer;
BEGIN
  IF EXISTS (SELECT 1 FROM admins WHERE username = p_username) THEN
    RAISE EXCEPTION 'username_taken' USING ERRCODE = 'unique_violation';
  END IF;
  IF EXISTS (SELECT 1 FROM admins WHERE mobile = p_mobile) THEN
    RAISE EXCEPTION 'mobile_taken' USING ERRCODE = 'unique_violation';
  END IF;
  INSERT INTO admins (full_name, username, mobile, email, password, role)
  VALUES (p_full_name, p_username, p_mobile, p_email, p_password_hash, 'Admin')
  RETURNING admins.admin_id INTO new_id;
  RETURN new_id;
END;
$$;

REVOKE ALL ON FUNCTION public.rpc_login_lookup(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.rpc_forgot_password_lookup(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.rpc_reset_password(integer, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.rpc_register_admin(text, text, text, text, text) FROM PUBLIC;

GRANT EXECUTE ON FUNCTION public.rpc_login_lookup(text) TO anon;
GRANT EXECUTE ON FUNCTION public.rpc_forgot_password_lookup(text) TO anon;
GRANT EXECUTE ON FUNCTION public.rpc_reset_password(integer, text) TO anon;
GRANT EXECUTE ON FUNCTION public.rpc_register_admin(text, text, text, text, text) TO anon;

COMMIT;


-- =========================================================================
-- Data lifecycle (ADR-76): account-level archive/delete, backing Settings
-- > Data & Backup's Export -> Confirm -> Archive/Delete flow
-- (routes/setting.py). Both RPCs derive the tenant from
-- current_admin_id() - neither takes an admin_id parameter - so an
-- authenticated caller can only ever archive/delete their own account.
-- =========================================================================

BEGIN;

-- admins.status/archived_at were added in section 1a above, before
-- rpc_login_lookup() (section 1c) was defined to select status.

CREATE OR REPLACE FUNCTION public.rpc_archive_tenant() RETURNS void
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
  UPDATE admins
  SET status = 'archived', archived_at = now()
  WHERE admin_id = public.current_admin_id();
$$;

-- One transaction, in FK-safe order (leaf tables first) - see the FK graph
-- in database/supabase_migration.sql. cashbook must be cleared before
-- payments (cashbook.payment_id -> payments), and audit_log before
-- cashbook (audit_log.entry_id -> cashbook) - the reverse of the order
-- these tables were originally created in.
CREATE OR REPLACE FUNCTION public.rpc_delete_tenant_data() RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  target_admin_id integer := public.current_admin_id();
BEGIN
  IF target_admin_id IS NULL THEN
    RAISE EXCEPTION 'not_authenticated';
  END IF;

  DELETE FROM audit_log WHERE admin_id = target_admin_id;
  DELETE FROM cashbook WHERE admin_id = target_admin_id;
  DELETE FROM membership_charges WHERE admin_id = target_admin_id;
  DELETE FROM payments WHERE admin_id = target_admin_id;
  DELETE FROM memberships WHERE admin_id = target_admin_id;
  DELETE FROM panda_messages WHERE admin_id = target_admin_id;
  DELETE FROM panda_conversations WHERE admin_id = target_admin_id;
  DELETE FROM expenses WHERE admin_id = target_admin_id;
  DELETE FROM shift_slots WHERE admin_id = target_admin_id;
  DELETE FROM security_settings WHERE admin_id = target_admin_id;
  DELETE FROM ai_center_settings WHERE admin_id = target_admin_id;
  DELETE FROM membership_settings WHERE admin_id = target_admin_id;
  DELETE FROM library_settings WHERE admin_id = target_admin_id;
  DELETE FROM backup_log WHERE admin_id = target_admin_id;
  DELETE FROM students WHERE admin_id = target_admin_id;
  DELETE FROM enquiries WHERE admin_id = target_admin_id;
  DELETE FROM admins WHERE admin_id = target_admin_id;
END;
$$;

REVOKE ALL ON FUNCTION public.rpc_archive_tenant() FROM PUBLIC;
REVOKE ALL ON FUNCTION public.rpc_delete_tenant_data() FROM PUBLIC;

GRANT EXECUTE ON FUNCTION public.rpc_archive_tenant() TO authenticated;
GRANT EXECUTE ON FUNCTION public.rpc_delete_tenant_data() TO authenticated;

COMMIT;
