"""
Reusable, admin-isolated data access for Settings > Notification Settings.

Notification settings live on the same library_settings row as the Library
Profile (one row per admin_id) - there is no separate table. A row must
already exist (created from the Library Profile page) before notification
settings can be saved. This is also the single owner of reminder behaviour:
membership_settings.reminder_days/send_reminders are superseded by the
columns here (see docs/11_FUTURE_WORK.md).

Supabase's `library_settings` table is the source of truth (ADR-24) - see
database/settings_queries.py's module docstring for why no SQLite mirror is
kept.
"""

from flask import g
from postgrest.exceptions import APIError

from database.settings_queries import _now_iso
from database.supabase_client import get_supabase_client


def get_notification_settings(admin_id):
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


def get_notification_settings_cached(admin_id):
    """Same result as get_notification_settings(), memoized on flask.g.

    app.py's global inject_notification_summary() context processor and
    routes/dashboard.py's dashboard() both need this admin's settings row
    on the same request (every authenticated page load, in the context
    processor's case) - without this, that's two identical Supabase reads
    per request instead of one.
    """

    cache_attr = f"_notification_settings_{admin_id}"

    if not hasattr(g, cache_attr):
        setattr(g, cache_attr, get_notification_settings(admin_id))

    return getattr(g, cache_attr)


def save_notification_settings(admin_id, data):
    """Update the reminder/channel/quiet-hours/dashboard columns for this admin.

    Assumes the library_settings row already exists (enforced by the route).
    """

    supabase = get_supabase_client()

    supabase.table("library_settings").update({
        "reminder_7_days": data["reminder_7_days"],
        "reminder_3_days": data["reminder_3_days"],
        "reminder_1_day": data["reminder_1_day"],
        "notify_on_expiry_day": data["notify_on_expiry_day"],
        "notify_after_expiry": data["notify_after_expiry"],
        "notify_in_app": data["notify_in_app"],
        "notify_sms": data["notify_sms"],
        "notify_email": data["notify_email"],
        "notify_whatsapp": data["notify_whatsapp"],
        "quiet_hours_enabled": data["quiet_hours_enabled"],
        "quiet_hours_start": data["quiet_hours_start"],
        "quiet_hours_end": data["quiet_hours_end"],
        "quiet_hours_allow_critical": data["quiet_hours_allow_critical"],
        "dash_show_badge_count": data["dash_show_badge_count"],
        "dash_show_expiry_today": data["dash_show_expiry_today"],
        "dash_show_expiry_tomorrow": data["dash_show_expiry_tomorrow"],
        "dash_show_overdue": data["dash_show_overdue"],
        "dash_show_pending_fees": data["dash_show_pending_fees"],
        "dash_show_new_admissions": data["dash_show_new_admissions"],
        "updated_at": _now_iso(),
    }).eq("admin_id", admin_id).execute()
