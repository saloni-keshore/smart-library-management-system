from datetime import date, timedelta

from flask import Blueprint, render_template, session, redirect
from database.db import get_connection
from database.cashbook_queries import get_pending_fees, get_total_fee_revenue
from database.membership_queries import (
    get_membership_counts, get_memberships_for_admin, get_effective_status
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

    # This admin's memberships (each row already carries full_name/mobile) -
    # Supabase `students`/`memberships` (ADR-23) instead of the SQLite
    # mirror. `payments` itself is not yet migrated (see
    # docs/MIRROR_TRACKER.md), so each row's latest receipt/payment info
    # below is still looked up from SQLite `payments` directly.
    all_memberships = get_memberships_for_admin(admin_id)
    total_memberships = len(all_memberships)

    # Plan-wise counts
    plan_counts = {plan: 0 for plan in PLAN_ORDER}
    for m in all_memberships:
        if m["plan_name"] in plan_counts:
            plan_counts[m["plan_name"]] += 1

    plan_percentages = {
        plan: (round(count * 100 / total_memberships) if total_memberships else 0)
        for plan, count in plan_counts.items()
    }

    # Active/Expired memberships - shared with Dashboard's identical counts
    # (see database/membership_queries.py).
    membership_counts = get_membership_counts(admin_id)
    active_memberships = membership_counts["active"]
    expired_memberships = membership_counts["expired"]

    # Each row's most recent payment/receipt - `payments` is still SQLite-
    # only (out of scope for this analytics migration slice, see
    # docs/MIRROR_TRACKER.md), so this stays a single batched SQLite lookup
    # keyed by membership_id instead of one query per row.
    membership_ids = [m["membership_id"] for m in all_memberships]
    latest_payment_by_membership = {}

    if membership_ids:
        conn = get_connection()
        cursor = conn.cursor()
        placeholders = ",".join("?" * len(membership_ids))
        cursor.execute(f"""
            SELECT membership_id, receipt_number, payment_mode, payment_date, amount_paid
            FROM payments
            WHERE membership_id IN ({placeholders})
            ORDER BY payment_id DESC
        """, membership_ids)
        for row in cursor.fetchall():
            latest_payment_by_membership.setdefault(row["membership_id"], row)
        conn.close()

    memberships = []
    for m in sorted(all_memberships, key=lambda m: m["membership_id"], reverse=True):

        status = get_effective_status(m["membership_status"], m["end_date"])
        last_payment = latest_payment_by_membership.get(m["membership_id"])

        memberships.append({
            "membership_id": m["membership_id"],
            "library_id": "LIB{:04d}".format(m["student_id"]),
            "student_id": m["student_id"],
            "full_name": m["full_name"],
            "mobile": m["mobile"],
            "plan_name": m["plan_name"],
            "joining_date": m["joining_date"],
            "end_date": m["end_date"],
            "total_fee": m["total_fee"],
            "paid_amount": m["paid_amount"],
            "pending_amount": m["pending_amount"],
            "status": status,
            "receipt_number": last_payment["receipt_number"] if last_payment else None,
            "payment_mode": last_payment["payment_mode"] if last_payment else None,
            "payment_date": last_payment["payment_date"] if last_payment else None,
            "last_amount_paid": last_payment["amount_paid"] if last_payment else None,
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
