"""
Migration: Audit Trail for the Cashbook ledger.

Run once from the project root:
    python database/migrate_audit_log.py

What it does:
  Creates the audit_log table so every automatic and manual Cashbook
  change (create/update) gets a permanent, admin-isolated log row.
"""

from db import get_connection


def run():

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER NOT NULL,
            entry_id INTEGER,
            action TEXT NOT NULL,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (admin_id) REFERENCES admins(admin_id),
            FOREIGN KEY (entry_id) REFERENCES cashbook(entry_id)
        )
    """)
    print("  audit_log table ready.")

    conn.commit()
    conn.close()
    print("Migration complete.")


if __name__ == "__main__":
    run()
