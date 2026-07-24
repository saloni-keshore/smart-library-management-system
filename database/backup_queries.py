"""
Reusable, admin-isolated data access for Settings > Data & Backup.

One row per admin_id in backup_log, tracking the most recent manual backup
taken from the Data & Backup page. Kept separate from library_settings so a
backup can be recorded before a Library Profile row exists.

Supabase's `backup_log` table is the source of truth (ADR-24) - see
database/settings_queries.py's module docstring for why no SQLite mirror is
kept (no other table enforces a foreign key against this one).
"""

from postgrest.exceptions import APIError

from database.settings_queries import _now_iso
from database.supabase_client import get_supabase_client


def get_backup_info(admin_id):
    """This admin's backup_log row, or None if no backup has been taken yet."""

    supabase = get_supabase_client()

    try:
        response = (
            supabase.table("backup_log")
            .select("*")
            .eq("admin_id", admin_id)
            .execute()
        )
    except APIError:
        return None

    return response.data[0] if response.data else None


def record_backup(admin_id, backup_filename):
    """Record that a backup was just taken for this admin."""

    supabase = get_supabase_client()

    supabase.table("backup_log").upsert({
        "admin_id": admin_id,
        "last_backup_at": _now_iso(),
        "backup_filename": backup_filename,
    }, on_conflict="admin_id").execute()
