"""Create the per-admin backup log table.

Run from the project root with:
    python database/migrate_backup_log.py
"""

from db import get_connection

EXPECTED_COLUMNS = {
    "log_id", "admin_id", "last_backup_at", "backup_filename",
}


def run():
    conn = get_connection()
    cursor = conn.cursor()

    existing = cursor.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        ("backup_log",),
    ).fetchone()

    if existing:
        columns = {
            row["name"] for row in cursor.execute(
                "PRAGMA table_info(backup_log)"
            ).fetchall()
        }
        if not EXPECTED_COLUMNS.issubset(columns):
            conn.close()
            missing = ", ".join(sorted(EXPECTED_COLUMNS - columns))
            raise RuntimeError(
                "backup_log has an incompatible schema. "
                f"Missing columns: {missing}"
            )

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS backup_log (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER NOT NULL UNIQUE,
            last_backup_at TIMESTAMP,
            backup_filename TEXT,
            FOREIGN KEY (admin_id) REFERENCES admins(admin_id)
        )
    """)

    conn.commit()
    conn.close()
    print("backup_log table ready.")


if __name__ == "__main__":
    run()
