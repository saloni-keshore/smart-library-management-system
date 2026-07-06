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

    # Active Memberships (not yet past end_date)
    cursor.execute("""
        SELECT COUNT(DISTINCT m.student_id) AS total
        FROM memberships m
        JOIN students s ON m.student_id = s.student_id
        WHERE m.membership_status = 'Active'
        AND m.end_date >= DATE('now')
        AND s.admin_id = ?
    """, (admin_id,))
    active_memberships = cursor.fetchone()["total"]

    # Expired Memberships (end_date passed, status still Active)
    cursor.execute("""
        SELECT COUNT(DISTINCT m.student_id) AS total
        FROM memberships m
        JOIN students s ON m.student_id = s.student_id
        WHERE m.end_date < DATE('now')
        AND m.membership_status = 'Active'
        AND s.admin_id = ?
    """, (admin_id,))
    expired_memberships = cursor.fetchone()["total"]

    # Total Revenue
    cursor.execute("""
        SELECT IFNULL(SUM(p.amount_paid), 0) AS revenue
        FROM payments p
        JOIN students s ON p.student_id = s.student_id
        WHERE s.admin_id = ?
    """, (admin_id,))
    total_revenue = cursor.fetchone()["revenue"]

    # Pending Amount
    cursor.execute("""
        SELECT IFNULL(SUM(m.pending_amount), 0) AS pending
        FROM memberships m
        JOIN students s ON m.student_id = s.student_id
        WHERE s.admin_id = ?
    """, (admin_id,))
    pending_amount = cursor.fetchone()["pending"]

    # Today's Collection
    cursor.execute("""
        SELECT IFNULL(SUM(p.amount_paid), 0) AS today
        FROM payments p
        JOIN students s ON p.student_id = s.student_id
        WHERE p.payment_date = DATE('now')
        AND s.admin_id = ?
    """, (admin_id,))
    today_collection = cursor.fetchone()["today"]

    # Upcoming Expiries (next 7 days, nearest first)
    cursor.execute("""
        SELECT
            s.student_id,
            s.full_name,
            m.end_date,
            CAST(julianday(m.end_date) - julianday(DATE('now')) AS INTEGER) AS days_left
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
        payment_methods=PAYMENT_METHODS
    )

   
