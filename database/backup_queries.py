"""
Reusable, admin-isolated data access for Settings > Data & Backup.

One row per admin_id in backup_log, tracking the most recent manual backup
taken from the Data & Backup page. Kept separate from library_settings so a
backup can be recorded before a Library Profile row exists.
"""

from database.db import get_connection


def get_backup_info(admin_id):
    """This admin's backup_log row, or None if no backup has been taken yet."""

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM backup_log WHERE admin_id = ?", (admin_id,))
    row = cursor.fetchone()
    conn.close()

    return row


def record_backup(admin_id, backup_filename):
    """Record that a backup was just taken for this admin."""

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO backup_log (admin_id, last_backup_at, backup_filename)
        VALUES (?, CURRENT_TIMESTAMP, ?)
        ON CONFLICT(admin_id)
        DO UPDATE SET
            last_backup_at = CURRENT_TIMESTAMP,
            backup_filename = excluded.backup_filename
    """, (admin_id, backup_filename))

    conn.commit()
    conn.close()
