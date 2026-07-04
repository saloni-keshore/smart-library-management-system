"""
Migration: Cashbook becomes the financial ledger.

Run once from the project root:
    python database/migrate_cashbook_ledger.py

What it does:
  Adds reference_id and source columns to the cashbook table so every
  entry (automatic or manual) can carry a unique reference number and
  record where it came from (Admission, Renewal, Payments, Cashbook
  Manual Entry).
"""

from db import get_connection


def run():

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("PRAGMA table_info(cashbook)")
    existing = [r["name"] for r in cursor.fetchall()]

    if "reference_id" not in existing:
        cursor.execute("ALTER TABLE cashbook ADD COLUMN reference_id TEXT")
        print("  cashbook.reference_id added.")
    else:
        print("  cashbook.reference_id already exists — skipped.")

    if "source" not in existing:
        cursor.execute("ALTER TABLE cashbook ADD COLUMN source TEXT")
        print("  cashbook.source added.")
    else:
        print("  cashbook.source already exists — skipped.")

    conn.commit()
    conn.close()
    print("Migration complete.")


if __name__ == "__main__":
    run()
