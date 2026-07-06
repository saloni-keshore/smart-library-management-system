"""
Migration: add receipt_footer to library_settings.

Run once from the project root:
    python database/migrate_settings_receipt_footer.py

What it does:
  Adds the receipt_footer column (custom message printed at the bottom of
  receipts) to the existing library_settings table.
"""

from db import get_connection


def run():

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("PRAGMA table_info(library_settings)")
    columns = {row["name"] for row in cursor.fetchall()}

    if "receipt_footer" not in columns:
        cursor.execute("ALTER TABLE library_settings ADD COLUMN receipt_footer TEXT")
        print("  receipt_footer column added.")
    else:
        print("  receipt_footer column already exists.")

    conn.commit()
    conn.close()
    print("Migration complete.")


if __name__ == "__main__":
    run()
