"""
Data access for the Business Intelligence module.

This module does not duplicate Cashbook's SQL. It imports the existing,
admin-isolated aggregate functions from cashbook_queries (monthly income,
monthly expense, category totals, pending fees, recent transactions) and
adds only the analysis that doesn't exist anywhere yet: growth math, health
classification, the composite health score, and membership-side counts.

Every new query here still follows the same admin_id-scoped, dict/list
returning convention used across cashbook_queries.py and the rest of the
database layer.
"""

from datetime import date

from database.db import get_connection
from database.cashbook_queries import (
    get_monthly_income,
    get_monthly_expense,
    get_pending_fees,
    get_total_fee_revenue,
    get_income_category_totals,
    get_expense_category_totals,
    get_recent_transactions,
)


# ---------------------------------------------------------------------------
# Shared month helpers
# ---------------------------------------------------------------------------

def last_n_months(n=6):
    """Last n month keys ('YYYY-MM'), oldest first, ending at the current month."""

    today = date.today()
    year, month = today.year, today.month

    months = []
    for i in range(n - 1, -1, -1):
        m = month - i
        y = year
        while m <= 0:
            m += 12
            y -= 1
        months.append(f"{y:04d}-{m:02d}")

    return months


# ---------------------------------------------------------------------------
# Membership-side counts (no equivalent exists yet in any queries module)
# ---------------------------------------------------------------------------

def get_monthly_new_memberships(admin_id):
    """New memberships per month, keyed by joining month."""

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            strftime('%Y-%m', m.joining_date) AS month,
            COUNT(*) AS total
        FROM memberships m
        JOIN students s ON m.student_id = s.student_id
        WHERE s.admin_id = ?
        GROUP BY month
        ORDER BY month
    """, (admin_id,))

    rows = cursor.fetchall()
    conn.close()

    return {row["month"]: row["total"] for row in rows}


def get_membership_retention(admin_id):
    """Total vs currently-active memberships, used as a retention signal."""

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            COUNT(*) AS total,
            SUM(
                CASE WHEN m.membership_status = 'Active'
                     AND m.end_date >= DATE('now')
                THEN 1 ELSE 0 END
            ) AS active
        FROM memberships m
        JOIN students s ON m.student_id = s.student_id
        WHERE s.admin_id = ?
    """, (admin_id,))

    row = cursor.fetchone()
    conn.close()

    return {"total": row["total"] or 0, "active": row["active"] or 0}


