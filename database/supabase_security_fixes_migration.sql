-- Smart Library App - Post-ADR-75/76 security fixes (ADR-77)
--
-- Closes three gaps found in code review of the shared-instance multi-tenant
-- conversion (database/supabase_rls_migration.sql), all in the pre-login /
-- account-lifecycle surface that RLS itself can't cover (no tenant identity
-- exists yet, or the session predates a status change):
--
--   1. rpc_reset_password(p_admin_id, p_new_password_hash) trusted its
--      caller's admin_id with no identity check inside the function itself.
--      routes/auth.py's forgot_password() verified full_name+mobile in
--      Python before calling it, but the SECURITY DEFINER RPC was reachable
--      directly (GRANT EXECUTE ... TO anon) with just an admin_id - anyone
--      who could guess/enumerate an admin_id could reset any admin's
--      password, bypassing the Python-side check entirely.
--
--   2. rpc_login_lookup(p_identifier) returned the stored password column
--      (a werkzeug hash) to whoever called it, unconditionally - no password
--      required. Since it's GRANT EXECUTE ... TO anon (this app's Flask
--      backend calls it pre-login, but so could anyone else with the anon
--      key), this let a caller harvest any admin's password hash for
--      offline cracking by supplying only a known username/mobile.
--
--   3. current_admin_id() read the admin_id claim straight out of the
--      request JWT with no check of the admin's current status. An admin
--      archived mid-session (routes/setting.py's rpc_archive_tenant(),
--      ADR-76) kept full RLS access on every tenant table for the
--      remaining life of their already-issued tenant JWT (up to
--      _TENANT_JWT_TTL_SECONDS = 60s, and for any request that reused a
--      still-valid session before that JWT was re-minted).
--
-- Run by hand, once, in the Supabase SQL Editor (ADR-14 - no DDL/exec_sql
-- RPC path exists) - AFTER database/supabase_rls_migration.sql has already
-- been applied. Idempotent: every statement can be re-run safely.
--
-- Fix #2 requires verifying a password inside Postgres, which the existing
-- werkzeug scrypt hash format (admins.password, e.g.
-- "scrypt:32768:8:1$salt$hex") cannot do - Postgres/pgcrypto has no scrypt
-- verifier, only crypt()-based schemes (bcrypt via gen_salt('bf')). Rather
-- than force every admin (including saloni, admin_id=2) to reset their
-- password immediately, this migrates lazily: rpc_login_lookup now takes
-- the plaintext password too and verifies bcrypt-format hashes entirely in
-- SQL (hash never returned); for an admin whose hash is still in the old
-- scrypt format, it returns that hash ONE more time so routes/auth.py's
-- login() can verify it in Python exactly as before, then immediately
-- upgrades that admin's stored hash to bcrypt via rpc_migrate_password_hash
-- (SECURITY DEFINER, scoped to current_admin_id() - i.e. only callable with
-- a tenant JWT Flask itself minted for that exact admin_id, via
-- build_tenant_client()). After that one login, the hash never leaves
-- Postgres again for that admin. A password reset (rpc_reset_password)
-- still writes a scrypt-format hash (unchanged, out of scope for this fix -
-- see fix #1 above) - that admin will simply repeat the one-time legacy
-- upgrade on their next login, same as an account that never reset.
--
-- Apply in order:
--   1. Run this whole file.
--   2. Deploy the application code changes (routes/auth.py).
--   3. Confirm via scripts/verify_security_fixes.py (new - throwaway admin
--      accounts only, cleans up after itself, never touches admin_id=2).

BEGIN;

-- pgcrypto ships pre-installed on Supabase projects, usually in the
-- `extensions` schema rather than `public`. IF NOT EXISTS is a no-op if
-- it's already present anywhere; the explicit WITH SCHEMA only takes effect
-- on a project where it genuinely doesn't exist yet. Every function below
-- that calls crypt()/gen_salt() pins search_path to `public, extensions` so
-- the unqualified calls resolve either way.
CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA extensions;

COMMIT;


-- =========================================================================
-- Fix #3: current_admin_id() now returns NULL for an archived admin, not
-- just a claim-less request. This is the one function every RLS policy in
-- database/supabase_rls_migration.sql's section 1b/1c is built on, plus
-- rpc_archive_tenant()/rpc_delete_tenant_data() (ADR-76) - so this single
-- change revokes an archived admin's access everywhere at once, for the
-- remaining lifetime of any session/JWT issued before they were archived,
-- without needing a per-route status check.
--
-- SECURITY DEFINER (new) so its own `SELECT ... FROM admins` doesn't
-- recurse into the admins_self_select RLS policy (which itself calls
-- current_admin_id()) - it runs as the function owner, who by default
-- bypasses RLS on tables they own (same mechanism rpc_login_lookup etc.
-- already rely on to read admins directly despite RLS being enabled there).
-- =========================================================================

BEGIN;

CREATE OR REPLACE FUNCTION public.current_admin_id() RETURNS integer
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public
AS $$
  SELECT a.admin_id
  FROM admins a
  WHERE a.admin_id = NULLIF(
          current_setting('request.jwt.claims', true)::json->>'admin_id',
          ''
        )::integer
    AND a.status = 'active'
$$;

COMMIT;


-- =========================================================================
-- Fix #1: rpc_reset_password() now verifies full_name + mobile INSIDE the
-- SECURITY DEFINER function itself, the same check routes/auth.py's
-- forgot_password() already did in Python before calling it - so the check
-- can no longer be bypassed by calling the RPC directly with just an
-- admin_id. Signature changed (2 params -> 4), so the old 2-param function
-- must be dropped explicitly - CREATE OR REPLACE does not replace a
-- different overload, it would just add a second, still-insecure one.
-- =========================================================================

BEGIN;

DROP FUNCTION IF EXISTS public.rpc_reset_password(integer, text);

CREATE OR REPLACE FUNCTION public.rpc_reset_password(
  p_admin_id integer, p_full_name text, p_mobile text, p_new_password_hash text
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  UPDATE admins
  SET password = p_new_password_hash
  WHERE admin_id = p_admin_id
    AND mobile = p_mobile
    AND lower(full_name) = lower(p_full_name);

  IF NOT FOUND THEN
    RAISE EXCEPTION 'identity_mismatch';
  END IF;
END;
$$;

REVOKE ALL ON FUNCTION public.rpc_reset_password(integer, text, text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.rpc_reset_password(integer, text, text, text) TO anon;

COMMIT;


-- =========================================================================
-- Fix #2: rpc_login_lookup() now takes the plaintext password and verifies
-- it in SQL for bcrypt-format hashes (crypt() match => return admin_id/
-- username/status, legacy_hash NULL; no match => no row, same as "user not
-- found" - no information leak either way). For a still-scrypt-format hash,
-- it returns that hash ONE more time (legacy_hash non-null) so Python can
-- verify it exactly as before; routes/auth.py then calls
-- rpc_migrate_password_hash() to upgrade it, so this branch stops applying
-- to that admin from their next login onward.
--
-- Signature changed (1 param -> 2) - drop the old single-arg overload so it
-- can no longer be called directly to exfiltrate a hash with no password.
-- =========================================================================

BEGIN;

DROP FUNCTION IF EXISTS public.rpc_login_lookup(text);

CREATE OR REPLACE FUNCTION public.rpc_login_lookup(p_identifier text, p_password text)
RETURNS TABLE (admin_id integer, username text, status text, legacy_hash text)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, extensions
AS $$
DECLARE
  row_rec admins%ROWTYPE;
BEGIN
  SELECT * INTO row_rec FROM admins a
  WHERE a.username = p_identifier OR a.mobile = p_identifier
  LIMIT 1;

  IF NOT FOUND THEN
    RETURN;
  END IF;

  IF row_rec.password LIKE '$2%' THEN
    -- bcrypt-format hash (already migrated, or a hash pgcrypto itself
    -- wrote): verify entirely here, never return it.
    IF crypt(p_password, row_rec.password) = row_rec.password THEN
      RETURN QUERY SELECT row_rec.admin_id, row_rec.username, row_rec.status, NULL::text;
    END IF;
    RETURN;
  ELSE
    -- Legacy werkzeug hash: Postgres can't verify this format. Return it
    -- once so routes/auth.py can check it in Python and immediately
    -- upgrade it - see this file's header comment and rpc_migrate_
    -- password_hash() below. Returned regardless of whether p_password is
    -- actually correct (Python still makes that call), matching this
    -- function's pre-fix behavior for this one shrinking legacy case.
    RETURN QUERY SELECT row_rec.admin_id, row_rec.username, row_rec.status, row_rec.password;
  END IF;
END;
$$;

REVOKE ALL ON FUNCTION public.rpc_login_lookup(text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.rpc_login_lookup(text, text) TO anon;

-- Upgrades the CALLING admin's own stored hash to bcrypt. SECURITY DEFINER
-- + scoped by current_admin_id() (not a p_admin_id parameter) - only
-- callable with a valid tenant JWT for that exact admin_id, i.e. only
-- routes/auth.py's login(), immediately after it verifies a legacy hash
-- correct in Python via build_tenant_client(admin_id). GRANT is to
-- `authenticated` only (needs a signed tenant JWT), never `anon` - an
-- anon-reachable version of this with no proof-of-password-knowledge would
-- let anyone overwrite any admin's password outright, recreating fix #1's
-- bug in a new place.
CREATE OR REPLACE FUNCTION public.rpc_migrate_password_hash(p_plain_password text)
RETURNS void
LANGUAGE sql
SECURITY DEFINER
SET search_path = public, extensions
AS $$
  UPDATE admins
  SET password = crypt(p_plain_password, gen_salt('bf'))
  WHERE admin_id = public.current_admin_id();
$$;

REVOKE ALL ON FUNCTION public.rpc_migrate_password_hash(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.rpc_migrate_password_hash(text) TO authenticated;

COMMIT;


-- =========================================================================
-- Sanity check - run this SELECT by hand after the block above and confirm
-- it returns `t` (true) before deploying the application code changes.
-- Computes ONE bcrypt hash (one gen_salt('bf') call), then re-crypt()s the
-- same password against that same hash - crypt(pw, existing_hash) reuses
-- the salt embedded in existing_hash, so this is a true round-trip check,
-- not two independently-salted hashes compared against each other (an
-- earlier version of this check did that by mistake and always returned
-- false regardless of whether pgcrypto worked). If this errors with
-- "function crypt(...) does not exist", pgcrypto landed in a schema not
-- covered by search_path = public, extensions on this project; find its
-- actual schema with:
--   SELECT extnamespace::regnamespace FROM pg_extension WHERE extname = 'pgcrypto';
-- and add it to every SET search_path above.
-- =========================================================================

WITH h AS (
  SELECT crypt('sanity-check', gen_salt('bf')) AS hash
)
SELECT crypt('sanity-check', h.hash) = h.hash
AS pgcrypto_bcrypt_works
FROM h;

-- Dropped/recreated functions and a changed current_admin_id() body are DDL
-- PostgREST needs to know about - Supabase's hosted projects normally pick
-- this up automatically via a built-in schema-watch event trigger, but this
-- is a harmless, idempotent nudge if a call still 404s/PGRST202s right
-- after applying the block above.
NOTIFY pgrst, 'reload schema';
