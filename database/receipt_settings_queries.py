"""
Reusable, admin-isolated data access for Settings > Receipt Settings.

Receipt settings live on the same library_settings row as the Library
Profile (one row per admin_id) - there is no separate table. A row must
already exist (created from the Library Profile page) before receipt
settings can be saved.

Supabase's `library_settings` table is the source of truth (ADR-24) - see
database/settings_queries.py's module docstring for why no SQLite mirror is
kept.
"""

from postgrest.exceptions import APIError

from database.settings_queries import _now_iso
from database.supabase_client import get_supabase_client


def get_receipt_settings(admin_id):
    """This admin's library_settings row, or None if no profile exists yet."""

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

    return response.data[0] if response.data else None


def save_receipt_settings(admin_id, data):
    """Update the receipt numbering/branding/printing columns for this admin.

    Assumes the library_settings row already exists (enforced by the route).
    """

    supabase = get_supabase_client()

    supabase.table("library_settings").update({
        "receipt_prefix": data["receipt_prefix"],
        "next_receipt_number": data["next_receipt_number"],
        "auto_increment_receipt": data["auto_increment_receipt"],
        "print_logo": data["print_logo"],
        "print_stamp": data["print_stamp"],
        "print_signature": data["print_signature"],
        "paper_size": data["paper_size"],
        "auto_print": data["auto_print"],
        "auto_email": data["auto_email"],
        "open_pdf_after_save": data["open_pdf_after_save"],
        "duplicate_copy": data["duplicate_copy"],
        "receipt_footer": data["receipt_footer"],
        "updated_at": _now_iso(),
    }).eq("admin_id", admin_id).execute()
