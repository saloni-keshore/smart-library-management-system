"""Small, dependency-free security helpers for the Flask application."""

import hmac
import secrets
import threading
import time
from collections import defaultdict, deque
from functools import wraps

from flask import current_app, flash, redirect, request, session, url_for

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
    """Limit sensitive form actions per source IP. Suitable for one-process SQLite deployments."""
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
