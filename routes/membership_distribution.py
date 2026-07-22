from datetime import date, timedelta

from flask import Blueprint, render_template, session, redirect
from database.db import get_connection
from database.cashbook_queries import get_pending_fees, get_total_fee_revenue
from database.membership_queries import (
    get_membership_counts, get_effective_status, DAYS_LEFT_SQL
)
from utils.charts import generate_membership_distribution_donut

membership_distribution_bp = Blueprint(
    "membership_distribution",
    __name__,
    url_prefix="/membership-distribution"
)

PLAN_ORDER = ["Monthly", "Quarterly", "Half-Yearly", "Yearly"]


@membership_distribution_bp.route("/")
def index():

    if "admin_id" not in session:
        return redirect("/")

    admin_id = session["admin_id"]

    generate_membership_distribution_donut(admin_id)

    conn = get_connection()
    cursor = conn.cursor()

    # Total memberships
    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM memberships m
        JOIN students s ON m.student_id = s.student_id
        WHERE s.admin_id = ?
    """, (admin_id,))
    total_memberships = cursor.fetchone()["total"]

    # Plan-wise counts
    cursor.execute("""
        SELECT m.plan_name, COUNT(*) AS total
        FROM memberships m
        JOIN students s ON m.student_id = s.student_id
        WHERE s.admin_id = ?
        GROUP BY m.plan_name
    """, (admin_id,))

    plan_counts = {plan: 0 for plan in PLAN_ORDER}
    for row in cursor.fetchall():
        if row["plan_name"] in plan_counts:
            plan_counts[row["plan_name"]] = row["total"]

    plan_percentages = {
        plan: (round(count * 100 / total_memberships) if total_memberships else 0)
        for plan, count in plan_counts.items()
    }

    # Active/Expired memberships - shared with Dashboard's identical counts
    # (see database/membership_queries.py).
    membership_counts = get_membership_counts(admin_id)
    active_memberships = membership_counts["active"]
    expired_memberships = membership_counts["expired"]

    # Full membership listing, with each row's most recent payment/receipt
    cursor.execute(f"""
        SELECT
            m.membership_id,
            s.student_id,
            s.full_name,
            s.mobile,
            m.plan_name,
            m.joining_date,
            m.end_date,
            m.total_fee,
            m.paid_amount,
            m.pending_amount,
            m.membership_status,
            {DAYS_LEFT_SQL} AS days_left,
            (SELECT p.receipt_number FROM payments p
                WHERE p.membership_id = m.membership_id
                ORDER BY p.payment_id DESC LIMIT 1) AS receipt_number,
            (SELECT p.payment_mode FROM payments p
                WHERE p.membership_id = m.membership_id
                ORDER BY p.payment_id DESC LIMIT 1) AS payment_mode,
            (SELECT p.payment_date FROM payments p
                WHERE p.membership_id = m.membership_id
                ORDER BY p.payment_id DESC LIMIT 1) AS payment_date,
            (SELECT p.amount_paid FROM payments p
                WHERE p.membership_id = m.membership_id
                ORDER BY p.payment_id DESC LIMIT 1) AS last_amount_paid
        FROM memberships m
        JOIN students s ON m.student_id = s.student_id
        WHERE s.admin_id = ?
        ORDER BY m.membership_id DESC
    """, (admin_id,))

    rows = cursor.fetchall()
    conn.close()

    memberships = []
    for row in rows:

        status = get_effective_status(row["membership_status"], row["end_date"])

        memberships.append({
            "membership_id": row["membership_id"],
            "library_id": "LIB{:04d}".format(row["student_id"]),
            "student_id": row["student_id"],
            "full_name": row["full_name"],
            "mobile": row["mobile"],
            "plan_name": row["plan_name"],
            "joining_date": row["joining_date"],
            "end_date": row["end_date"],
            "total_fee": row["total_fee"],
            "paid_amount": row["paid_amount"],
            "pending_amount": row["pending_amount"],
            "status": status,
            "receipt_number": row["receipt_number"],
            "payment_mode": row["payment_mode"],
            "payment_date": row["payment_date"],
            "last_amount_paid": row["last_amount_paid"],
        })

    # Quick Insights — derived read-only from the data already fetched above,
    # no new queries beyond what the page already loads.
    most_popular_plan = max(plan_counts, key=plan_counts.get) if total_memberships else "-"
    most_popular_plan_pct = plan_percentages.get(most_popular_plan, 0)

    today_str = date.today().isoformat()
    renewal_cutoff_str = (date.today() + timedelta(days=7)).isoformat()
    upcoming_renewals = sum(
        1 for m in memberships
        if m["status"] == "Active" and m["end_date"] and today_str <= m["end_date"] <= renewal_cutoff_str
    )

    # Same source of truth as Dashboard's "Total Revenue"/"Pending Fees" and
    # Cashbook's "Pending Fees" (see database/cashbook_queries.py) rather
    # than re-summing the page's already-fetched rows in Python.
    total_revenue = get_total_fee_revenue(admin_id)
    total_pending = get_pending_fees(admin_id)

    return render_template(
        "memberships/distribution.html",
        total_memberships=total_memberships,
        plan_counts=plan_counts,
        plan_percentages=plan_percentages,
        active_memberships=active_memberships,
        expired_memberships=expired_memberships,
        memberships=memberships,
        most_popular_plan=most_popular_plan,
        most_popular_plan_pct=most_popular_plan_pct,
        upcoming_renewals=upcoming_renewals,
        total_revenue=total_revenue,
        total_pending=total_pending
    )
