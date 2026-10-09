"""Short-lived server-side storage for new Google signup credentials."""

import base64
import hashlib
from datetime import datetime, timezone

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app

from database.supabase_client import build_pending_google_signup_client


def _fernet():
    secret = current_app.config.get("SECRET_KEY")
    if not secret:
        raise RuntimeError("SECRET_KEY must be configured for pending Google signup storage.")
    # Domain-separated key derivation from the existing server-side secret.
    key = hashlib.sha256(
        b"smart-library:pending-google-signup:v1\0" + str(secret).encode("utf-8")
    ).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def _lookup_hash(lookup_id):
    return hashlib.sha256(lookup_id.encode("utf-8")).hexdigest()


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def save_pending_google_signup(lookup_id, access_token, expires_at, email, name):
    """Persist signup data using a random opaque handle and strict TTL."""
    client = build_pending_google_signup_client()
    now = _now_iso()
    # Opportunistically remove expired records on writes. Reads also reject
    # expired rows in the query and RLS policy, independent of cleanup timing.
    client.table("pending_google_signups").delete().lte("expires_at", now).execute()
    encrypted = _fernet().encrypt(access_token.encode("utf-8")).decode("ascii")
    client.table("pending_google_signups").insert({
        "lookup_hash": _lookup_hash(lookup_id),
        "encrypted_access_token": encrypted,
        "google_email": email,
        "profile_name": name,
        "expires_at": datetime.fromtimestamp(expires_at, timezone.utc).isoformat(),
    }).execute()


def get_pending_google_signup_token(lookup_id):
    """Return valid signup data for this opaque handle, or None if expired."""
    row = (
        build_pending_google_signup_client()
        .table("pending_google_signups")
        .select("encrypted_access_token,google_email,profile_name")
        .eq("lookup_hash", _lookup_hash(lookup_id))
        .gt("expires_at", _now_iso())
        .limit(1)
        .execute()
        .data
    )
    if not row:
        return None
    try:
        access_token = _fernet().decrypt(
            row[0]["encrypted_access_token"].encode("ascii")
        ).decode("utf-8")
        return {
            "access_token": access_token,
            "email": row[0]["google_email"],
            "name": row[0]["profile_name"],
        }
    except (InvalidToken, KeyError, UnicodeDecodeError):
        # A key rotation or corrupted row must fail closed and discard it.
        delete_pending_google_signup(lookup_id)
        return None


def delete_pending_google_signup(lookup_id):
    build_pending_google_signup_client().table("pending_google_signups").delete().eq(
        "lookup_hash", _lookup_hash(lookup_id)
    ).execute()
