-- Short-lived storage for Supabase Auth access tokens used only to finish
-- Google signup after the user submits the onboarding form.
-- Run on the TEST project first, then production only after explicit approval.

BEGIN;

CREATE TABLE IF NOT EXISTS public.pending_google_signups (
  lookup_hash text PRIMARY KEY CHECK (lookup_hash ~ '^[0-9a-f]{64}$'),
  encrypted_access_token text NOT NULL,
  google_email text NOT NULL DEFAULT '',
  profile_name text NOT NULL DEFAULT '',
  created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  CONSTRAINT pending_google_signups_expiry_window CHECK (
    expires_at > created_at
    AND expires_at <= created_at + interval '10 minutes'
  )
);

CREATE INDEX IF NOT EXISTS pending_google_signups_expiry_idx
  ON public.pending_google_signups (expires_at);

ALTER TABLE public.pending_google_signups ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.pending_google_signups FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, DELETE ON public.pending_google_signups TO authenticated;

DROP POLICY IF EXISTS pending_google_signup_worker_select ON public.pending_google_signups;
CREATE POLICY pending_google_signup_worker_select
  ON public.pending_google_signups FOR SELECT TO authenticated
  USING (
    (current_setting('request.jwt.claims', true)::jsonb ->> 'pending_google_signup_worker') = 'true'
    AND expires_at > now()
  );

DROP POLICY IF EXISTS pending_google_signup_worker_insert ON public.pending_google_signups;
CREATE POLICY pending_google_signup_worker_insert
  ON public.pending_google_signups FOR INSERT TO authenticated
  WITH CHECK (
    (current_setting('request.jwt.claims', true)::jsonb ->> 'pending_google_signup_worker') = 'true'
    AND expires_at > now()
    AND expires_at <= now() + interval '10 minutes'
  );

DROP POLICY IF EXISTS pending_google_signup_worker_delete ON public.pending_google_signups;
CREATE POLICY pending_google_signup_worker_delete
  ON public.pending_google_signups FOR DELETE TO authenticated
  USING (
    (current_setting('request.jwt.claims', true)::jsonb ->> 'pending_google_signup_worker') = 'true'
  );

COMMIT;