def get_upcoming_expiries(admin_id, days=7):
    """Count of active memberships expiring within the next `days` days."""

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM memberships m
        JOIN students s ON m.student_id = s.student_id
        WHERE s.admin_id = ?
        AND m.membership_status = 'Active'
        AND m.end_date BETWEEN DATE('now') AND DATE('now', ?)
    """, (admin_id, f"+{days} days"))

    total = cursor.fetchone()["total"]
    conn.close()

    return total


# ---------------------------------------------------------------------------
# Revenue growth + health classification
# ---------------------------------------------------------------------------

def get_revenue_growth(admin_id):
    """Current vs previous month revenue and the growth % between them."""

    income = get_monthly_income(admin_id)
    previous_month, current_month = last_n_months(2)

    current = income.get(current_month, 0)
    previous = income.get(previous_month, 0)

    if previous > 0:
        growth_pct = round((current - previous) / previous * 100, 1)
    elif current > 0:
        growth_pct = 100.0
    else:
        growth_pct = 0.0

    return {
        "current_month": current,
        "previous_month": previous,
        "growth_pct": growth_pct,
    }


def classify_revenue_health(growth_pct):
    """Healthy: growing 5%+. Warning: roughly flat. Critical: shrinking 5%+."""

    if growth_pct >= 5:
        return "Healthy"
    if growth_pct <= -5:
        return "Critical"
    return "Warning"


def classify_expense_health(admin_id):
    """Classifies this month's expense-to-income ratio.

    Healthy: spending under half of revenue. Warning: 50-75%.
    Critical: over 75%, or any expense with zero revenue to cover it.
    """

    income = get_monthly_income(admin_id)
    expense = get_monthly_expense(admin_id)
    current_month = last_n_months(1)[0]

    current_income = income.get(current_month, 0)
    current_expense = expense.get(current_month, 0)

    if current_income > 0:
        ratio = current_expense / current_income
    else:
        ratio = 1.0 if current_expense > 0 else 0.0

    if ratio <= 0.5:
        status = "Healthy"
    elif ratio <= 0.75:
        status = "Warning"
    else:
        status = "Critical"

    return {
        "ratio_pct": round(ratio * 100, 1),
        "status": status,
        "current_income": current_income,
        "current_expense": current_expense,
    }


# ---------------------------------------------------------------------------
# Business Health Score
#
# Weighted blend of four signals, each normalized to 0-1:
#   30% revenue growth      (-20% growth -> 0, +20% growth -> 1)
#   30% expense discipline  (0% of revenue spent -> 1, 100%+ -> 0)
#   20% fee collection      (share of billed fee revenue not left pending)
#   20% membership renewal  (active memberships / total memberships)
# A library with no data yet gets neutral 0.5 on components it has no
# signal for, rather than being punished with a 0.
# ---------------------------------------------------------------------------

def get_business_health_score(admin_id):

    growth = get_revenue_growth(admin_id)
    expense = classify_expense_health(admin_id)
    retention = get_membership_retention(admin_id)
    pending = get_pending_fees(admin_id)
    total_fee_revenue = get_total_fee_revenue(admin_id)

    growth_component = max(0.0, min(1.0, (growth["growth_pct"] + 20) / 40))
    expense_component = max(0.0, min(1.0, 1 - (expense["ratio_pct"] / 100)))

    # Billable = fees actually collected + fees still pending. Deliberately
    # uses fee revenue (Payments/Memberships), not get_total_income()'s
    # all-Cashbook total - non-fee income (donations, library fines, book
    # sales) isn't billed against a membership, so blending it in would
    # dilute the pending share and overstate collection health.
    billable = pending + total_fee_revenue
    collection_component = (
        max(0.0, min(1.0, 1 - pending / billable)) if billable > 0 else 0.5
    )

    renewal_component = (
        retention["active"] / retention["total"] if retention["total"] > 0 else 0.5
    )

    score = round(100 * (
        0.30 * growth_component +
        0.30 * expense_component +
        0.20 * collection_component +
        0.20 * renewal_component
    ))
    score = max(0, min(100, score))

    if score >= 80:
        status = "Excellent"
    elif score >= 60:
        status = "Good"
    elif score >= 40:
        status = "Average"
    else:
        status = "Needs Attention"

    return {"score": score, "status": status}


# ---------------------------------------------------------------------------
# Top revenue sources / expense categories
# ---------------------------------------------------------------------------

def _rank_categories(totals, limit=5):

    total_sum = sum(totals.values())
    ranked = []

    for i, (category, amount) in enumerate(totals.items(), start=1):
        if i > limit:
            break
        ranked.append({
            "rank": i,
            "category": category,
            "amount": amount,
            "percentage": round(amount / total_sum * 100, 1) if total_sum else 0,
        })

    return ranked


def get_top_revenue_sources(admin_id, limit=5):
    return _rank_categories(get_income_category_totals(admin_id), limit)


def get_top_expense_categories(admin_id, limit=5):
    return _rank_categories(get_expense_category_totals(admin_id), limit)


# ---------------------------------------------------------------------------
# Action Center
# ---------------------------------------------------------------------------

def get_action_items(admin_id):
    """Actionable recommendations derived from signals already computed above."""

    items = []

    growth = get_revenue_growth(admin_id)
    expense = classify_expense_health(admin_id)
    retention = get_membership_retention(admin_id)
    pending = get_pending_fees(admin_id)
    expiring_soon = get_upcoming_expiries(admin_id, days=7)

    if expiring_soon > 0:
        items.append({
            "type": "warning",
            "icon": "bi-calendar-x",
            "title": f"{expiring_soon} membership{'s' if expiring_soon != 1 else ''} expiring within 7 days",
            "description": "Reach out now to renew before they lapse.",
        })

    if pending > 0:
        items.append({
            "type": "warning",
            "icon": "bi-cash-coin",
            "title": f"₹{pending:,.0f} in pending fees",
            "description": "Follow up with members carrying outstanding balances.",
        })

    if expense["status"] in ("Warning", "Critical"):
        items.append({
            "type": "danger" if expense["status"] == "Critical" else "warning",
            "icon": "bi-graph-down-arrow",
            "title": f"Expenses at {expense['ratio_pct']:.0f}% of revenue",
            "description": "Review high-spend categories and cut avoidable costs.",
        })

    if retention["total"] > 0:
        renewal_rate = retention["active"] / retention["total"] * 100
        if renewal_rate < 60:
            items.append({
                "type": "danger",
                "icon": "bi-person-dash",
                "title": f"Only {renewal_rate:.0f}% of memberships are active",
                "description": "Retention is low - consider a renewal campaign.",
            })

    if growth["growth_pct"] <= -5:
        items.append({
            "type": "danger",
            "icon": "bi-arrow-down-right",
            "title": f"Revenue dropped {abs(growth['growth_pct']):.1f}% this month",
            "description": "Investigate the cause before it compounds next month.",
        })
    elif growth["growth_pct"] >= 5:
        items.append({
            "type": "success",
            "icon": "bi-arrow-up-right",
            "title": f"Revenue grew {growth['growth_pct']:.1f}% this month",
            "description": "Momentum is positive - current strategies are working.",
        })

    if not items:
        items.append({
            "type": "success",
            "icon": "bi-check-circle",
            "title": "No urgent issues detected",
            "description": "The library's finances and memberships look stable.",
        })

    return items


# ---------------------------------------------------------------------------
# Business Timeline
# ---------------------------------------------------------------------------

def get_business_timeline(admin_id, limit=8):
    """Recent financial activity, reusing Cashbook's own recency query."""

    rows = get_recent_transactions(admin_id, limit=limit)

    return [
        {
            "type": row["type"],
            "category": row["category"],
            "person": row["person"],
            "amount": row["amount"],
            "entry_date": row["entry_date"],
            "description": row["description"],
        }
        for row in rows
    ]
