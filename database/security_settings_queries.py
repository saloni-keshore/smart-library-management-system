"""
Reusable, admin-isolated data access for Settings > Security Settings.

One row per admin_id in security_settings. Kept separate from
library_settings so these preferences can be saved before a Library Profile
row exists.
"""

from database.db import get_connection

DEFAULTS = {
    "session_timeout_minutes": 60,
    "remember_me_enabled": 0,
    "login_notifications_enabled": 0,
}


def get_security_settings(admin_id):
    """This admin's security_settings row, or the defaults if none exists yet."""

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM security_settings WHERE admin_id = ?", (admin_id,))
    row = cursor.fetchone()
    conn.close()

    return row if row else DEFAULTS


def save_security_settings(admin_id, data):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO security_settings (
            admin_id, session_timeout_minutes, remember_me_enabled, login_notifications_enabled
        )
        VALUES (?, ?, ?, ?)
        ON CONFLICT(admin_id)
        DO UPDATE SET
            session_timeout_minutes = excluded.session_timeout_minutes,
            remember_me_enabled = excluded.remember_me_enabled,
            login_notifications_enabled = excluded.login_notifications_enabled,
            updated_at = CURRENT_TIMESTAMP
    """, (
        admin_id, data["session_timeout_minutes"],
        data["remember_me_enabled"], data["login_notifications_enabled"]
    ))

    conn.commit()
    conn.close()
