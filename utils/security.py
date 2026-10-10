"""Small, dependency-free security helpers for the Flask application."""

import hmac
import secrets
import threading
import time
from collections import defaultdict, deque
from functools import wraps

import httpx
from flask import current_app, flash, redirect, request, session, url_for
from postgrest.exceptions import APIError

from database.supabase_client import get_supabase_client

_attempts = defaultdict(deque)
_attempt_lock = threading.Lock()


def csrf_token():
    return session.setdefault("_csrf_token", secrets.token_urlsafe(32))


def validate_csrf():
    if not current_app.config.get("CSRF_ENABLED", True) or current_app.testing:
        return True
    submitted = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token")
    expected = session.get("_csrf_token")
    return bool(expected and submitted and hmac.compare_digest(expected, submitted))


def rate_limited(limit=5, window_seconds=300):
    """Limit sensitive form actions per source IP. State (`_attempts`) is an
    in-process dict, not persisted anywhere - suitable only for a
    single-process deployment, independent of which database backend is in
    use (multiple workers would each track their own separate counts)."""
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if request.method != "POST" or current_app.testing:
                return view(*args, **kwargs)
            key = (view.__name__, request.remote_addr or "unknown")
            now = time.monotonic()
            with _attempt_lock:
                attempts = _attempts[key]
                while attempts and attempts[0] <= now - window_seconds:
                    attempts.popleft()
                if len(attempts) >= limit:
                    flash("Too many attempts. Please try again later.", "danger")
                    return redirect(url_for("auth.login"))
                attempts.append(now)
            return view(*args, **kwargs)
        return wrapped
    return decorator


def clear_rate_limit(action):
    """Clear prior failed attempts after a successful sensitive operation."""
    with _attempt_lock:
        _attempts.pop((action, request.remote_addr or "unknown"), None)


# expire_idle_session() only rewrites session["last_seen"] (and so the
# cookie) this often, not on every request.
LAST_SEEN_REFRESH_SECONDS = 60


def expire_idle_session():
    """End a login that was made without "Remember Me" once it has been
    idle longer than the admin's Session Timeout (ADR-87). Runs as app.py's
    first before_request hook - before attach_tenant_supabase_client - so
    an expired session never gets a tenant-scoped Supabase client.

    session["idle_timeout"] is in seconds, set by routes/auth.py's
    start_admin_session(); 0 means "Never". A remembered session is not
    idle-limited - Flask's PERMANENT_SESSION_LIFETIME bounds it instead."""
    if "admin_id" not in session or request.endpoint == "static":
        return

    now = int(time.time())
    last_seen = session.get("last_seen")

    if last_seen is None:
        # Logged in before ADR-87: treat as an un-remembered session on the
        # default timeout, starting its idle clock now.
        session["remember"] = False
        session.permanent = False
        session["idle_timeout"] = current_app.config["SESSION_IDLE_TIMEOUT_MINUTES"] * 60
        session["last_seen"] = now
        return

    try:
        idle_timeout = int(session.get("idle_timeout") or 0)
        idle_seconds = now - int(last_seen)
    except (TypeError, ValueError):
        idle_timeout, idle_seconds = 1, 2  # unreadable values: end the session

    if not session.get("remember") and idle_timeout > 0 and idle_seconds > idle_timeout:
        session.clear()
        flash("Your session has ended. Please log in again.", "warning")
        return

    if idle_seconds >= LAST_SEEN_REFRESH_SECONDS:
        session["last_seen"] = now


# How often login_required re-asks the database whether this session is
# still valid (ADR-85). RLS already refuses a revoked session's data on
# every query; this only turns "empty pages" into a clean redirect.
SESSION_RECHECK_SECONDS = 300


def _session_still_valid():
    """False once this session was revoked (logout elsewhere, password
    change) or the account archived. Sessions from before ADR-85 have no
    `sv` and can't be revoked, so they are ended once here."""
    if "sv" not in session:
        return False
    now = int(time.time())
    if now - int(session.get("sv_checked_at", 0)) < SESSION_RECHECK_SECONDS:
        return True
    try:
        valid = bool(get_supabase_client().rpc("rpc_session_valid").execute().data)
    except (APIError, httpx.HTTPError):
        # A database hiccup must not log people out; RLS still guards data.
        return True
    if valid:
        session["sv_checked_at"] = now
    return valid


def login_required(view):
    """Replaces the `if "admin_id" not in session: return redirect("/")`
    check duplicated inline across every route file. App-layer
    defense-in-depth on top of Row-Level Security (ADR-75), not a
    replacement for it - RLS is what actually makes cross-tenant data
    inaccessible; this decorator's job is to keep an unauthenticated (or
    revoked, ADR-85) visitor from ever seeing a broken/empty page instead
    of being sent to login."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "admin_id" not in session:
            return redirect("/")
        if not _session_still_valid():
            session.clear()
            flash("Your session has ended. Please log in again.", "warning")
            return redirect("/")
        return view(*args, **kwargs)
    return wrapped
