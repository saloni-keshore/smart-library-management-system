from flask import (
    Blueprint,
    render_template,
    session,
    redirect
)

from database.db import get_connection
from utils.charts import ( generate_revenue_chart,
                           generate_membership_chart )
from database.cashbook_categories import (
    MANUAL_INCOME_CATEGORIES,
    MANUAL_EXPENSE_CATEGORIES,
    PAYMENT_METHODS
)
from database.cashbook_queries import (
    get_pending_fees,
    get_total_fee_revenue,
    get_today_fee_collection
)
from database.notification_settings_queries import get_notification_settings_cached
from database.membership_queries import get_membership_counts, DAYS_LEFT_SQL


dashboard_bp = Blueprint(
    "dashboard",
    __name__
)


@dashboard_bp.route("/dashboard")
def dashboard():

    if "admin_id" not in session:
        return redirect("/")

    admin_id = session["admin_id"]
    generate_revenue_chart(admin_id)
    generate_membership_chart(admin_id)

    conn = get_connection()
    cursor = conn.cursor()

    # Total Students
    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM students
        WHERE status = 'Active' AND admin_id = ?
    """, (admin_id,))
    total_students = cursor.fetchone()["total"]

    # Total Enquiries
    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM enquiries
        WHERE admin_id = ?
    """, (admin_id,))
    total_enquiries = cursor.fetchone()["total"]

    # Active/Expired Memberships - shared with Membership Distribution's
    # identical counts (see database/membership_queries.py).
    membership_counts = get_membership_counts(admin_id)
    active_memberships = membership_counts["active"]
    expired_memberships = membership_counts["expired"]

    # Total Revenue (same source of truth as Membership Distribution's
    # "Revenue Collected" - see database/cashbook_queries.py)
    total_revenue = get_total_fee_revenue(admin_id)

    # Pending Amount (same source of truth as Cashbook's "Pending Fees" and
    # Membership Distribution's "Pending Payments")
    pending_amount = get_pending_fees(admin_id)

    # Today's Collection (same fee-revenue family as Total Revenue/Pending
    # Fees above - see database/cashbook_queries.py)
    today_collection = get_today_fee_collection(admin_id)

    # Upcoming Expiries (next 7 days, nearest first)
    cursor.execute(f"""
        SELECT
            s.student_id,
            s.full_name,
            m.end_date,
            {DAYS_LEFT_SQL} AS days_left
        FROM memberships m
        JOIN students s ON m.student_id = s.student_id
        WHERE s.admin_id = ?
        AND m.membership_status = 'Active'
        AND m.end_date >= DATE('now')
        AND m.end_date <= DATE('now', '+7 days')
        ORDER BY m.end_date ASC
    """, (admin_id,))
    expiry_rows = cursor.fetchall()

    expiries = [
        {
            "library_id": "LIB{:04d}".format(row["student_id"]),
            "student_name": row["full_name"],
            "end_date": row["end_date"],
            "days_left": row["days_left"]
        }
        for row in expiry_rows[:5]
    ]
    expiries_total = len(expiry_rows)

    # Recent Admissions (latest 5, newest first)
    cursor.execute("""
        SELECT
            s.student_id,
            s.full_name,
            s.join_date,
            m.plan_name
        FROM students s
        LEFT JOIN memberships m ON m.membership_id = (
            SELECT membership_id
            FROM memberships
            WHERE student_id = s.student_id
            ORDER BY membership_id DESC
            LIMIT 1
        )
        WHERE s.admin_id = ?
        ORDER BY s.join_date DESC, s.student_id DESC
        LIMIT 5
    """, (admin_id,))
    admission_rows = cursor.fetchall()

    admissions = [
        {
            "library_id": "LIB{:04d}".format(row["student_id"]),
            "student_name": row["full_name"],
            "plan": row["plan_name"] or "--",
            "admission_date": row["join_date"]
        }
        for row in admission_rows
    ]

    conn.close()

    notification_settings = get_notification_settings_cached(admin_id)
    dash_show_pending_fees = (
        bool(notification_settings["dash_show_pending_fees"])
        if notification_settings else True
    )

    return render_template(
        "dashboard/index.html",
        total_students=total_students,
        total_enquiries=total_enquiries,
        active_memberships=active_memberships,
        expired_memberships=expired_memberships,
        total_revenue=total_revenue,
        pending_amount=pending_amount,
        today_collection=today_collection,
        expiries=expiries,
        expiries_total=expiries_total,
        upcoming_renewals=expiries_total,
        admissions=admissions,
        manual_income_categories=MANUAL_INCOME_CATEGORIES,
        manual_expense_categories=MANUAL_EXPENSE_CATEGORIES,
        payment_methods=PAYMENT_METHODS,
        dash_show_pending_fees=dash_show_pending_fees
    )

   
