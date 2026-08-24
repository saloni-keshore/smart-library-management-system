"""
Reusable, admin-isolated data access for the Cashbook module.

Every query here is scoped to a single admin_id so the Cashbook behaves
like Students, Memberships, Payments and Enquiries: no admin can ever see
another admin's transactions.

As of 2026-07-24 (ADR-27, Phase 10 - the second mirror-write fully
removed), Supabase's `cashbook` table is this module's only store, for
both reads and writes - there is no SQLite mirror left. Reference-id and
entry_id generation (`_generate_reference_id`/`_next_entry_id`) query
Supabase's own `MAX`/`COUNT` now, the same explicit-id pattern
ADR-18/19/20/22 established (IDs computed explicitly rather than left to
an auto-increment sequence), just against Supabase instead of SQLite.

Two different write shapes coexist here, deliberately:

- insert_transaction() (manual entries, called directly from the in-scope
  routes/cashbook.py) writes the `cashbook` row first and rolls it back if
  the matching `audit_log` insert then fails - the same strict shape
  routes/enquiries.py/student.py/membership.py use for their own mirrors,
  just entirely within Supabase now instead of Supabase-then-SQLite.
- insert_income_entry() (automatic entries, called from
  database/payment_queries.py's record_payment() - itself called from
  routes/membership.py and routes/payment.py, both out of scope for this
  migration slice) wraps id generation and both inserts in one bare
  except, swallowing any failure - the same best-effort contract this
  function has had since ADR-22, kept deliberately even after those two
  routes' own SQLite writes were removed (ADR-29): this function's own
  caller chain is still out of scope, so widening its bare except into a
  specific caught type would be new logic, not the mechanical one-line
  except-clause change ADR-28/29 made at the route level. As of ADR-27,
  there is no SQLite fallback left: a Supabase outage during this call
  means the automatic entry (and its audit-log row) for that one payment
  is not recorded anywhere at all, not just left stale - see
  docs/MIRROR_TRACKER.md and TD-43 in docs/11_FUTURE_WORK.md.

As of 2026-07-24 (ADR-25), `payment_id` **is** sent to Supabase for
automatic entries - `payments` itself migrated to Supabase (best-effort
mirror, same shape as this function), closing the FK violation that
previously made this impossible (TD-38, `Resolved`). If that payments
mirror-write happened to fail moments earlier, this insert falls back to
the same best-effort miss `insert_income_entry()` already risks - see
TD-41.
"""

from datetime import date

from postgrest.exceptions import APIError

from database.supabase_client import get_supabase_client
from database.membership_queries import get_memberships_for_admin, get_admin_students


# ---------------------------------------------------------------------------
# Reference IDs
# ---------------------------------------------------------------------------

def _generate_reference_id(supabase, prefix):
    """Unique, human-readable reference number: PREFIX-YYYYMMDD-00001.

    Sequence is scoped to the prefix (PAY / EXP / INC) so the three entry
    origins each get their own counter instead of colliding on one. As of
    2026-07-24 (ADR-27, Phase 10 - cashbook's SQLite mirror-write removed),
    counts against Supabase `cashbook` - the source of truth for this table
    since ADR-22, and the only copy that still receives new rows.
    """

    resp = (
        supabase.table("cashbook")
        .select("*", count="exact", head=True)
        .like("reference_id", f"{prefix}-%")
        .execute()
    )
    sequence = (resp.count or 0) + 1

    return f"{prefix}-{date.today().strftime('%Y%m%d')}-{sequence:05d}"


def _next_entry_id(supabase):
    """Next explicit entry_id, from Supabase `cashbook`'s own MAX (see
    module docstring) - as of ADR-27, Supabase replaces SQLite as the MAX
    source now that this table's SQLite mirror-write is gone.
    """

    resp = (
        supabase.table("cashbook")
        .select("entry_id")
        .order("entry_id", desc=True)
        .limit(1)
        .execute()
    )
    return (resp.data[0]["entry_id"] + 1) if resp.data else 1


