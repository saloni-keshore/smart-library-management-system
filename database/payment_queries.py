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
from utils.normalization import normalize_category


# ---------------------------------------------------------------------------
# Idempotency (TD-30, ADR-53) - same undefined-column/unique-violation
# detection shape as database/membership_queries.py's own copies of these
# two helpers (that module's docstring explains why each module keeps its
# own small copy rather than sharing one).
# ---------------------------------------------------------------------------

_UNDEFINED_COLUMN_ERROR_CODES = {"42703", "PGRST204"}


def _is_undefined_column_error(error):
    details = error.args[0] if error.args else ""
    if isinstance(details, dict):
        code = details.get("code")
    else:
        code = str(details)
    return any(marker in (code or "") for marker in _UNDEFINED_COLUMN_ERROR_CODES)


def _is_unique_violation(error):
    details = error.args[0] if error.args else ""
    if isinstance(details, dict):
        code = details.get("code")
    else:
        code = str(details)
    return "23505" in (code or "")


def find_payment_by_idempotency_key(idempotency_key):
    """The payment row already inserted for this idempotency_key, or None.

    Used both by record_payment() below (to detect a race that lost to a
    concurrent identical submission) and directly by routes/payment.py's
    collect() (to short-circuit a slower duplicate - e.g. a back-button
    resubmit - before touching the membership's paid_amount/pending_amount
    a second time). Returns None (never raises) if idempotency_key doesn't
    exist as a column yet on this Supabase project (ADR-53) - the same
    silent-degrade behavior record_payment() itself falls back to.
    """

    if not idempotency_key:
        return None

    supabase = get_supabase_client()
    try:
        resp = (
            supabase.table("payments")
            .select("*")
            .eq("idempotency_key", idempotency_key)
            .limit(1)
            .execute()
        )
    except APIError as error:
        if _is_undefined_column_error(error):
            return None
        raise
    return resp.data[0] if resp.data else None


def get_unsynced_payment_count(admin_id):
    """How many of this admin's payments are missing their automatic
    Cashbook Income entry (TD-43, ADR-53) - insert_income_entry() failed
    even after its retry, and record_payment() flagged the payment row
    cashbook_synced=False instead of losing the gap silently. Used by
    routes/cashbook.py to show a reconciliation banner. Returns 0 (never
    raises) if cashbook_synced doesn't exist as a column yet on this
    Supabase project - same silent-degrade shape as the idempotency helpers
    above.
    """

    # get_payments_for_admin() already returns [] rather than raising on a
    # Supabase error (see its own docstring below), and simply omits
    # cashbook_synced from each row's dict if the column doesn't exist yet
    # on this project - .get(...) is False only once real data says so.
    payments = get_payments_for_admin(admin_id)
    return sum(1 for p in payments if p.get("cashbook_synced") is False)


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


def _flag_cashbook_unsynced(supabase, payment_id, admin_id, amount, category):
    """TD-43/ADR-53: insert_income_entry() below failed even after its own
    retry - the payment itself is kept (it's already valid, already
    validated money; rolling it back would erase a genuine payment over an
    unrelated ledger-mirror failure), but the automatic Cashbook entry it
    should have produced is missing. Logs the gap and best-effort flags the
    payment row (payments.cashbook_synced = FALSE) so routes/cashbook.py can
    surface a reconciliation banner, instead of losing the gap silently the
    way this same failure did before ADR-53. Never raises past
    record_payment() - nothing here may turn an already-successful payment
    into a failed request.
    """

    try:
        from flask import current_app
        current_app.logger.error(
            "Cashbook entry missing for payment_id=%s admin_id=%s amount=%s "
            "category=%s - insert_income_entry() failed after retry (TD-43)",
            payment_id, admin_id, amount, category
        )
    except Exception:
        pass

    try:
        supabase.table("payments").update(
            {"cashbook_synced": False}
        ).eq("payment_id", payment_id).execute()
    except Exception:
        # cashbook_synced may not exist yet on this project (ADR-53) - the
        # error log above is the only signal available until it's added.
        pass


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
    source,
    idempotency_key=None
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

    As of 2026-08-21 (TD-30, ADR-53), `idempotency_key` is optional - when
    given, a payment already recorded for that exact key is detected (both
    up front, and by catching the UNIQUE constraint if two identical
    requests race each other) and its receipt_number is returned as-is
    instead of inserting a second row - the caller's normal success path
    should run in that case, not its failure/rollback path, since nothing
    actually went wrong. If idempotency_key isn't a column yet on this
    Supabase project, this silently degrades to the pre-ADR-53 behavior
    (always inserts, no dedup) rather than failing payment collection
    outright.

    As of 2026-08-21 (TD-43, ADR-53), a failure in the automatic Cashbook
    entry below (even after its own retry) no longer disappears silently -
    see _flag_cashbook_unsynced() above.
    """

    supabase = get_supabase_client()

    if idempotency_key:
        existing = find_payment_by_idempotency_key(idempotency_key)
        if existing is not None:
            return existing["receipt_number"]

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

    # payments.payment_mode is a Category field (Payment Mode) per the
    # input-normalization policy (utils/normalization.py) - stored
    # UPPERCASE. The *original* payment_mode is still what's passed to
    # insert_income_entry() below: Cashbook's payment_method column/filter
    # dropdown (database/cashbook_categories.py's PAYMENT_METHODS, Title
    # Case) is a separate, out-of-scope concept that both manual and
    # automatic Cashbook entries must keep sharing one casing convention
    # for - normalizing only the payments-table copy avoids splitting that
    # column's values by capitalization instead of fixing it.
    payment_row = {
        "payment_id": payment_id,
        "membership_id": membership_id,
        "student_id": student_id,
        "receipt_number": receipt_number,
        "payment_mode": normalize_category(payment_mode),
        "amount_paid": amount,
        "payment_date": payment_date,
        "remarks": remarks,
        "idempotency_key": idempotency_key,
    }

    try:
        supabase.table("payments").insert(payment_row).execute()
    except APIError as error:
        if idempotency_key and _is_unique_violation(error):
            # Lost a race to an earlier, identical submission that already
            # inserted this exact idempotency_key (TD-30, ADR-53).
            existing = find_payment_by_idempotency_key(idempotency_key)
            if existing is not None:
                return existing["receipt_number"]
            raise
        if not _is_undefined_column_error(error):
            raise
        # idempotency_key isn't a column on this project yet (ADR-53) -
        # retry without it, same silent-degrade shape as
        # database/membership_queries.py's insert_membership().
        without_key = {k: v for k, v in payment_row.items() if k != "idempotency_key"}
        supabase.table("payments").insert(without_key).execute()

    cashbook_reference = insert_income_entry(
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

    if cashbook_reference is None:
        _flag_cashbook_unsynced(supabase, payment_id, admin_id, amount, category)

    return receipt_number
