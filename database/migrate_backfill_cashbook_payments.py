"""
One-off data fix: backfill Cashbook Income entries for Payments rows that
predate the automatic Cashbook logging added to the Admission / Renewal /
Collect Payment routes.

Run once from the project root:
    python database/migrate_backfill_cashbook_payments.py

What it does:
  For every row in `payments` that has no corresponding automatic Cashbook
  entry, inserts one - using the same category/source convention the live
  routes use:
    - first payment recorded for a membership that followed an Expired
      membership for the same student -> "Membership Renewal" / Renewal
    - first payment recorded for any other membership                  -> "Admission Fee" / Admission
    - any later payment on the same membership                         -> "Membership Fee" / Payments
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import get_connection
from database.cashbook_queries import insert_income_entry


def run():

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT p.payment_id, p.membership_id, p.student_id, p.payment_mode,
               p.amount_paid, p.payment_date, p.remarks,
               s.full_name, s.admin_id, m.plan_name
        FROM payments p
        JOIN students s ON s.student_id = p.student_id
        JOIN memberships m ON m.membership_id = p.membership_id
        ORDER BY p.membership_id, p.payment_id
    """)
    payments = cursor.fetchall()

    cursor.execute("""
        SELECT membership_id, student_id, membership_status
        FROM memberships
        ORDER BY student_id, membership_id
    """)
    memberships = cursor.fetchall()

    # First membership_id per student that is preceded by an Expired
    # membership for the same student -> that membership was a renewal.
    renewal_membership_ids = set()
    by_student = {}
    for row in memberships:
        by_student.setdefault(row["student_id"], []).append(row)

    for rows in by_student.values():
        for previous, current in zip(rows, rows[1:]):
            if previous["membership_status"] == "Expired":
                renewal_membership_ids.add(current["membership_id"])

    seen_membership_ids = set()
    inserted = 0

    for payment in payments:

        # Every Cashbook entry created by the live routes carries the
        # student's name, exact amount and exact date - if one already
        # exists we treat this payment as already logged.
        cursor.execute("""
            SELECT 1 FROM cashbook
            WHERE admin_id = ? AND person = ? AND amount = ? AND entry_date = ?
            LIMIT 1
        """, (
            payment["admin_id"], payment["full_name"],
            payment["amount_paid"], payment["payment_date"]
        ))
        if cursor.fetchone():
            seen_membership_ids.add(payment["membership_id"])
            continue

        is_first_for_membership = payment["membership_id"] not in seen_membership_ids
        seen_membership_ids.add(payment["membership_id"])

        if is_first_for_membership and payment["membership_id"] in renewal_membership_ids:
            category, source, label = "Membership Renewal", "Renewal", "renewal"
        elif is_first_for_membership:
            category, source, label = "Admission Fee", "Admission", "admission"
        else:
            category, source, label = "Membership Fee", "Payments", "fee collection"

        insert_income_entry(
            conn,
            payment["admin_id"],
            category=category,
            person=payment["full_name"],
            description=payment["remarks"] or f"Backfilled {label} - {payment['plan_name']}",
            amount=payment["amount_paid"],
            payment_method=payment["payment_mode"],
            entry_date=payment["payment_date"],
            source=source
        )
        inserted += 1

    conn.commit()
    conn.close()

    print(f"  {inserted} historical payment(s) backfilled into the Cashbook.")
    print("Migration complete.")


if __name__ == "__main__":
    run()
