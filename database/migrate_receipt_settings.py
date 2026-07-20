"""
Migration: add receipt settings columns to library_settings.

Run once from the project root:
    python database/migrate_receipt_settings.py

What it does:
  Adds the receipt numbering, branding and printing columns used by
  Settings > Receipt Settings to the existing library_settings table.
  receipt_footer already exists (see migrate_settings_receipt_footer.py)
  and is reused as-is.
"""

from db import get_connection

NEW_COLUMNS = {
    "receipt_prefix": "TEXT DEFAULT 'LIB'",
    "next_receipt_number": "INTEGER DEFAULT 1001",
    "auto_increment_receipt": "INTEGER DEFAULT 1",
    "print_logo": "INTEGER DEFAULT 1",
    "print_stamp": "INTEGER DEFAULT 1",
    "print_signature": "INTEGER DEFAULT 1",
    "paper_size": "TEXT DEFAULT 'A4'",
    "auto_print": "INTEGER DEFAULT 0",
    "auto_email": "INTEGER DEFAULT 0",
    "open_pdf_after_save": "INTEGER DEFAULT 1",
    "duplicate_copy": "INTEGER DEFAULT 0",
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
