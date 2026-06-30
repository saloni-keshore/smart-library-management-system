from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash
)

from datetime import date

from database.db import get_connection


payment_bp = Blueprint(
    "payment",
    __name__,
    url_prefix="/payments"
)


# ---------------------------------------
# Payment List
# ---------------------------------------

@payment_bp.route("/")
def index():

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT p.*, s.full_name
        FROM payments p
        INNER JOIN students s ON p.student_id = s.student_id
        ORDER BY p.payment_id DESC
    """)

    payments = cursor.fetchall()
    conn.close()

    return render_template("payments/index.html", payments=payments)


# ---------------------------------------
# Create Payment
# ---------------------------------------

@payment_bp.route("/create/<int:membership_id>", methods=["GET", "POST"])
def create(membership_id):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT *
        FROM memberships
        WHERE membership_id = ?
        """,
        (membership_id,)
    )

    membership = cursor.fetchone()

    if membership is None:
        conn.close()
        flash("Membership not found.", "danger")
        return redirect(url_for("student.index"))

    cursor.execute(
        """
        SELECT *
        FROM students
        WHERE student_id = ?
        """,
        (membership["student_id"],)
    )

    student = cursor.fetchone()

    if request.method == "POST":

        paid_amount_str = request.form.get("paid_amount", "0")

        try:
            paid_amount = float(paid_amount_str)
        except ValueError:
            flash("Invalid amount entered.", "danger")
            conn.close()
            return render_template(
                "payments/create.html",
                membership=membership,
                student=student
            )

        if paid_amount <= 0:
            flash("Paid amount must be greater than zero.", "danger")
            conn.close()
            return render_template(
                "payments/create.html",
                membership=membership,
                student=student
            )

        payment_mode = request.form.get("payment_mode")
        remarks = request.form.get("remarks")

        total_fee = float(membership["total_fee"])

        if paid_amount > total_fee:
            flash("Paid amount cannot be greater than total fee.", "danger")
            conn.close()
            return render_template(
                "payments/create.html",
                membership=membership,
                student=student
            )

        pending_amount = total_fee - paid_amount

        receipt_number = (
            f"REC-{date.today().strftime('%Y%m%d')}-{membership_id:04d}"
        )

        cursor.execute(
            """
            INSERT INTO payments
            (
                membership_id,
                student_id,
                receipt_number,
                payment_mode,
                amount_paid,
                payment_date,
                remarks
            )
            VALUES
            (
                ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                membership_id,
                student["student_id"],
                receipt_number,
                payment_mode,
                paid_amount,
                date.today(),
                remarks
            )
        )

        cursor.execute(
            """
            UPDATE memberships
            SET
                paid_amount = ?,
                pending_amount = ?
            WHERE membership_id = ?
            """,
            (
                paid_amount,
                pending_amount,
                membership_id
            )
        )

        conn.commit()
        conn.close()

        flash("Payment recorded successfully.", "success")

        return render_template(
            "payments/success.html",
            student=student,
            membership=membership,
            receipt_number=receipt_number,
            paid_amount=paid_amount,
            pending_amount=pending_amount
        )

    conn.close()

    return render_template(
        "payments/create.html",
        membership=membership,
        student=student
    )


# ---------------------------------------
# Collect Pending Payment
# ---------------------------------------

@payment_bp.route("/collect/<int:membership_id>", methods=["GET", "POST"])
def collect(membership_id):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT *
        FROM memberships
        WHERE membership_id = ?
        """,
        (membership_id,)
    )

    membership = cursor.fetchone()

    if membership is None:
        conn.close()
        flash("Membership not found.", "danger")
        return redirect(url_for("student.index"))

    cursor.execute(
        """
        SELECT *
        FROM students
        WHERE student_id = ?
        """,
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

        payment_mode = request.form.get("payment_mode")
        remarks = request.form.get("remarks")

        new_paid = membership["paid_amount"] + amount
        new_pending = membership["pending_amount"] - amount

        if new_pending < 0:
            new_pending = 0

        cursor.execute(
            """
            INSERT INTO payments
            (
                membership_id,
                student_id,
                receipt_number,
                payment_mode,
                amount_paid,
                payment_date,
                remarks
            )
            VALUES
            (
                ?, ?, ?, ?, ?, DATE('now'), ?
            )
            """,
            (
                membership_id,
                student["student_id"],
                f"REC-{membership_id}-{int(new_paid)}",
                payment_mode,
                amount,
                remarks
            )
        )

        cursor.execute(
            """
            UPDATE memberships
            SET
                paid_amount=?,
                pending_amount=?
            WHERE membership_id=?
            """,
            (
                new_paid,
                new_pending,
                membership_id
            )
        )

        conn.commit()
        conn.close()

        flash("Payment collected successfully.", "success")

        return redirect(
            url_for("student.view", student_id=student["student_id"])
        )

    conn.close()

    return render_template(
        "payments/collect.html",
        membership=membership,
        student=student
    )
