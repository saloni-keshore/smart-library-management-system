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
docs/MIRROR_TRACKER.md). As of 2026-07-24 (ADR-28, Phase 10 - the third
mirror-write fully removed), Supabase is also this table's only *write*
target - `record_payment()` no longer touches SQLite at all, and its
Supabase insert is strict (raises on failure), not best-effort: its callers
(`routes/membership.py`'s `create()`/`renew()`, `routes/payment.py`'s
`collect()`) catch `postgrest.exceptions.APIError` around this call, so a
payment failure still rolls back cleanly. As of 2026-07-24 (ADR-29), those
two routes' own SQLite writes were removed too, so this is now their only
caught exception type around this call, not one caught alongside
`sqlite3.Error` - see those routes' own comments and ADR-28/29 in
docs/DECISIONS.md.
"""

from datetime import date

from postgrest.exceptions import APIError

from database.cashbook_queries import insert_income_entry
from database.membership_queries import get_admin_students
from database.supabase_client import get_supabase_client


def _receipt_number_taken(supabase, receipt_number):
    resp = (
        supabase.table("payments")
        .select("payment_id")
        .eq("receipt_number", receipt_number)
        .limit(1)
        .execute()
    )
    return bool(resp.data)


def _max_claimed_sequence(supabase, prefix):
    """Highest `{prefix}-NNNNN` sequence number already claimed by *any*
    admin, or None if none exist yet.

    As of 2026-07-24 (ADR-28), `_receipt_number_taken()`'s uniqueness loops
    below query Supabase (a real network round trip per check) instead of
    local SQLite - a linear scan starting from a fixed floor (1001) is no
    longer safe once thousands of receipts share the same default "LIB"
    prefix, since the loop would need one round trip per already-claimed
    number before reaching a free one (confirmed live: 1281 sequential
    checks, 161 seconds, for a single fresh admin's first receipt). Both
    call sites below seed their starting point from this function's result
    instead, so the uniqueness loop only ever runs for the rare *actual*
    collision, not to walk past everything already claimed. Sequence
    numbers are zero-padded to a fixed width (%05d), so an ORDER BY on the
    text column itself sorts identically to numeric order - no need to
    fetch and parse every row to find the max.
    """

    resp = (
        supabase.table("payments")
        .select("receipt_number")
        .like("receipt_number", f"{prefix}-%")
        .order("receipt_number", desc=True)
        .limit(1)
        .execute()
    )
    if not resp.data:
        return None
    try:
        return int(resp.data[0]["receipt_number"].split("-")[1])
    except (IndexError, ValueError):
        return None


def generate_receipt_number(admin_id):
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

    As of 2026-07-24 (ADR-28), the uniqueness check (`_receipt_number_taken`)
    queries Supabase directly (was SQLite before, deliberately, back when
    Supabase was only a best-effort mirror that could lag - now that
    Supabase is the only copy of `payments`, checking anywhere else would be
    checking stale data). Both branches first call `_max_claimed_sequence()`
    to seed their starting point from the true global max for this prefix,
    rather than blindly starting from `next_receipt_number`/1001 and walking
    the uniqueness-check loop forward one network round trip at a time past
    every already-claimed number - see that function's docstring for the
    161-second live reproduction that made this necessary. The counter
    advance is still a separate Supabase write, not wrapped in the same
    transaction as the `payments` insert it's issued for - see TD-40 in
    docs/11_FUTURE_WORK.md for the narrow non-atomicity this leaves
    (unchanged by ADR-28).
    """

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
        max_claimed = _max_claimed_sequence(supabase, prefix)
        if max_claimed is not None and max_claimed + 1 > number:
            number = max_claimed + 1

        while _receipt_number_taken(supabase, f"{prefix}-{number:05d}"):
            number += 1

        supabase.table("library_settings").update(
            {"next_receipt_number": number + 1}
        ).eq("admin_id", admin_id).execute()
        return f"{prefix}-{number:05d}"

    prefix = "LIB"
    max_claimed = _max_claimed_sequence(supabase, prefix)
    sequence = (max_claimed + 1) if max_claimed is not None else 1001

    while _receipt_number_taken(supabase, f"{prefix}-{sequence:05d}"):
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


def get_payment_id_by_receipt_number(receipt_number):
    """Look up the payment_id a receipt_number belongs to.

    record_payment() only ever returned receipt_number (its long-standing
    return shape, kept as-is here). Callers that need the new payment's ID
    - to redirect to its receipt page, routes/payment.py's collect() and
    routes/membership.py's create()/renew() - use this instead of widening
    record_payment()'s return value. receipt_number is globally unique
    (enforced by generate_receipt_number()'s uniqueness loop), so this
    always resolves to at most one row.
    """

    supabase = get_supabase_client()
    resp = (
        supabase.table("payments")
        .select("payment_id")
        .eq("receipt_number", receipt_number)
        .limit(1)
        .execute()
    )
    return resp.data[0]["payment_id"] if resp.data else None


def record_payment(
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
    entry.

    Returns the generated receipt_number. Caller is still responsible for
    any membership-row update (paid_amount/pending_amount) and for its own
    SQLite mirror transaction (`memberships` isn't migrated yet - see
    docs/MIRROR_TRACKER.md).

    As of 2026-07-24 (ADR-28), Supabase is the only store - `payment_id` is
    computed explicitly (Supabase `MAX(payment_id) + 1`, the same pattern
    ADR-18/19/20/22/27 use for `enquiry_id`/`student_id`/`membership_id`/
    `entry_id`) rather than left to an auto-increment sequence, and the
    `payments` insert is strict: a failure raises `postgrest.exceptions.
    APIError` past this function, for the caller to catch and roll back -
    unlike the old SQLite-primary/Supabase-best-effort shape, there is no
    fallback store left to silently keep the payment in.
    """

    supabase = get_supabase_client()
    receipt_number = generate_receipt_number(admin_id)

    next_id_row = (
        supabase.table("payments")
        .select("payment_id")
        .order("payment_id", desc=True)
        .limit(1)
        .execute()
    )
    payment_id = (next_id_row.data[0]["payment_id"] + 1) if next_id_row.data else 1
    payment_date = date.today().isoformat()

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

    insert_income_entry(
        admin_id,
        category=category,
        person=student_name,
        description=description,
        amount=amount,
        payment_method=payment_mode,
        entry_date=payment_date,
        source=source,
        payment_id=payment_id
    )

    return receipt_number
