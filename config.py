"""Runtime configuration. Production secrets are supplied through the environment."""

import os
from datetime import timedelta

from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY")
    SESSION_COOKIE_NAME = "smart_library_session"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "true").lower() == "true"
    # How long a "Remember Me" login lasts since the last visit (ADR-87).
    # Flask also uses this as the maximum age of any session cookie's
    # signature, so it is the hard cap for every session, remembered or not.
    PERMANENT_SESSION_LIFETIME = timedelta(
        days=int(os.environ.get("REMEMBER_ME_DAYS", "7"))
    )
    # Idle timeout for a login without "Remember Me" when the admin's own
    # Settings -> Security value can't be read (and for sessions that
    # predate ADR-87) - see utils/security.py's expire_idle_session().
    SESSION_IDLE_TIMEOUT_MINUTES = int(os.environ.get("SESSION_LIFETIME_MINUTES", "60"))
    MAX_CONTENT_LENGTH = 5 * 1024 * 1024
    CSRF_ENABLED = True
    # Shows the "Continue with Google" / "Recover with Google" buttons
    # (ADR-84). Only turn on once the Google provider is configured in
    # Supabase Auth - see docs/DEPLOYMENT.md.
    GOOGLE_AUTH_ENABLED = os.environ.get("GOOGLE_AUTH_ENABLED", "false").lower() == "true"
    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")


class DevelopmentConfig(Config):
    DEBUG = True
    SESSION_COOKIE_SECURE = False


class ProductionConfig(Config):
    DEBUG = False
    TESTING = False