def _admin_full_name(supabase, admin_id):
    resp = (
        supabase.table("admins")
        .select("full_name")
        .eq("admin_id", admin_id)
        .execute()
    )
    return resp.data[0]["full_name"] if resp.data else None


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------

def get_recent_transactions(admin_id, limit=10):
    """Latest transactions for this admin, newest first."""

    supabase = get_supabase_client()

    resp = (
        supabase.table("cashbook")
        .select("*")
        .eq("admin_id", admin_id)
        .order("entry_date", desc=True)
        .order("entry_id", desc=True)
        .limit(limit)
        .execute()
    )

    return resp.data


def insert_transaction(
    admin_id,
    transaction_type,
    category,
    person,
    description,
    amount,
    payment_method,
    entry_date
):
    """Insert a manual Cashbook entry (Expense or Misc Income) owned by admin.

    Manual entries are the only ones an admin creates directly - automatic
    Income entries come from insert_income_entry() below, triggered by
    Membership/Payment routes. As of 2026-07-24 (ADR-27), Supabase is the
    only store: the `cashbook` row is written first, and rolled back if the
    matching `audit_log` row then fails, so the two Supabase tables never
    disagree about which manual entries exist.
    """

    supabase = get_supabase_client()

    prefix = "EXP" if transaction_type == "Expense" else "INC"
    reference_id = _generate_reference_id(supabase, prefix)
    entry_id = _next_entry_id(supabase)

    details = f"Manual {transaction_type} of ₹{amount} added under '{category}' ({reference_id})"

    supabase.table("cashbook").insert({
        "entry_id": entry_id,
        "admin_id": admin_id,
        "type": transaction_type,
        "category": category,
        "person": person,
        "description": description,
        "amount": amount,
        "payment_method": payment_method,
        "entry_date": entry_date,
        "reference_id": reference_id,
        "source": "Cashbook Manual Entry",
    }).execute()

    try:
        supabase.table("audit_log").insert({
            "admin_id": admin_id,
            "entry_id": entry_id,
            "action": "Created",
            "details": details,
        }).execute()
    except Exception:
        supabase.table("cashbook").delete().eq("entry_id", entry_id).execute()
        raise

    return reference_id


def insert_income_entry(
    admin_id,
    category,
    person,
    description,
    amount,
    payment_method,
    entry_date,
    source,
    reference_prefix="PAY",
    payment_id=None
):
    """Record an automatic Income entry for a just-recorded payment.

    Membership (create/renew) and Payment (collect) routes trigger this via
    database/payment_queries.py's record_payment(), right after that
    function's own `payments` insert. As of 2026-07-24 (ADR-27, Phase 10 -
    cashbook's SQLite mirror-write removed), this writes only Supabase, and
    the whole thing (id generation plus both inserts) is best-effort,
    wrapped in one bare except - the same fire-and-forget contract this
    function has had since ADR-22, preserved deliberately even after those
    two routes' own SQLite writes were removed (ADR-29): this function's
    caller chain (record_payment(), itself called from those routes) is
    still out of scope for turning this into a strict, propagating write.
    Before ADR-27, a Supabase outage here only left
    the Supabase mirror stale (TD-39/TD-41) - the SQLite row still existed.
    As of ADR-27, there is no SQLite fallback left, so an outage now means
    the automatic Income entry (and its audit-log row) for that one payment
    is not recorded anywhere at all - see TD-43 in docs/11_FUTURE_WORK.md.

    As of 2026-07-24 (ADR-25, closing TD-38), `payment_id` is sent to
    Supabase, now that `payments` itself has a Supabase row (also
    best-effort, via record_payment()) - Supabase's `cashbook.payment_id`
    FK can resolve in the common case.

    Returns the generated reference_id, or None if the write didn't
    succeed (nothing to return - there is no longer a guaranteed copy).

    As of 2026-08-21 (TD-43, ADR-53), this makes one bounded retry (two
    attempts total) before giving up - most failures at this call site are
    a transient blip (a brief Supabase hiccup), and retrying once here,
    inline, is simpler than making every caller (routes/membership.py's
    create()/renew(), routes/payment.py's collect(), all via
    record_payment()) handle that themselves. A second attempt regenerates
    reference_id/entry_id fresh rather than reusing the first attempt's
    values, since those are derived from a live count/max query, not
    pre-allocated - reusing stale values across attempts could itself
    collide. record_payment() (database/payment_queries.py) is responsible
    for what happens if both attempts fail - see its own
    _flag_cashbook_unsynced().
    """

    supabase = get_supabase_client()

    for _attempt in range(2):
        try:
            reference_id = _generate_reference_id(supabase, reference_prefix)
            entry_id = _next_entry_id(supabase)

            details = (
                f"Automatic Income of ₹{amount} recorded under '{category}' for "
                f"{person or 'N/A'} via {source} ({reference_id})"
            )

            supabase.table("cashbook").insert({
                "entry_id": entry_id,
                "admin_id": admin_id,
                "type": "Income",
                "category": category,
                "person": person,
                "description": description,
                "amount": amount,
                "payment_method": payment_method,
                "entry_date": entry_date,
                "reference_id": reference_id,
                "source": source,
                "payment_id": payment_id,
            }).execute()
            supabase.table("audit_log").insert({
                "admin_id": admin_id,
                "entry_id": entry_id,
                "action": "Auto-Created",
                "details": details,
            }).execute()

            return reference_id
        except Exception:
            # Best-effort only - see docstring above for why this must
            # never raise past the caller's own transaction
            # (routes/membership.py / routes/payment.py, both out of scope
            # for this migration slice).
            continue

    return None


