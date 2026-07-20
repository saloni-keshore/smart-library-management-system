"""
Reusable, admin-isolated data access for Settings > Receipt Settings.

Receipt settings live on the same library_settings row as the Library
Profile (one row per admin_id) - there is no separate table. A row must
already exist (created from the Library Profile page) before receipt
settings can be saved.
"""

from database.db import get_connection


def get_receipt_settings(admin_id):
    """This admin's library_settings row, or None if no profile exists yet."""

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM library_settings WHERE admin_id = ?", (admin_id,))
    row = cursor.fetchone()
    conn.close()

    return row


def save_receipt_settings(admin_id, data):
    """Update the receipt numbering/branding/printing columns for this admin.

    Assumes the library_settings row already exists (enforced by the route).
    """

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE library_settings
        SET receipt_prefix = ?,
            next_receipt_number = ?,
            auto_increment_receipt = ?,
            print_logo = ?,
            print_stamp = ?,
            print_signature = ?,
            paper_size = ?,
            auto_print = ?,
            auto_email = ?,
            open_pdf_after_save = ?,
            duplicate_copy = ?,
            receipt_footer = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE admin_id = ?
    """, (
        data["receipt_prefix"], data["next_receipt_number"],
        data["auto_increment_receipt"], data["print_logo"],
        data["print_stamp"], data["print_signature"], data["paper_size"],
        data["auto_print"], data["auto_email"], data["open_pdf_after_save"],
        data["duplicate_copy"], data["receipt_footer"], admin_id
    ))

    conn.commit()
    conn.close()
