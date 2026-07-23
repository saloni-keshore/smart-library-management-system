"""Shared Supabase (PostgREST) client for app code migrated off SQLite.

Reads SUPABASE_URL / SUPABASE_SECRET_KEY from the environment (via .env in
development), the same variables test_supabase.py and
database/migrate_to_supabase.py already use. Unlike database.db.get_connection()
(a short-lived per-request SQLite connection), the Supabase client is a
plain HTTP client wrapper, so a single instance is created once and reused.
"""

import os
from functools import lru_cache

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()


@lru_cache(maxsize=1)
def get_supabase_client() -> Client:
    """Return a cached, process-wide Supabase client."""
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SECRET_KEY")
    if not url:
        raise RuntimeError("SUPABASE_URL must be set before using Supabase-backed routes.")
    if not key:
        raise RuntimeError("SUPABASE_SECRET_KEY must be set before using Supabase-backed routes.")
    return create_client(url, key)
