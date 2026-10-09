"""Supabase (PostgREST) client construction - the only database access layer
in the app (ADR-32).

As of ADR-75, this app is a shared-database multi-tenant SaaS: many
libraries (tenants) share one Supabase project, isolated from each other by
Postgres Row-Level Security (RLS), not merely by application-code
convention. Because RLS is unconditionally bypassed by Supabase's
service-role key, per-request app traffic must NOT use that key - it must
authenticate as the `authenticated` Postgres role via a short-lived,
tenant-scoped JWT, so RLS policies actually apply. See
docs/DECISIONS.md ADR-75 and database/supabase_rls_migration.sql.

Five kinds of client exist here:
  - build_anon_client(): no tenant identity yet (pre-login). Can only call
    the SECURITY DEFINER admins-bootstrap RPCs (rpc_login_lookup,
    rpc_register_admin, rpc_record_login_failure) - RLS grants the `anon`
    role no table policies at all.
  - build_tenant_client(admin_id): scoped to one tenant via a freshly
    signed JWT, built fresh on every call - NEVER cached or reused across
    requests. The app runs multi-threaded (waitress); postgrest-py mutates
    a Client's auth header in place, so sharing one Client across
    concurrent requests from different tenants would be a data race, not
    just inefficient. A fresh httpx-backed Client costs no network I/O to
    construct.
  - build_pkce_auth_client(): an anon client whose Supabase Auth half is
    set up for the server-side Google OAuth (PKCE) flow, keeping the PKCE
    code verifier in the Flask session between /auth/google/start and
    /auth/google/callback (ADR-84).
  - build_pending_google_signup_client(): a narrowly scoped server JWT for
    reading/writing expiring pending Google signup credentials under RLS.
  - build_user_token_client(access_token): authenticated with a Supabase
    Auth user's own access token (from that Google code exchange), so
    rpc_google_login_lookup()/rpc_register_admin_google() can read the
    Google identity from auth.uid() - verified by Postgres, not by us.
  - get_service_role_client(): the old single-admin-per-database behavior,
    renamed and narrowed. Bypasses RLS entirely - only for offline
    scripts/tooling (scripts/*.py, test fixtures) that legitimately need
    cross-tenant access. NEVER import this from routes/ or
    database/*_queries.py.

app.py's `attach_tenant_supabase_client` before_request hook builds the
right client for the current request (anon or tenant-scoped, based on
session["admin_id"]) and stashes it on flask.g; get_supabase_client() below
just returns whatever that hook put there. This keeps every existing
call site (`from database.supabase_client import get_supabase_client`)
unchanged - only what the function returns has changed.
"""

import os
import time
from functools import lru_cache

import jwt
from dotenv import load_dotenv
from flask import g, has_request_context, session
from supabase import Client, create_client
from supabase.lib.client_options import SyncClientOptions
from supabase_auth import SyncSupportedStorage

load_dotenv()

_JWT_ALGORITHM = "HS256"
_TENANT_JWT_TTL_SECONDS = 60


def _url() -> str:
    url = os.environ.get("SUPABASE_URL")
    if not url:
        raise RuntimeError("SUPABASE_URL must be set before using Supabase-backed routes.")
    return url


def _anon_key() -> str:
    key = os.environ.get("SUPABASE_ANON_KEY")
    if not key:
        raise RuntimeError("SUPABASE_ANON_KEY must be set before using Supabase-backed routes.")
    return key


def _jwt_secret() -> str:
    secret = os.environ.get("SUPABASE_JWT_SECRET")
    if not secret:
        raise RuntimeError("SUPABASE_JWT_SECRET must be set before using Supabase-backed routes.")
    return secret


def build_anon_client() -> Client:
    """A request with no admin_id in session yet (pre-login). No table RLS
    policy grants this role anything - only the SECURITY DEFINER bootstrap
    RPCs in database/supabase_rls_migration.sql are reachable."""
    return create_client(_url(), _anon_key())


