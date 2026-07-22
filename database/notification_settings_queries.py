"""
Reusable, admin-isolated data access for Settings > Notification Settings.

Notification settings live on the same library_settings row as the Library
Profile (one row per admin_id) - there is no separate table. A row must
already exist (created from the Library Profile page) before notification
settings can be saved. This is also the single owner of reminder behaviour:
membership_settings.reminder_days/send_reminders are superseded by the
columns here (see docs/11_FUTURE_WORK.md).
"""

from flask import g

from database.db import get_connection


def get_notification_settings(admin_id):
    """This admin's library_settings row, or None if no profile exists yet."""

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM library_settings WHERE admin_id = ?", (admin_id,))
    row = cursor.fetchone()
    conn.close()

    return row


def get_notification_settings_cached(admin_id):
    """Same result as get_notification_settings(), memoized on flask.g.

    app.py's global inject_notification_summary() context processor and
    routes/dashboard.py's dashboard() both need this admin's settings row
    on the same request (every authenticated page load, in the context
    processor's case) - without this, that's two identical SELECTs per
    request instead of one.
    """

    cache_attr = f"_notification_settings_{admin_id}"

    if not hasattr(g, cache_attr):
        setattr(g, cache_attr, get_notification_settings(admin_id))

    return getattr(g, cache_attr)


def save_notification_settings(admin_id, data):
    """Update the reminder/channel/quiet-hours/dashboard columns for this admin.

    Assumes the library_settings row already exists (enforced by the route).
    """

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE library_settings
        SET reminder_7_days = ?,
            reminder_3_days = ?,
            reminder_1_day = ?,
            notify_on_expiry_day = ?,
            notify_after_expiry = ?,
            notify_in_app = ?,
            notify_sms = ?,
            notify_email = ?,
            notify_whatsapp = ?,
            quiet_hours_enabled = ?,
            quiet_hours_start = ?,
            quiet_hours_end = ?,
            quiet_hours_allow_critical = ?,
            dash_show_badge_count = ?,
            dash_show_expiry_today = ?,
            dash_show_expiry_tomorrow = ?,
            dash_show_overdue = ?,
            dash_show_pending_fees = ?,
            dash_show_new_admissions = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE admin_id = ?
    """, (
        data["reminder_7_days"], data["reminder_3_days"], data["reminder_1_day"],
        data["notify_on_expiry_day"], data["notify_after_expiry"],
        data["notify_in_app"], data["notify_sms"], data["notify_email"], data["notify_whatsapp"],
        data["quiet_hours_enabled"], data["quiet_hours_start"], data["quiet_hours_end"],
        data["quiet_hours_allow_critical"],
        data["dash_show_badge_count"], data["dash_show_expiry_today"],
        data["dash_show_expiry_tomorrow"], data["dash_show_overdue"],
        data["dash_show_pending_fees"], data["dash_show_new_admissions"],
        admin_id
    ))

    conn.commit()
    conn.close()
