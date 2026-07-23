"""
Reusable, admin-isolated data access for the Cashbook module.

Every query here is scoped to a single admin_id so the Cashbook behaves
like Students, Memberships, Payments and Enquiries: no admin can ever see
another admin's transactions.

Supabase's `cashbook` table is the source of truth for every read (ADR-22).
Reference-id and entry_id generation stay SQLite-based (unchanged from the
pre-migration logic - see _generate_reference_id below), and every write
still keeps the SQLite mirror in sync, following the same explicit-id
pattern ADR-18/19/20 established for enquiries/students/memberships:
Supabase's identity sequence trails SQLite's ever-climbing counter, so IDs
are always computed from SQLite's MAX(entry_id) and passed explicitly to
both stores rather than letting either auto-assign.

Two different write shapes coexist here, deliberately:

- insert_transaction() (manual entries, called directly from the in-scope
  routes/cashbook.py) writes Supabase first and rolls the Supabase insert
  back if the SQLite mirror-write fails - the same strict shape
  routes/enquiries.py/student.py/membership.py use for their own mirrors.
- insert_income_entry() (automatic entries, called from
  database/payment_queries.py's record_payment() - itself called from
  routes/membership.py and routes/payment.py, both out of scope for this
  migration slice) keeps its SQLite write as the primary, unchanged path,
  and best-effort mirrors the same row into Supabase afterward, swallowing
  any Supabase-side failure. Those two routes only catch sqlite3.Error
  around this call and manage their own SQLite commit/rollback; letting a
  Supabase hiccup raise past insert_income_entry() would surface as an
  unhandled error in a file this migration isn't touching. See
  docs/MIRROR_TRACKER.md and TD-38/TD-39 in docs/11_FUTURE_WORK.md.

`payment_id` is never sent to Supabase for automatic entries: Supabase's
`cashbook.payment_id` has a real FK to `payments`, and `payments` is still
SQLite-only (unmigrated) - sending a real payment_id there always fails
with a foreign-key violation (verified live, Postgres error 23503). The
SQLite mirror keeps the real payment_id, preserving today's
payment-reconciliation ability there; see TD-38.
"""

from datetime import date

from database.db import get_connection
from database.audit_queries import log_entry
from database.supabase_client import get_supabase_client


# ---------------------------------------------------------------------------
# Reference IDs
# ---------------------------------------------------------------------------

def _generate_reference_id(cursor, prefix):
    """Unique, human-readable reference number: PREFIX-YYYYMMDD-00001.

    Sequence is scoped to the prefix (PAY / EXP / INC) so the three entry
    origins each get their own counter instead of colliding on one. Stays
    SQLite-based (unchanged from before this module's Supabase migration)
    so numbering never depends on Supabase being reachable at write time -
    both insert paths below keep the SQLite mirror in lockstep with every
    write, so this count is always current.
    """

    cursor.execute(
        "SELECT COUNT(*) AS total FROM cashbook WHERE reference_id LIKE ?",
        (f"{prefix}-%",)
    )
    sequence = cursor.fetchone()["total"] + 1

    return f"{prefix}-{date.today().strftime('%Y%m%d')}-{sequence:05d}"


def _next_entry_id(cursor):
    """Next explicit entry_id, from SQLite's MAX (see module docstring)."""

    cursor.execute("SELECT IFNULL(MAX(entry_id), 0) AS m FROM cashbook")
    return cursor.fetchone()["m"] + 1


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
    Membership/Payment routes. Supabase is written first (source of
    truth); if the SQLite mirror-write fails, the Supabase row(s) are
    rolled back so the two stores never disagree about which manual
    entries exist.
    """

    supabase = get_supabase_client()
    conn = get_connection()
    cursor = conn.cursor()

    prefix = "EXP" if transaction_type == "Expense" else "INC"
    reference_id = _generate_reference_id(cursor, prefix)
    entry_id = _next_entry_id(cursor)

    details = f"Manual {transaction_type} of ₹{amount} added under '{category}' ({reference_id})"

    try:
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
    except Exception:
        conn.close()
        raise

    try:
        supabase.table("audit_log").insert({
            "admin_id": admin_id,
            "entry_id": entry_id,
            "action": "Created",
            "details": details,
        }).execute()
    except Exception:
        supabase.table("cashbook").delete().eq("entry_id", entry_id).execute()
        conn.close()
        raise

    cursor.execute("""
        INSERT INTO cashbook
        (
            entry_id,
            admin_id,
            type,
            category,
            person,
            description,
            amount,
            payment_method,
            entry_date,
            reference_id,
            source
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        entry_id,
        admin_id,
        transaction_type,
        category,
        person,
        description,
        amount,
        payment_method,
        entry_date,
        reference_id,
        "Cashbook Manual Entry"
    ))

    log_entry(cursor, admin_id, entry_id, "Created", details)

    conn.commit()
    conn.close()

    return reference_id