def build_tenant_client(admin_id: int, session_version: int | None = None) -> Client:
    """A brand-new client, scoped to admin_id for the lifetime of one
    request only, via a freshly signed JWT. Never cache or reuse this
    across requests - see module docstring.

    session_version (ADR-85) goes into the JWT as the `sv` claim;
    current_admin_id() rejects the JWT once the admin's
    admins.session_version has moved past it (logout, password change).
    Offline scripts/tests that omit it are not version-checked."""
    now = int(time.time())
    claims = {
        "role": "authenticated",
        "aud": "authenticated",
        "admin_id": admin_id,
        "iat": now,
        "exp": now + _TENANT_JWT_TTL_SECONDS,
    }
    if session_version is not None:
        claims["sv"] = int(session_version)
    token = jwt.encode(claims, _jwt_secret(), algorithm=_JWT_ALGORITHM)
    return create_client(
        _url(),
        _anon_key(),
        options=SyncClientOptions(headers={"Authorization": f"Bearer {token}"}),
    )


def build_pending_google_signup_client() -> Client:
    """A narrowly scoped server identity for pending Google signup rows.

    This JWT has no tenant identity. RLS grants its dedicated claim access to
    pending_google_signups; ordinary user and tenant JWTs cannot read or
    change those rows.
    """
    now = int(time.time())
    claims = {
        "role": "authenticated",
        "aud": "authenticated",
        "pending_google_signup_worker": True,
        "iat": now,
        "exp": now + 60,
    }
    token = jwt.encode(claims, _jwt_secret(), algorithm=_JWT_ALGORITHM)
    return create_client(
        _url(),
        _anon_key(),
        options=SyncClientOptions(headers={"Authorization": f"Bearer {token}"}),
    )


class _FlaskSessionStorage(SyncSupportedStorage):
    """Supabase Auth storage backed by the Flask session cookie. Only the
    PKCE code verifier ever lands here: it has to survive from
    /auth/google/start to /auth/google/callback, two separate requests
    that each build their own client."""

    _PREFIX = "sb_auth:"

    def get_item(self, key):
        return session.get(self._PREFIX + key)

    def set_item(self, key, value):
        session[self._PREFIX + key] = value

    def remove_item(self, key):
        session.pop(self._PREFIX + key, None)


def build_pkce_auth_client() -> Client:
    """Anon client for the Google OAuth PKCE flow (ADR-84). Never persists
    or auto-refreshes a Supabase Auth session - Flask's own session cookie
    stays the only login state. The exchanged Supabase Auth access token is
    used immediately for account lookup and, for new signup, is encrypted in
    the short-lived server-side pending-signup store."""
    return create_client(
        _url(),
        _anon_key(),
        options=SyncClientOptions(
            flow_type="pkce",
            storage=_FlaskSessionStorage(),
            auto_refresh_token=False,
            persist_session=False,
        ),
    )


def build_user_token_client(access_token: str) -> Client:
    """A client authenticated as a Supabase Auth user (their Google sign-in
    access token), for the two Google RPCs that read auth.uid()."""
    return create_client(
        _url(),
        _anon_key(),
        options=SyncClientOptions(headers={"Authorization": f"Bearer {access_token}"}),
    )


def get_supabase_client() -> Client:
    """Return the current request's Supabase client (tenant-scoped once
    logged in, anon otherwise), built once per request by app.py's
    `attach_tenant_supabase_client` before_request hook and cached on
    flask.g.

    Raises outside a request context - offline scripts/tooling that need
    cross-tenant access should call get_service_role_client() instead.
    """
    if not has_request_context() or not hasattr(g, "supabase"):
        raise RuntimeError(
            "get_supabase_client() requires an active Flask request (see "
            "app.py's attach_tenant_supabase_client before_request hook). "
            "Scripts/tooling running outside a request should use "
            "get_service_role_client() instead."
        )
    return g.supabase


@lru_cache(maxsize=1)
def get_service_role_client() -> Client:
    """DANGER: uses the service-role key, which bypasses Row-Level Security
    entirely - this client can read/write every tenant's data. Only for
    offline scripts/tooling (scripts/*.py, tests/conftest.py assertion
    helpers). Never import this from routes/ or database/*_queries.py."""
    key = os.environ.get("SUPABASE_SECRET_KEY")
    if not key:
        raise RuntimeError("SUPABASE_SECRET_KEY must be set to use get_service_role_client().")
    return create_client(_url(), key)
