"""
Reusable, admin-isolated data access for the Settings > Library Profile page.

One row per admin_id, same isolation pattern as Cashbook and Enquiries:
no admin can ever see or overwrite another admin's library profile.
"""

from database.db import get_connection


def get_library_settings(admin_id):
    """This admin's library profile, or None if it hasn't been saved yet."""

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM library_settings WHERE admin_id = ?", (admin_id,))
    row = cursor.fetchone()
    conn.close()

    return row


def create_library_settings(admin_id, data):
    """Insert the first-ever library profile row for this admin."""

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO library_settings (
            admin_id, library_name, owner_name, phone, email, address,
            city, state, pincode, opening_time, closing_time, weekly_holiday,
            logo_path, stamp_path, signature_path, receipt_footer
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        admin_id, data["library_name"], data["owner_name"], data["phone"],
        data["email"], data["address"], data["city"], data["state"],
        data["pincode"], data["opening_time"], data["closing_time"],
        data["weekly_holiday"], data["logo_path"], data["stamp_path"],
        data["signature_path"], data["receipt_footer"]
    ))

    conn.commit()
    conn.close()


def update_library_settings(admin_id, data):
    """Update the existing library profile row for this admin.

    The caller (route) has already resolved logo_path/stamp_path/
    signature_path to their final value - keep the old path, use the newly
    uploaded one, or None to clear it - so this just writes what it's given.
    """

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE library_settings
        SET library_name = ?,
            owner_name = ?,
            phone = ?,
            email = ?,
            address = ?,
            city = ?,
            state = ?,
            pincode = ?,
            opening_time = ?,
            closing_time = ?,
            weekly_holiday = ?,
            logo_path = ?,
            stamp_path = ?,
            signature_path = ?,
            receipt_footer = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE admin_id = ?
    """, (
        data["library_name"], data["owner_name"], data["phone"],
        data["email"], data["address"], data["city"], data["state"],
        data["pincode"], data["opening_time"], data["closing_time"],
        data["weekly_holiday"], data["logo_path"], data["stamp_path"],
        data["signature_path"], data["receipt_footer"], admin_id
    ))

    conn.commit()
    conn.close()


def save_library_settings(admin_id, data):
    """Upsert: create the row on first save, update it on every save after."""

    if get_library_settings(admin_id) is None:
        create_library_settings(admin_id, data)
    else:
        update_library_settings(admin_id, data)


def clear_library_logo(admin_id):
    """Clear just the logo path, used by the standalone Remove Logo action."""

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE library_settings
        SET logo_path = NULL, updated_at = CURRENT_TIMESTAMP
        WHERE admin_id = ?
    """, (admin_id,))

    conn.commit()
    conn.close()
