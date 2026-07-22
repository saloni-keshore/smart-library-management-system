import sqlite3

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session
)

from database.db import get_connection
from database.payment_queries import record_payment


payment_bp = Blueprint(
    "payment",
    __name__,
    url_prefix="/payments"
)


@payment_bp.route("/")
def index():

    if "admin_id" not in session:
        return redirect("/")

    admin_id = session["admin_id"]

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT p.*, s.full_name
        FROM payments p
        INNER JOIN students s ON p.student_id = s.student_id
        WHERE s.admin_id = ?
        ORDER BY p.payment_id DESC
    """, (admin_id,))

    payments = cursor.fetchall()
    conn.close()

    return render_template("payments/index.html", payments=payments)


@payment_bp.route("/collect/<int:membership_id>", methods=["GET", "POST"])
def collect(membership_id):

    if "admin_id" not in session:
        return redirect("/")

    admin_id = session["admin_id"]

    conn = get_connection()
    cursor = conn.cursor()

    # Verify membership belongs to this admin via student ownership
    cursor.execute("""
        SELECT m.*
        FROM memberships m
        JOIN students s ON m.student_id = s.student_id
        WHERE m.membership_id = ? AND s.admin_id = ?
    """, (membership_id, admin_id))
    membership = cursor.fetchone()

    if membership is None:
        conn.close()
        flash("Membership not found.", "danger")
        return redirect(url_for("student.index"))

    cursor.execute(
        "SELECT * FROM students WHERE student_id=?",
        (membership["student_id"],)
    )
    student = cursor.fetchone()

    pending = float(membership["pending_amount"])

    if request.method == "POST":

        if pending <= 0:
            flash("This membership has no pending balance to collect.", "warning")
            conn.close()
            return redirect(url_for("student.view", student_id=student["student_id"]))

        amount_str = request.form.get("amount_paid", "0")

        try:
            amount = float(amount_str)
        except ValueError:
            flash("Invalid amount entered.", "danger")
            conn.close()
            return render_template(
                "payments/collect.html",
                membership=membership,
                student=student
            )

        if amount <= 0:
            flash("Amount must be greater than zero.", "danger")
            conn.close()
            return render_template(
                "payments/collect.html",
                membership=membership,
                student=student
            )

        if amount > pending:
            flash(
                f"Amount cannot exceed pending balance of ₹{pending:.0f}.",
                "danger"
            )
            conn.close()
            return render_template(
                "payments/collect.html",
                membership=membership,
                student=student
            )

        payment_mode = request.form.get("payment_mode")
        remarks = request.form.get("remarks")

        new_paid = float(membership["paid_amount"]) + amount
        new_pending = pending - amount

        try:
            cursor.execute("""
                UPDATE memberships
                SET paid_amount=?, pending_amount=?
                WHERE membership_id=?
            """, (new_paid, new_pending, membership_id))

            receipt_number = record_payment(
                conn,
                admin_id,
                membership_id=membership_id,
                student_id=student["student_id"],
                student_name=student["full_name"],
                payment_mode=payment_mode,
                amount=amount,
                remarks=remarks,
                category="Membership Fee",
                description=remarks or f"Pending fee payment - {membership['plan_name']}",
                source="Payments"
            )

            conn.commit()
        except sqlite3.Error:
            conn.rollback()
            flash(
                "Could not record this payment due to a database error. "
                "Nothing was saved - please try again.",
                "danger"
            )
            conn.close()
            return render_template(
                "payments/collect.html",
                membership=membership,
                student=student
            )

        conn.close()

        flash(
            f"Payment of ₹{amount:.0f} collected successfully. Receipt No: {receipt_number}",
            "success"
        )
        return redirect(url_for("student.view", student_id=student["student_id"]))

    conn.close()
    return render_template(
        "payments/collect.html",
        membership=membership,
        student=student
    )