def insert_income_entry(
    conn,
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
    """Record an automatic Income entry using an already-open connection.

    Membership (create/renew) and Payment (collect) routes call this right
    after they insert into `payments`, using their own connection/cursor so
    the Cashbook entry commits as part of the very same transaction as the
    payment it represents - no second connection, no duplicated SQL. That
    SQLite write is unchanged from before this module's Supabase migration;
    see the module docstring for why the Supabase mirror-write below is
    best-effort rather than part of that same guarantee.

    `payment_id` is still recorded in the SQLite mirror (preserving today's
    reconciliation ability there) but never sent to Supabase - see the
    module docstring for why.
    """

    cursor = conn.cursor()
    reference_id = _generate_reference_id(cursor, reference_prefix)
    entry_id = _next_entry_id(cursor)

    cursor.execute("""
        INSERT INTO cashbook
        (entry_id, admin_id, type, category, person, description, amount,
         payment_method, entry_date, reference_id, source, payment_id)
        VALUES (?, ?, 'Income', ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        entry_id, admin_id, category, person, description, amount,
        payment_method, entry_date, reference_id, source, payment_id
    ))

    details = (
        f"Automatic Income of ₹{amount} recorded under '{category}' for "
        f"{person or 'N/A'} via {source} ({reference_id})"
    )
    log_entry(cursor, admin_id, entry_id, "Auto-Created", details)

    try:
        supabase = get_supabase_client()
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
        }).execute()
        supabase.table("audit_log").insert({
            "admin_id": admin_id,
            "entry_id": entry_id,
            "action": "Auto-Created",
            "details": details,
        }).execute()
    except Exception:
        # Best-effort mirror only - see module docstring for why this must
        # never block the caller's own SQLite transaction.
        pass

    return reference_id


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
    manual - callers use that to reject the request. Supabase (source of
    truth) is updated first, then the SQLite mirror.
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

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE cashbook
        SET category = ?, person = ?, description = ?, amount = ?,
            payment_method = ?, entry_date = ?
        WHERE entry_id = ? AND admin_id = ? AND source = 'Cashbook Manual Entry'
    """, (
        category, person, description, amount, payment_method, entry_date,
        entry_id, admin_id
    ))

    log_entry(cursor, admin_id, entry_id, "Updated", details)

    conn.commit()
    conn.close()

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
    the SQLite `memberships`/`students` mirrors - out of scope for this
    Cashbook/audit_log migration slice, unchanged.
    """

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT IFNULL(SUM(m.pending_amount), 0) AS total
        FROM memberships m
        JOIN students s ON m.student_id = s.student_id
        WHERE s.admin_id = ?
    """, (admin_id,))

    total = cursor.fetchone()["total"]
    conn.close()

    return total


def get_today_fee_collection(admin_id):
    """
    Fee revenue collected today specifically - same "Payments, not all of
    Cashbook" scope as get_total_fee_revenue() below, just narrowed to
    today's date. Distinct from get_today_income() (all of today's
    Cashbook income, including non-fee manual entries) for the same reason
    get_total_fee_revenue() is distinct from get_total_income() - see
    ADR-11 in docs/DECISIONS.md. Reads SQLite `payments`/`students` -
    both out of scope for this migration slice, unchanged.
    """

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT IFNULL(SUM(p.amount_paid), 0) AS total
        FROM payments p
        JOIN students s ON p.student_id = s.student_id
        WHERE s.admin_id = ? AND p.payment_date = DATE('now')
    """, (admin_id,))

    total = cursor.fetchone()["total"]
    conn.close()

    return total


def get_total_fee_revenue(admin_id):
    """
    Total fee revenue actually collected from students (Admission/Membership
    Fee/Renewal payments), summed straight from Payments - the source of
    truth for "how much has this library billed and collected", same as
    get_pending_fees() above is the source of truth for what's still owed.

    Deliberately narrower than get_total_income(): Cashbook's Income total
    also includes non-fee categories (Donation, Library Fine, Book Sale,
    Other Income), which aren't billable/collectible against a membership
    and must not be blended into fee-collection metrics. Reads SQLite
    `payments`/`students` - both out of scope for this migration slice,
    unchanged.
    """

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT IFNULL(SUM(p.amount_paid), 0) AS total
        FROM payments p
        JOIN students s ON p.student_id = s.student_id
        WHERE s.admin_id = ?
    """, (admin_id,))

    total = cursor.fetchone()["total"]
    conn.close()

    return total


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
