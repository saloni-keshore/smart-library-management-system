"""Create the per-admin security settings table.

Run from the project root with:
    python database/migrate_security_settings.py
"""

from db import get_connection

EXPECTED_COLUMNS = {
    "setting_id", "admin_id", "session_timeout_minutes",
    "remember_me_enabled", "login_notifications_enabled",
    "created_at", "updated_at",
}


def run():
    conn = get_connection()
    cursor = conn.cursor()

    existing = cursor.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        ("security_settings",),
    ).fetchone()

    if existing:
        columns = {
            row["name"] for row in cursor.execute(
                "PRAGMA table_info(security_settings)"
            ).fetchall()
        }
        if not EXPECTED_COLUMNS.issubset(columns):
            conn.close()
            missing = ", ".join(sorted(EXPECTED_COLUMNS - columns))
            raise RuntimeError(
                "security_settings has an incompatible schema. "
                f"Missing columns: {missing}"
            )

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS security_settings (
            setting_id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER NOT NULL UNIQUE,
            session_timeout_minutes INTEGER NOT NULL DEFAULT 60,
            remember_me_enabled INTEGER NOT NULL DEFAULT 0 CHECK (remember_me_enabled IN (0, 1)),
            login_notifications_enabled INTEGER NOT NULL DEFAULT 0 CHECK (login_notifications_enabled IN (0, 1)),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (admin_id) REFERENCES admins(admin_id)
        )
    """)

    conn.commit()
    conn.close()
    print("security_settings table ready.")


if __name__ == "__main__":
    run()
