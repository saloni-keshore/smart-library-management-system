"""Shared Supabase (PostgREST) client - the only database access layer in
the app as of 2026-07-25 (ADR-32, Phase 11), now that SQLite has been
removed entirely (see docs/DECISIONS.md).

Reads SUPABASE_URL / SUPABASE_SECRET_KEY from the environment (via .env in
development), the same variables test_supabase.py used to set up. Unlike a
short-lived per-request SQLite connection (the pattern this module
replaced - see ADR-32 for what used to live in the now-deleted
database/db.py), the Supabase client is a plain HTTP client wrapper, so a
single instance is created once and reused.
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
