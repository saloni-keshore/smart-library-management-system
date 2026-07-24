"""
Reusable, admin-isolated data access for Settings > Security Settings.

One row per admin_id in security_settings. Kept separate from
library_settings so these preferences can be saved before a Library Profile
row exists.

Supabase's `security_settings` table is the source of truth (ADR-24) - see
database/settings_queries.py's module docstring for why no SQLite mirror is
kept (no other table enforces a foreign key against this one).
"""

from postgrest.exceptions import APIError

from database.settings_queries import _now_iso
from database.supabase_client import get_supabase_client

DEFAULTS = {
    "session_timeout_minutes": 60,
    "remember_me_enabled": 0,
    "login_notifications_enabled": 0,
}


def get_security_settings(admin_id):
    """This admin's security_settings row, or the defaults if none exists yet."""

    supabase = get_supabase_client()

    try:
        response = (
            supabase.table("security_settings")
            .select("*")
            .eq("admin_id", admin_id)
            .execute()
        )
    except APIError:
        return DEFAULTS

    return response.data[0] if response.data else DEFAULTS


def save_security_settings(admin_id, data):

    supabase = get_supabase_client()

    supabase.table("security_settings").upsert({
        "admin_id": admin_id,
        "session_timeout_minutes": data["session_timeout_minutes"],
        "remember_me_enabled": data["remember_me_enabled"],
        "login_notifications_enabled": data["login_notifications_enabled"],
        "updated_at": _now_iso(),
    }, on_conflict="admin_id").execute()
