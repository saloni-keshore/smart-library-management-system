"""
Audit trail for every financial change made to the Cashbook ledger.

log_entry() takes a cursor from an already-open connection so the audit
row commits as part of the very same transaction as the Cashbook entry it
describes (same pattern as insert_income_entry in cashbook_queries.py) -
an audit row can never exist without the change it records, or vice versa.
"""

from database.db import get_connection


def log_entry(cursor, admin_id, entry_id, action, details):

    cursor.execute("""
        INSERT INTO audit_log (admin_id, entry_id, action, details)
        VALUES (?, ?, ?, ?)
    """, (admin_id, entry_id, action, details))


def get_recent_audit_log(admin_id, limit=15):
    """Latest financial changes for this admin, newest first."""

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT al.*, a.full_name AS performed_by
        FROM audit_log al
        LEFT JOIN admins a ON a.admin_id = al.admin_id
        WHERE al.admin_id = ?
        ORDER BY al.created_at DESC, al.log_id DESC
        LIMIT ?
    """, (admin_id, limit))

    rows = cursor.fetchall()
    conn.close()

    return rows
