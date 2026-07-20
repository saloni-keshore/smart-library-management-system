"""
Migration: add notification settings columns to library_settings.

Run once from the project root:
    python database/migrate_notification_settings.py

What it does:
  Adds the reminder-rule, channel, quiet-hours and dashboard-display columns
  used by Settings > Notification Settings to the existing library_settings
  table. Notification Settings becomes the single owner of reminder
  behaviour - membership_settings.reminder_days/send_reminders are left in
  place but no longer written to (see docs/11_FUTURE_WORK.md).
"""

from db import get_connection

NEW_COLUMNS = {
    # Reminder Rules
    "reminder_7_days": "INTEGER DEFAULT 1",
    "reminder_3_days": "INTEGER DEFAULT 1",
    "reminder_1_day": "INTEGER DEFAULT 1",
    "notify_on_expiry_day": "INTEGER DEFAULT 1",
    "notify_after_expiry": "INTEGER DEFAULT 1",
    # Channels
    "notify_in_app": "INTEGER DEFAULT 1",
    "notify_sms": "INTEGER DEFAULT 0",
    "notify_email": "INTEGER DEFAULT 0",
    "notify_whatsapp": "INTEGER DEFAULT 0",
    # Quiet Hours
    "quiet_hours_enabled": "INTEGER DEFAULT 0",
    "quiet_hours_start": "TEXT DEFAULT '22:00'",
    "quiet_hours_end": "TEXT DEFAULT '07:00'",
    "quiet_hours_allow_critical": "INTEGER DEFAULT 1",
    # Dashboard Notifications
    "dash_show_badge_count": "INTEGER DEFAULT 1",
    "dash_show_expiry_today": "INTEGER DEFAULT 1",
    "dash_show_expiry_tomorrow": "INTEGER DEFAULT 1",
    "dash_show_overdue": "INTEGER DEFAULT 1",
    "dash_show_pending_fees": "INTEGER DEFAULT 1",
    "dash_show_new_admissions": "INTEGER DEFAULT 1",
}


def run():

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("PRAGMA table_info(library_settings)")
    columns = {row["name"] for row in cursor.fetchall()}

    for name, definition in NEW_COLUMNS.items():
        if name not in columns:
            cursor.execute(f"ALTER TABLE library_settings ADD COLUMN {name} {definition}")
            print(f"  {name} column added.")
        else:
            print(f"  {name} column already exists.")

    conn.commit()
    conn.close()
    print("Migration complete.")


if __name__ == "__main__":
    run()
