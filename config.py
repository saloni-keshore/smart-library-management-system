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
    PERMANENT_SESSION_LIFETIME = timedelta(
        minutes=int(os.environ.get("SESSION_LIFETIME_MINUTES", "60"))
    )
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