def get_transaction_by_id(admin_id, entry_id):
    """Single admin-isolated Cashbook entry, used by the View/Edit modals."""

    supabase = get_supabase_client()

    resp = (
        supabase.table("cashbook")
        .select("*")
        .eq("entry_id", entry_id)
        .eq("admin_id", admin_id)
        .execute()
    )

    if not resp.data:
        return None

    row = dict(resp.data[0])
    row["created_by"] = _admin_full_name(supabase, admin_id)
    return row


def update_manual_transaction(
    admin_id,
    entry_id,
    category,
    person,
    description,
    amount,
    payment_method,
    entry_date
):
    """Update a manual Cashbook entry.

    Scoped to source = 'Cashbook Manual Entry' so automatic ledger entries
    (which mirror a Payments row) can never be silently edited out of sync.
    Returns False if the entry doesn't exist, isn't this admin's, or isn't
    manual - callers use that to reject the request. As of 2026-07-24
    (ADR-27), Supabase is the only store updated.
    """

    supabase = get_supabase_client()

    existing = (
        supabase.table("cashbook")
        .select("entry_id")
        .eq("entry_id", entry_id)
        .eq("admin_id", admin_id)
        .eq("source", "Cashbook Manual Entry")
        .execute()
    )
    if not existing.data:
        return False

    details = f"Transaction edited - now ₹{amount} under '{category}'"

    supabase.table("cashbook").update({
        "category": category,
        "person": person,
        "description": description,
        "amount": amount,
        "payment_method": payment_method,
        "entry_date": entry_date,
    }).eq("entry_id", entry_id).eq("admin_id", admin_id).execute()

    supabase.table("audit_log").insert({
        "admin_id": admin_id,
        "entry_id": entry_id,
        "action": "Updated",
        "details": details,
    }).execute()

    return True


# ---------------------------------------------------------------------------
# KPI cards
# ---------------------------------------------------------------------------

def _fetch_cashbook_rows(admin_id, transaction_type=None):
    supabase = get_supabase_client()
    query = supabase.table("cashbook").select("*").eq("admin_id", admin_id)

    if transaction_type:
        query = query.eq("type", transaction_type)

    return query.execute().data


def _get_total_by_type(admin_id, transaction_type):
    rows = _fetch_cashbook_rows(admin_id, transaction_type)
    return sum(row["amount"] or 0 for row in rows)


def get_total_income(admin_id):
    return _get_total_by_type(admin_id, "Income")


def get_total_expense(admin_id):
    return _get_total_by_type(admin_id, "Expense")


