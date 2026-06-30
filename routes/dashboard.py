from flask import (
    Blueprint,
    render_template,
    session,
    redirect
)

from database.db import get_connection


dashboard_bp = Blueprint(
    "dashboard",
    __name__
)


@dashboard_bp.route("/dashboard")
def dashboard():

    if "admin_id" not in session:
        return redirect("/")

    conn = get_connection()
    cursor = conn.cursor()

    # ----------------------------
    # Total Students
    # ----------------------------

    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM students
        WHERE status='Active'
    """)

    total_students = cursor.fetchone()["total"]

    # ----------------------------
    # Total Enquiries
    # ----------------------------

    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM enquiries
    """)

    total_enquiries = cursor.fetchone()["total"]

    # ----------------------------
    # Active Memberships
    # ----------------------------

    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM memberships
        WHERE membership_status='Active'
    """)

    active_memberships = cursor.fetchone()["total"]

    # ----------------------------
    # Total Revenue
    # ----------------------------

    cursor.execute("""
        SELECT
            IFNULL(SUM(amount),0) AS revenue
        FROM payments
    """)

    total_revenue = cursor.fetchone()["revenue"]

    # ----------------------------
    # Pending Amount
    # ----------------------------

    cursor.execute("""
        SELECT
            IFNULL(SUM(pending_amount),0) AS pending
        FROM memberships
    """)

    pending_amount = cursor.fetchone()["pending"]

    # ----------------------------
    # Today's Collection
    # ----------------------------

    cursor.execute("""
        SELECT
            IFNULL(SUM(amount),0) AS today
        FROM payments
        WHERE payment_date = DATE('now')
    """)

    today_collection = cursor.fetchone()["today"]

    conn.close()

    return render_template(
        "dashboard/index.html",

        total_students=total_students,
        total_enquiries=total_enquiries,
        active_memberships=active_memberships,
        total_revenue=total_revenue,
        pending_amount=pending_amount,
        today_collection=today_collection
    )