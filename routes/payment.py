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

    return "Payment Module Coming Soon"


# ---------------------------------------
# Create Payment
# ---------------------------------------

@payment_bp.route("/create/<int:membership_id>", methods=["GET", "POST"])
def create(membership_id):

    conn = get_connection()
    cursor = conn.cursor()


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

        flash(
            "Membership not found.",
            "danger"
        )

        return redirect(
            url_for("student.index")
        )

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

        amount = float(
            request.form.get("amount_paid")
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
                f"REC-{membership_id}-{new_paid}",
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

        flash(
            "Payment collected successfully.",
            "success"
        )

        return redirect(
            url_for(
                "student.view",
                student_id=student["student_id"]
            )
        )

    conn.close()

    return render_template(
        "payments/collect.html",
        membership=membership,
        student=student
    )



    # ---------------------------------------
    # Get Membership
    # ---------------------------------------

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

    # ---------------------------------------
    # Get Student
    # ---------------------------------------

    cursor.execute(
        """
        SELECT *
        FROM students
        WHERE student_id = ?
        """,
        (membership["student_id"],)
    )

    student = cursor.fetchone()

    # ---------------------------------------
    # Save Payment
    # ---------------------------------------

    if request.method == "POST":

        paid_amount = float(request.form.get("paid_amount"))

        payment_mode = request.form.get("payment_mode")

        remarks = request.form.get("remarks")

        total_fee = float(membership["total_fee"])

        pending_amount = total_fee - paid_amount

        # Prevent overpayment

        if paid_amount > total_fee:

            flash(
                "Paid amount cannot be greater than total fee.",
                "danger"
            )

            conn.close()

            return render_template(
                "payments/create.html",
                membership=membership,
                student=student
            )

        # Generate Receipt Number

        receipt_number = (
            f"REC-{date.today().strftime('%Y%m%d')}-{membership_id:04d}"
        )

        # Insert Payment

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

        # Update Membership

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