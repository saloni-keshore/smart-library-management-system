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

    admin_id = session["admin_id"]

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

    conn.close()

    return render_template(
        "dashboard/index.html",
        total_students=total_students,
        total_enquiries=total_enquiries,
        active_memberships=active_memberships,
        expired_memberships=expired_memberships,
        total_revenue=total_revenue,
        pending_amount=pending_amount,
        today_collection=today_collection
    )
