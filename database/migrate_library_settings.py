"""
Migration: Library Settings (Settings > Library Profile).

Run once from the project root:
    python database/migrate_library_settings.py

What it does:
  Creates the library_settings table so each admin can store their own
  library profile (name, contact info, hours, logo/stamp/signature).
"""

from db import get_connection


def run():

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS library_settings (
            setting_id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER NOT NULL UNIQUE,
            library_name TEXT NOT NULL,
            owner_name TEXT,
            phone TEXT NOT NULL,
            email TEXT,
            address TEXT,
            city TEXT,
            state TEXT,
            pincode TEXT,
            opening_time TEXT,
            closing_time TEXT,
            weekly_holiday TEXT,
            logo_path TEXT,
            stamp_path TEXT,
            signature_path TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (admin_id) REFERENCES admins(admin_id)
        )
    """)
    print("  library_settings table ready.")

    conn.commit()
    conn.close()
    print("Migration complete.")


if __name__ == "__main__":
    run()
