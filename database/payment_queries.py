"""
Reusable, admin-isolated data access for the Payment workflow.

Single source of truth for recording a payment. Before this module existed,
`routes/membership.py` (`create`/`renew`) and `routes/payment.py` (`collect`)
each inlined their own `INSERT INTO payments` plus their own receipt-number
formula - three copies that had already drifted into two incompatible
formats and never read the receipt_prefix/next_receipt_number configured in
Settings > Receipt Settings (see docs/11_FUTURE_WORK.md TD-22). Every route
that ever creates a payment now goes through record_payment() here instead.
"""

from datetime import date

from database.cashbook_queries import insert_income_entry


def generate_receipt_number(conn, admin_id):
    """Allocate this admin's next receipt number, advancing the persisted
    counter (library_settings.next_receipt_number) in the same transaction
    as the payment it's issued for - if that transaction rolls back, the
    number is never consumed.

    Falls back to a count-based LIB-01001... sequence (same pattern as
    Cashbook's own _generate_reference_id) when this admin hasn't created a
    Library Profile yet, since there's no settings row to persist a counter
    on.
    """

    cursor = conn.cursor()
    cursor.execute(
        "SELECT receipt_prefix, next_receipt_number "
        "FROM library_settings WHERE admin_id = ?",
        (admin_id,)
    )
    settings = cursor.fetchone()

    if settings is not None:
        prefix = settings["receipt_prefix"] or "LIB"
        number = settings["next_receipt_number"] or 1001

        cursor.execute(
            "UPDATE library_settings SET next_receipt_number = ? "
            "WHERE admin_id = ?",
            (number + 1, admin_id)
        )
        return f"{prefix}-{number:05d}"

    prefix = "LIB"
    cursor.execute("""
        SELECT COUNT(*) AS total FROM payments p
        JOIN students s ON s.student_id = p.student_id
        WHERE s.admin_id = ? AND p.receipt_number LIKE ?
    """, (admin_id, f"{prefix}-%"))
    sequence = 1001 + cursor.fetchone()["total"]

    return f"{prefix}-{sequence:05d}"


def record_payment(
    conn,
    admin_id,
    membership_id,
    student_id,
    student_name,
    payment_mode,
    amount,
    remarks,
    category,
    description,
    source
):
    """Insert one `payments` row and its matching automatic Cashbook Income
    entry, atomically on the caller's already-open connection/transaction.

    Returns the generated receipt_number. Caller is still responsible for
    any membership-row update (paid_amount/pending_amount) and for
    conn.commit()/conn.close().
    """

    cursor = conn.cursor()
    receipt_number = generate_receipt_number(conn, admin_id)

    cursor.execute("""
        INSERT INTO payments
        (membership_id, student_id, receipt_number, payment_mode,
         amount_paid, payment_date, remarks)
        VALUES (?, ?, ?, ?, ?, DATE('now'), ?)
    """, (
        membership_id, student_id, receipt_number,
        payment_mode, amount, remarks
    ))

    payment_id = cursor.lastrowid

    insert_income_entry(
        conn,
        admin_id,
        category=category,
        person=student_name,
        description=description,
        amount=amount,
        payment_method=payment_mode,
        entry_date=date.today().isoformat(),
        source=source,
        payment_id=payment_id
    )

    return receipt_number
