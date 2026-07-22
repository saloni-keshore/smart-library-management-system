"""
Reusable, admin-isolated data access for the Cashbook module.

Every query here is scoped to a single admin_id so the Cashbook behaves
like Students, Memberships, Payments and Enquiries: no admin can ever see
another admin's transactions.
"""

from datetime import date

from database.db import get_connection
from database.audit_queries import log_entry


# ---------------------------------------------------------------------------
# Reference IDs
# ---------------------------------------------------------------------------

def _generate_reference_id(cursor, prefix):
    """Unique, human-readable reference number: PREFIX-YYYYMMDD-00001.

    Sequence is scoped to the prefix (PAY / EXP / INC) so the three entry
    origins each get their own counter instead of colliding on one.
    """

    cursor.execute(
        "SELECT COUNT(*) AS total FROM cashbook WHERE reference_id LIKE ?",
        (f"{prefix}-%",)
    )
    sequence = cursor.fetchone()["total"] + 1

    return f"{prefix}-{date.today().strftime('%Y%m%d')}-{sequence:05d}"


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------

def get_recent_transactions(admin_id, limit=10):
    """Latest transactions for this admin, newest first."""

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM cashbook
        WHERE admin_id = ?
        ORDER BY entry_date DESC, entry_id DESC
        LIMIT ?
    """, (admin_id, limit))

    rows = cursor.fetchall()
    conn.close()

    return rows


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
    Membership/Payment routes.
    """

    conn = get_connection()
    cursor = conn.cursor()

    prefix = "EXP" if transaction_type == "Expense" else "INC"
    reference_id = _generate_reference_id(cursor, prefix)

    cursor.execute("""
        INSERT INTO cashbook
        (
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
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
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

    log_entry(
        cursor,
        admin_id,
        cursor.lastrowid,
        "Created",
        f"Manual {transaction_type} of ₹{amount} added under '{category}' ({reference_id})"
    )

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
    payment it represents - no second connection, no duplicated SQL.

    `payment_id`, when given, links this ledger row back to the exact
    `payments` row that produced it (the FK the `cashbook` table already
    declares) - without it, reconciling "did this payment produce a ledger
    entry" only worked by fuzzy person/amount/date matching, which is
    ambiguous whenever two payments share all three.
    """

    cursor = conn.cursor()
    reference_id = _generate_reference_id(cursor, reference_prefix)

    cursor.execute("""
        INSERT INTO cashbook
        (admin_id, type, category, person, description, amount,
         payment_method, entry_date, reference_id, source, payment_id)
        VALUES (?, 'Income', ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        admin_id, category, person, description, amount,
        payment_method, entry_date, reference_id, source, payment_id
    ))

    log_entry(
        cursor,
        admin_id,
        cursor.lastrowid,
        "Auto-Created",
        f"Automatic Income of ₹{amount} recorded under '{category}' for "
        f"{person or 'N/A'} via {source} ({reference_id})"
    )

    return reference_id


def get_transaction_by_id(admin_id, entry_id):
    """Single admin-isolated Cashbook entry, used by the View/Edit modals."""

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT c.*, a.full_name AS created_by
        FROM cashbook c
        LEFT JOIN admins a ON a.admin_id = c.admin_id
        WHERE c.entry_id = ? AND c.admin_id = ?
    """, (entry_id, admin_id))

    row = cursor.fetchone()
    conn.close()

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
    manual - callers use that to reject the request.
    """

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

    updated = cursor.rowcount > 0

    if updated:
        log_entry(
            cursor,
            admin_id,
            entry_id,
            "Updated",
            f"Transaction edited - now ₹{amount} under '{category}'"
        )

    conn.commit()
    conn.close()

    return updated


# ---------------------------------------------------------------------------
# KPI cards
# ---------------------------------------------------------------------------

def _get_total_by_type(admin_id, transaction_type):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT IFNULL(SUM(amount), 0) AS total
        FROM cashbook
        WHERE admin_id = ? AND type = ?
    """, (admin_id, transaction_type))

    total = cursor.fetchone()["total"]
    conn.close()

    return total


def get_total_income(admin_id):
    return _get_total_by_type(admin_id, "Income")


def get_total_expense(admin_id):
    return _get_total_by_type(admin_id, "Expense")


