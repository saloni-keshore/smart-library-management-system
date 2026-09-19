-- Smart Library App - Danger Zone / Security Settings password-verification
-- crash fix (ADR-80, TD-112)
--
-- Root cause: `routes/setting.py`'s `_danger_zone_confirmation_error()`
-- (Settings > Data & Backup > Archive/Delete) and `security_settings()`'s
-- password-change branch (Settings > Security Settings) both called
-- Werkzeug's `check_password_hash()` directly on `admins.password`.
-- Werkzeug only parses its own `method$salt$hash` format (scrypt/pbkdf2) -
-- since ADR-77's lazy bcrypt migration
-- (`database/supabase_security_fixes_migration.sql`) rewrites
-- `admins.password` to bcrypt (`$2b$...`) the moment an admin next logs in,
-- any admin who has logged in even once since ADR-77 shipped crashed
-- confirming their own current password on either page: Werkzeug's
-- `_hash_internal()` raises an unhandled `ValueError` on a bcrypt hash,
-- which was never caught, surfacing as an HTTP 500.
--
-- Fix: a SECURITY DEFINER RPC that verifies the CALLING admin's own
-- password without a bcrypt hash ever reaching Python - mirrors
-- `rpc_login_lookup()`'s two-branch shape: a bcrypt hash is checked
-- entirely in SQL via pgcrypto's `crypt()`; a still-legacy scrypt hash is
-- returned ONCE so Python can check it with `check_password_hash()` exactly
-- as before (the same one-time round-trip `rpc_login_lookup()` already
-- uses for login). No new Python dependency - this app's dependency
-- footprint was deliberately trimmed (ADR-78/TD-111, Vercel serverless
-- bundle-size limit), so verification stays in Postgres/pgcrypto rather
-- than adding a `bcrypt` package.
--
-- Run by hand, once, in the Supabase SQL Editor (ADR-14), AFTER
-- `database/supabase_security_fixes_migration.sql` (this depends on
-- `current_admin_id()` and the `extensions.crypt()` availability that file
-- establishes). Idempotent - CREATE OR REPLACE.

BEGIN;

CREATE OR REPLACE FUNCTION public.rpc_verify_current_password(p_password text)
RETURNS TABLE (is_valid boolean, legacy_hash text)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, extensions
AS $$
DECLARE
  row_rec admins%ROWTYPE;
BEGIN
  SELECT * INTO row_rec FROM admins a WHERE a.admin_id = public.current_admin_id();

  IF NOT FOUND THEN
    RETURN QUERY SELECT false, NULL::text;
    RETURN;
  END IF;

  IF row_rec.password LIKE '$2%' THEN
    -- bcrypt-format hash: verify entirely here, never return it.
    RETURN QUERY SELECT (crypt(p_password, row_rec.password) = row_rec.password), NULL::text;
  ELSE
    -- Legacy werkzeug hash: Postgres can't verify this format. Return it
    -- once so routes/setting.py can check it in Python exactly as before -
    -- same one-time shape rpc_login_lookup() uses.
    RETURN QUERY SELECT NULL::boolean, row_rec.password;
  END IF;
END;
$$;

REVOKE ALL ON FUNCTION public.rpc_verify_current_password(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.rpc_verify_current_password(text) TO authenticated;

COMMIT;

NOTIFY pgrst, 'reload schema';