def _get_today_total_by_type(admin_id, transaction_type):
    today = date.today().isoformat()
    rows = _fetch_cashbook_rows(admin_id, transaction_type)
    return sum(row["amount"] or 0 for row in rows if row["entry_date"] == today)


def get_today_income(admin_id):
    return _get_today_total_by_type(admin_id, "Income")


def get_today_expense(admin_id):
    return _get_today_total_by_type(admin_id, "Expense")


def get_pending_fees(admin_id):
    """
    Pending Fees comes from the Payments/Memberships module (the source of
    truth for what students still owe), not from Cashbook expenses. Reads
    Supabase `students`/`memberships` (ADR-23) via
    database.membership_queries.get_memberships_for_admin() - the same
    shared join every other analytics consumer of that pair now uses.
    """

    memberships = get_memberships_for_admin(admin_id)
    return sum(m["pending_amount"] or 0 for m in memberships)


def _fetch_payments_for_admin(admin_id):
    """This admin's payments - the Python-side equivalent of `payments p
    JOIN students s ON p.student_id = s.student_id WHERE s.admin_id = ?`,
    since PostgREST has no cross-table JOIN in the client this codebase
    uses (same shape as get_memberships_for_admin()). Not imported from
    database.payment_queries to avoid a circular import (that module
    already imports this one for insert_income_entry()) - kept as a small,
    local duplicate instead.
    """

    students = get_admin_students(admin_id)
    if not students:
        return []
    student_ids = [s["student_id"] for s in students]

    supabase = get_supabase_client()
    try:
        response = (
            supabase.table("payments")
            .select("*")
            .in_("student_id", student_ids)
            .execute()
        )
        return response.data
    except APIError:
        return []


def get_today_fee_collection(admin_id):
    """
    Fee revenue collected today specifically - same "Payments, not all of
    Cashbook" scope as get_total_fee_revenue() below, just narrowed to
    today's date. Distinct from get_today_income() (all of today's
    Cashbook income, including non-fee manual entries) for the same reason
    get_total_fee_revenue() is distinct from get_total_income() - see
    ADR-11 in docs/DECISIONS.md. Reads Supabase `students`/`payments`
    (ADR-25).
    """

    today = date.today().isoformat()
    payments = _fetch_payments_for_admin(admin_id)
    return sum(p["amount_paid"] or 0 for p in payments if p["payment_date"] == today)


def get_total_fee_revenue(admin_id):
    """
    Total fee revenue actually collected from students (Admission/Membership
    Fee/Renewal payments), summed straight from Payments - the source of
    truth for "how much has this library billed and collected", same as
    get_pending_fees() above is the source of truth for what's still owed.

    Deliberately narrower than get_total_income(): Cashbook's Income total
    also includes non-fee categories (Donation, Library Fine, Book Sale,
    Other Income), which aren't billable/collectible against a membership
    and must not be blended into fee-collection metrics. Reads Supabase
    `students`/`payments` (ADR-25).
    """

    payments = _fetch_payments_for_admin(admin_id)
    return sum(p["amount_paid"] or 0 for p in payments)


# ---------------------------------------------------------------------------
# Analytics (reusable data for future Chart.js dashboards / reports / exports)
# ---------------------------------------------------------------------------

def _monthly_totals_by_type(admin_id, transaction_type):
    rows = _fetch_cashbook_rows(admin_id, transaction_type)

    totals = {}
    for row in rows:
        if not row["entry_date"]:
            continue
        month = row["entry_date"][:7]
        totals[month] = totals.get(month, 0) + (row["amount"] or 0)

    return dict(sorted(totals.items()))


def get_monthly_income(admin_id):
    return _monthly_totals_by_type(admin_id, "Income")


def get_monthly_expense(admin_id):
    return _monthly_totals_by_type(admin_id, "Expense")


def get_monthly_profit(admin_id):
    """Net profit per month = income - expense for that month."""

    income = get_monthly_income(admin_id)
    expense = get_monthly_expense(admin_id)

    months = sorted(set(income) | set(expense))

    return {
        month: income.get(month, 0) - expense.get(month, 0)
        for month in months
    }