def _get_today_total_by_type(admin_id, transaction_type):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT IFNULL(SUM(amount), 0) AS total
        FROM cashbook
        WHERE admin_id = ? AND type = ? AND entry_date = DATE('now')
    """, (admin_id, transaction_type))

    total = cursor.fetchone()["total"]
    conn.close()

    return total


def get_today_income(admin_id):
    return _get_today_total_by_type(admin_id, "Income")


def get_today_expense(admin_id):
    return _get_today_total_by_type(admin_id, "Expense")


def get_pending_fees(admin_id):
    """
    Pending Fees comes from the Payments/Memberships module (the source of
    truth for what students still owe), not from Cashbook expenses.
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
    ADR-11 in docs/DECISIONS.md.
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
    and must not be blended into fee-collection metrics.
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

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            strftime('%Y-%m', entry_date) AS month,
            IFNULL(SUM(amount), 0) AS total
        FROM cashbook
        WHERE admin_id = ? AND type = ?
        GROUP BY month
        ORDER BY month
    """, (admin_id, transaction_type))

    rows = cursor.fetchall()
    conn.close()

    return {row["month"]: row["total"] for row in rows}


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

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT category, IFNULL(SUM(amount), 0) AS total
        FROM cashbook
        WHERE admin_id = ? AND type = ?
        GROUP BY category
        ORDER BY total DESC
    """, (admin_id, transaction_type))

    rows = cursor.fetchall()
    conn.close()

    return {row["category"]: row["total"] for row in rows}


def get_income_category_totals(admin_id):
    return _category_totals_by_type(admin_id, "Income")


def get_expense_category_totals(admin_id):
    return _category_totals_by_type(admin_id, "Expense")


def get_payment_method_distribution(admin_id):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT payment_method, IFNULL(SUM(amount), 0) AS total
        FROM cashbook
        WHERE admin_id = ?
        GROUP BY payment_method
        ORDER BY total DESC
    """, (admin_id,))

    rows = cursor.fetchall()
    conn.close()

    return {row["payment_method"]: row["total"] for row in rows}


def get_cash_balance(admin_id):
    """Physical cash on hand: Cash-method Income minus Cash-method Expense.

    Distinct from Net Profit (which is all payment methods combined) - this
    answers "how much cash is actually in the drawer".
    """

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            IFNULL(SUM(CASE WHEN type = 'Income' THEN amount ELSE 0 END), 0) -
            IFNULL(SUM(CASE WHEN type = 'Expense' THEN amount ELSE 0 END), 0)
            AS balance
        FROM cashbook
        WHERE admin_id = ? AND payment_method = 'Cash'
    """, (admin_id,))

    balance = cursor.fetchone()["balance"]
    conn.close()

    return balance


def get_todays_transaction_count(admin_id):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM cashbook
        WHERE admin_id = ? AND entry_date = DATE('now')
    """, (admin_id,))

    total = cursor.fetchone()["total"]
    conn.close()

    return total


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
    """

    conditions = ["c.admin_id = ?"]
    params = [admin_id]

    if search:
        like = f"%{search}%"
        conditions.append("""(
            c.category LIKE ? OR c.person LIKE ? OR
            c.description LIKE ? OR c.reference_id LIKE ?
        )""")
        params.extend([like, like, like, like])

    if date_from:
        conditions.append("c.entry_date >= ?")
        params.append(date_from)

    if date_to:
        conditions.append("c.entry_date <= ?")
        params.append(date_to)

    if transaction_type:
        conditions.append("c.type = ?")
        params.append(transaction_type)

    if category:
        conditions.append("c.category = ?")
        params.append(category)

    if payment_method:
        conditions.append("c.payment_method = ?")
        params.append(payment_method)

    if source == "Manual":
        conditions.append("c.source = 'Cashbook Manual Entry'")
    elif source == "Automatic":
        # IS NULL check matters: pre-migration rows (created before the
        # `source` column existed) are NULL, and `NULL != 'x'` is NULL (not
        # true) in SQL, so without it these legacy automatic entries would
        # silently vanish from both the "Automatic" and "Manual" filters.
        conditions.append("(c.source != 'Cashbook Manual Entry' OR c.source IS NULL)")

    where_clause = " AND ".join(conditions)

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        f"SELECT COUNT(*) AS total FROM cashbook c WHERE {where_clause}",
        params
    )
    total = cursor.fetchone()["total"]

    per_page = max(1, per_page)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    offset = (page - 1) * per_page

    cursor.execute(f"""
        SELECT c.*, a.full_name AS created_by
        FROM cashbook c
        LEFT JOIN admins a ON a.admin_id = c.admin_id
        WHERE {where_clause}
        ORDER BY c.entry_date DESC, c.entry_id DESC
        LIMIT ? OFFSET ?
    """, params + [per_page, offset])

    rows = cursor.fetchall()
    conn.close()

    return {
        "rows": rows,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": total_pages,
    }
