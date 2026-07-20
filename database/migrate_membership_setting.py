"""Create the per-admin membership settings table.

Run from the project root with:
    python database/migrate_membership_setting.py
"""

from db import get_connection


EXPECTED_COLUMNS = {
    "setting_id", "admin_id", "monthly_fee", "monthly_days",
    "quarterly_fee", "quarterly_days", "half_yearly_fee",
    "half_yearly_days", "yearly_fee", "yearly_days", "admission_fee",
    "late_fee_per_day", "renewal_grace_days", "auto_expiry",
    "allow_early_renewal", "send_reminders", "reminder_days",
    "created_at", "updated_at",
}


def run():
    conn = get_connection()
    cursor = conn.cursor()

    existing = cursor.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        ("membership_settings",),
    ).fetchone()

    if existing:
        columns = {
            row["name"] for row in cursor.execute(
                "PRAGMA table_info(membership_settings)"
            ).fetchall()
        }
        if not EXPECTED_COLUMNS.issubset(columns):
            conn.close()
            missing = ", ".join(sorted(EXPECTED_COLUMNS - columns))
            raise RuntimeError(
                "membership_settings has an incompatible schema. "
                f"Missing columns: {missing}"
            )

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS membership_settings (
            setting_id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER NOT NULL UNIQUE,
            monthly_fee REAL NOT NULL DEFAULT 0,
            monthly_days INTEGER NOT NULL DEFAULT 30,
            quarterly_fee REAL NOT NULL DEFAULT 0,
            quarterly_days INTEGER NOT NULL DEFAULT 90,
            half_yearly_fee REAL NOT NULL DEFAULT 0,
            half_yearly_days INTEGER NOT NULL DEFAULT 180,
            yearly_fee REAL NOT NULL DEFAULT 0,
            yearly_days INTEGER NOT NULL DEFAULT 365,
            admission_fee REAL NOT NULL DEFAULT 0,
            late_fee_per_day REAL NOT NULL DEFAULT 0,
            renewal_grace_days INTEGER NOT NULL DEFAULT 7,
            auto_expiry INTEGER NOT NULL DEFAULT 1 CHECK (auto_expiry IN (0, 1)),
            allow_early_renewal INTEGER NOT NULL DEFAULT 1 CHECK (allow_early_renewal IN (0, 1)),
            send_reminders INTEGER NOT NULL DEFAULT 1 CHECK (send_reminders IN (0, 1)),
            reminder_days INTEGER NOT NULL DEFAULT 3,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (admin_id) REFERENCES admins(admin_id)
        )
    """)

    conn.commit()
    conn.close()
    print("membership_settings table ready.")


if __name__ == "__main__":
    run()