def _category_totals_by_type(admin_id, transaction_type):
    rows = _fetch_cashbook_rows(admin_id, transaction_type)

    totals = {}
    for row in rows:
        totals[row["category"]] = totals.get(row["category"], 0) + (row["amount"] or 0)

    return dict(sorted(totals.items(), key=lambda kv: kv[1], reverse=True))


def get_income_category_totals(admin_id):
    return _category_totals_by_type(admin_id, "Income")


def get_expense_category_totals(admin_id):
    return _category_totals_by_type(admin_id, "Expense")


def get_payment_method_distribution(admin_id):
    rows = _fetch_cashbook_rows(admin_id)

    totals = {}
    for row in rows:
        totals[row["payment_method"]] = totals.get(row["payment_method"], 0) + (row["amount"] or 0)

    return dict(sorted(totals.items(), key=lambda kv: kv[1], reverse=True))


def get_cash_balance(admin_id):
    """Physical cash on hand: Cash-method Income minus Cash-method Expense.

    Distinct from Net Profit (which is all payment methods combined) - this
    answers "how much cash is actually in the drawer".
    """

    rows = _fetch_cashbook_rows(admin_id)

    balance = 0
    for row in rows:
        if row["payment_method"] != "Cash":
            continue
        if row["type"] == "Income":
            balance += row["amount"] or 0
        elif row["type"] == "Expense":
            balance -= row["amount"] or 0

    return balance


def get_todays_transaction_count(admin_id):
    today = date.today().isoformat()
    rows = _fetch_cashbook_rows(admin_id)
    return sum(1 for row in rows if row["entry_date"] == today)


# ---------------------------------------------------------------------------
# Filterable, paginated ledger listing (Cashbook "Recent Transactions" table)
# ---------------------------------------------------------------------------

def get_cashbook_ledger(
    admin_id,
    search=None,
    date_from=None,
    date_to=None,
    transaction_type=None,
    category=None,
    payment_method=None,
    source=None,
    page=1,
    per_page=10
):
    """Filtered, paginated Cashbook entries with the admin's name attached.

    Every filter is optional and combinable. Returns a dict with the page
    of rows plus pagination metadata for the template to render controls.

    Structured filters (date range, type, category, payment method, the
    "Manual" half of source) run server-side via Supabase's query builder.
    Free-text search and the "Automatic" half of source (which needs an OR
    against NULL - PostgREST can express this, but not worth a raw filter
    string for user-controlled input) are applied in Python, along with
    sorting and pagination - the same "fetch this admin's rows, finish the
    shaping in Python" shape ADR-18/19/20 already use where Supabase's
    query surface doesn't cover something SQL used to do in one query.
    """

    supabase = get_supabase_client()

    query = supabase.table("cashbook").select("*").eq("admin_id", admin_id)

    if date_from:
        query = query.gte("entry_date", date_from)
    if date_to:
        query = query.lte("entry_date", date_to)
    if transaction_type:
        query = query.eq("type", transaction_type)
    if category:
        query = query.eq("category", category)
    if payment_method:
        query = query.eq("payment_method", payment_method)
    if source == "Manual":
        query = query.eq("source", "Cashbook Manual Entry")

    rows = query.execute().data

    if source == "Automatic":
        # NULL check matters: pre-migration rows (created before the
        # `source` column existed) have no source, and must still count as
        # "Automatic", not silently vanish from both filters.
        rows = [r for r in rows if r.get("source") != "Cashbook Manual Entry"]

    if search:
        needle = search.lower()

        def _matches(row):
            haystacks = (
                row.get("category"), row.get("person"),
                row.get("description"), row.get("reference_id")
            )
            return any(h and needle in h.lower() for h in haystacks)

        rows = [r for r in rows if _matches(r)]

    rows.sort(key=lambda r: (r.get("entry_date") or "", r.get("entry_id") or 0), reverse=True)

    created_by = _admin_full_name(supabase, admin_id)
    for row in rows:
        row["created_by"] = created_by

    total = len(rows)
    per_page = max(1, per_page)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    offset = (page - 1) * per_page

    return {
        "rows": rows[offset:offset + per_page],
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
    }
