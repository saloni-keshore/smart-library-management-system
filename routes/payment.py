from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session
)

from datetime import date

from database.db import get_connection
from database.cashbook_queries import insert_income_entry


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

    if request.method == "POST":

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

        pending = float(membership["pending_amount"])
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

        # Use timestamp-based receipt to avoid collisions
        receipt_number = (
            f"REC-{date.today().strftime('%Y%m%d')}-{membership_id:04d}"
            f"-{int(new_paid):04d}"
        )

        cursor.execute("""
            INSERT INTO payments
            (membership_id, student_id, receipt_number, payment_mode,
             amount_paid, payment_date, remarks)
            VALUES (?, ?, ?, ?, ?, DATE('now'), ?)
        """, (
            membership_id, student["student_id"],
            receipt_number, payment_mode, amount, remarks
        ))

        cursor.execute("""
            UPDATE memberships
            SET paid_amount=?, pending_amount=?
            WHERE membership_id=?
        """, (new_paid, new_pending, membership_id))

        insert_income_entry(
            conn,
            admin_id,
            category="Membership Fee",
            person=student["full_name"],
            description=remarks or f"Pending fee payment - {membership['plan_name']}",
            amount=amount,
            payment_method=payment_mode,
            entry_date=date.today().isoformat(),
            source="Payments"
        )

        conn.commit()
        conn.close()

        flash("Payment collected successfully.", "success")
        return redirect(url_for("student.view", student_id=student["student_id"]))

    conn.close()
    return render_template(
        "payments/collect.html",
        membership=membership,
        student=student
    )
