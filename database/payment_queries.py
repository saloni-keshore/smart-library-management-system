"""
Reusable, admin-isolated data access for the Payment workflow.

Single source of truth for recording a payment. Before this module existed,
`routes/membership.py` (`create`/`renew`) and `routes/payment.py` (`collect`)
each inlined their own `INSERT INTO payments` plus their own receipt-number
formula - three copies that had already drifted into two incompatible
formats and never read the receipt_prefix/next_receipt_number configured in
Settings > Receipt Settings (see docs/11_FUTURE_WORK.md TD-22). Every route
that ever creates a payment now goes through record_payment() here instead.

As of 2026-07-24 (ADR-25), Supabase `payments` is the source of truth for
every *read* (`routes/payment.py`'s `index()`, `utils/charts.py`'s
`generate_revenue_chart()`, `database/cashbook_queries.py`'s
`get_today_fee_collection()`/`get_total_fee_revenue()`, etc. - see
docs/MIRROR_TRACKER.md). `record_payment()` here still writes SQLite as the
primary path, unchanged, and best-effort mirrors the identical row into
Supabase afterward - the same shape ADR-22 established for
`database/cashbook_queries.py`'s `insert_income_entry()`, for the same
reason: this function is called mid-transaction, on a connection
`routes/membership.py`/`routes/payment.py` opened, own, and roll back
themselves, and giving them a new caught exception type would expand this
slice's scope back into those two files. See TD-41 in
docs/11_FUTURE_WORK.md for the narrower staleness window this leaves.
"""

from datetime import date

from postgrest.exceptions import APIError

from database.cashbook_queries import insert_income_entry
from database.membership_queries import get_admin_students
from database.supabase_client import get_supabase_client


def _receipt_number_taken(cursor, receipt_number):
    cursor.execute(
        "SELECT 1 FROM payments WHERE receipt_number = ?",
        (receipt_number,)
    )
    return cursor.fetchone() is not None


def generate_receipt_number(conn, admin_id):
    """Allocate this admin's next receipt number, advancing the persisted
    counter (Supabase `library_settings.next_receipt_number`, ADR-24).

    Falls back to a count-based LIB-01001... sequence (same pattern as
    Cashbook's own _generate_reference_id) when this admin hasn't created a
    Library Profile yet, since there's no settings row to persist a counter
    on.

    `payments.receipt_number` is UNIQUE *globally*, not per admin, but both
    paths above compute `number`/`sequence` from this admin's own counter or
    this admin's own payment count alone. Two different admins who share the
    same prefix (every admin defaults to "LIB" until they customize it in
    Settings > Receipt Settings) reach the same sequence position - most
    obviously both admins' very first receipt, "LIB-01001" - and collide,
    which previously surfaced as an unhandled UNIQUE constraint failure that
    silently discarded the payment. Skipping forward past any number already
    claimed (by any admin) keeps every allocated receipt number actually
    unique while leaving the common, non-colliding case unchanged.

    The counter advance is a separate Supabase write, no longer inside the
    same SQLite transaction as the `payments` row it's issued for (`payments`
    itself is still SQLite, unmigrated) - if that SQLite transaction rolls
    back after this returns, the counter has already advanced and won't roll
    back with it. This narrows, but doesn't remove, the original design's own
    non-atomicity (the receipt-number availability check below was never
    itself race-free against a concurrent request either) - see TD-40 in
    docs/11_FUTURE_WORK.md.
    """

    cursor = conn.cursor()
    supabase = get_supabase_client()
    settings_response = (
        supabase.table("library_settings")
        .select("receipt_prefix, next_receipt_number")
        .eq("admin_id", admin_id)
        .execute()
    )
    settings = settings_response.data[0] if settings_response.data else None

    if settings is not None:
        prefix = settings["receipt_prefix"] or "LIB"
        number = settings["next_receipt_number"] or 1001

        while _receipt_number_taken(cursor, f"{prefix}-{number:05d}"):
            number += 1

        supabase.table("library_settings").update(
            {"next_receipt_number": number + 1}
        ).eq("admin_id", admin_id).execute()
        return f"{prefix}-{number:05d}"

    prefix = "LIB"
    sequence = 1001 + len(get_payments_for_admin(admin_id, prefix=prefix))

    while _receipt_number_taken(cursor, f"{prefix}-{sequence:05d}"):
        sequence += 1

    return f"{prefix}-{sequence:05d}"


def get_payments_for_admin(admin_id, prefix=None):
    """Every payment belonging to this admin's students, each row enriched
    with that student's full_name - the Python-side equivalent of
    `payments p JOIN students s ON p.student_id = s.student_id WHERE
    s.admin_id = ?`, since PostgREST has no cross-table JOIN in the client
    this codebase uses (same shape as
    database.membership_queries.get_memberships_for_admin()). Optionally
    narrowed to receipt numbers starting with `prefix` (used by
    generate_receipt_number()'s no-Library-Profile-yet fallback, which only
    needs a count, not full rows).
    """

    students = get_admin_students(admin_id)
    if not students:
        return []
    students_by_id = {s["student_id"]: s for s in students}

    supabase = get_supabase_client()
    try:
        response = (
            supabase.table("payments")
            .select("*")
            .in_("student_id", list(students_by_id.keys()))
            .execute()
        )
        payments = response.data
    except APIError:
        payments = []

    for p in payments:
        p["full_name"] = students_by_id.get(p["student_id"], {}).get("full_name")

    if prefix:
        payments = [p for p in payments if (p.get("receipt_number") or "").startswith(f"{prefix}-")]

    return payments


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

    SQLite is the primary write, unchanged from before ADR-25 - `payment_id`
    is computed explicitly (SQLite `MAX(payment_id) + 1`, the same pattern
    ADR-18/19/20/22 use for `enquiry_id`/`student_id`/`membership_id`/
    `entry_id`) rather than left to SQLite's `AUTOINCREMENT`, so the exact
    same id can be used for the best-effort Supabase mirror-write below.
    """

    cursor = conn.cursor()
    receipt_number = generate_receipt_number(conn, admin_id)

    next_id_row = cursor.execute("SELECT IFNULL(MAX(payment_id), 0) AS m FROM payments").fetchone()
    payment_id = next_id_row["m"] + 1
    payment_date = date.today().isoformat()

    cursor.execute("""
        INSERT INTO payments
        (payment_id, membership_id, student_id, receipt_number, payment_mode,
         amount_paid, payment_date, remarks)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        payment_id, membership_id, student_id, receipt_number,
        payment_mode, amount, payment_date, remarks
    ))

    try:
        supabase = get_supabase_client()
        supabase.table("payments").insert({
            "payment_id": payment_id,
            "membership_id": membership_id,
            "student_id": student_id,
            "receipt_number": receipt_number,
            "payment_mode": payment_mode,
            "amount_paid": amount,
            "payment_date": payment_date,
            "remarks": remarks,
        }).execute()
    except APIError:
        # Best-effort mirror only - see module docstring (TD-41) for why
        # this must never block the caller's own SQLite transaction.
        pass

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
