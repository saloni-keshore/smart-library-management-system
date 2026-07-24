"""
Reusable, admin-isolated data access for the Settings > Library Profile page.

One row per admin_id, same isolation pattern as Cashbook and Enquiries:
no admin can ever see or overwrite another admin's library profile.

Supabase's `library_settings` table is the source of truth (ADR-24) - no
SQLite mirror is kept, since no other SQLite table enforces a foreign key
against this one (unlike enquiries/students/memberships/cashbook/audit_log,
library_settings is a leaf table in the FK graph - see
docs/MIRROR_TRACKER.md).
"""

from datetime import datetime, timezone

from postgrest.exceptions import APIError

from database.supabase_client import get_supabase_client


def _now_iso():
    """Current UTC timestamp as an ISO string, for columns this module
    stamps explicitly (Supabase has no auto-update-on-write trigger for
    `updated_at`, only a DEFAULT on insert - the SQLite column's
    `UPDATE ... updated_at = CURRENT_TIMESTAMP` had to be replaced with an
    explicit value on every write)."""

    return datetime.now(timezone.utc).isoformat()


def _normalize_timestamps(row):
    """Supabase returns ISO timestamps with a 'T' separator
    ("2026-07-23T15:15:09.123+00:00"); the old SQLite column used a space
    ("2026-07-23 15:15:09"), which routes/setting.py's library_profile()
    slices to the first 16 characters for display. Normalize back to a
    space so that slice keeps producing the same "YYYY-MM-DD HH:MM" shape
    regardless of backend."""

    for key in ("created_at", "updated_at"):
        if row.get(key):
            row[key] = row[key].replace("T", " ")
    return row


def get_library_settings(admin_id):
    """This admin's library profile, or None if it hasn't been saved yet."""

    supabase = get_supabase_client()

    try:
        response = (
            supabase.table("library_settings")
            .select("*")
            .eq("admin_id", admin_id)
            .execute()
        )
    except APIError:
        return None

    if not response.data:
        return None

    return _normalize_timestamps(dict(response.data[0]))


def create_library_settings(admin_id, data):
    """Insert the first-ever library profile row for this admin."""

    supabase = get_supabase_client()

    supabase.table("library_settings").insert({
        "admin_id": admin_id,
        "library_name": data["library_name"],
        "owner_name": data["owner_name"],
        "phone": data["phone"],
        "email": data["email"],
        "address": data["address"],
        "city": data["city"],
        "state": data["state"],
        "pincode": data["pincode"],
        "opening_time": data["opening_time"],
        "closing_time": data["closing_time"],
        "weekly_holiday": data["weekly_holiday"],
        "logo_path": data["logo_path"],
        "stamp_path": data["stamp_path"],
        "signature_path": data["signature_path"],
        "receipt_footer": data["receipt_footer"],
    }).execute()


def update_library_settings(admin_id, data):
    """Update the existing library profile row for this admin.

    The caller (route) has already resolved logo_path/stamp_path/
    signature_path to their final value - keep the old path, use the newly
    uploaded one, or None to clear it - so this just writes what it's given.
    """

    supabase = get_supabase_client()

    supabase.table("library_settings").update({
        "library_name": data["library_name"],
        "owner_name": data["owner_name"],
        "phone": data["phone"],
        "email": data["email"],
        "address": data["address"],
        "city": data["city"],
        "state": data["state"],
        "pincode": data["pincode"],
        "opening_time": data["opening_time"],
        "closing_time": data["closing_time"],
        "weekly_holiday": data["weekly_holiday"],
        "logo_path": data["logo_path"],
        "stamp_path": data["stamp_path"],
        "signature_path": data["signature_path"],
        "receipt_footer": data["receipt_footer"],
        "updated_at": _now_iso(),
    }).eq("admin_id", admin_id).execute()


def save_library_settings(admin_id, data):
    """Upsert: create the row on first save, update it on every save after."""

    if get_library_settings(admin_id) is None:
        create_library_settings(admin_id, data)
    else:
        update_library_settings(admin_id, data)


def clear_library_logo(admin_id):
    """Clear just the logo path, used by the standalone Remove Logo action."""

    supabase = get_supabase_client()

    supabase.table("library_settings").update({
        "logo_path": None,
        "updated_at": _now_iso(),
    }).eq("admin_id", admin_id).execute()
