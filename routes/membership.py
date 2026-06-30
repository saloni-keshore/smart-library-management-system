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

membership_bp = Blueprint(
    "membership",
    __name__,
    url_prefix="/memberships"
)


# ---------------------------------------
# Membership List
# ---------------------------------------

@membership_bp.route("/")
def index():

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT m.*, s.full_name, s.mobile
        FROM memberships m
        INNER JOIN students s ON m.student_id = s.student_id
        ORDER BY m.membership_id DESC
    """)

    memberships = cursor.fetchall()
    conn.close()

    return render_template("memberships/index.html", memberships=memberships)


# ---------------------------------------
# Create Membership
# ---------------------------------------

@membership_bp.route("/create/<int:student_id>", methods=["GET", "POST"])
def create(student_id):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT *
        FROM students
        WHERE student_id = ?
        """,
        (student_id,)
    )

    student = cursor.fetchone()

    if student is None:

        conn.close()

        flash("Student not found.", "danger")

        return redirect(url_for("student.index"))

    if request.method == "POST":

        plan_name = request.form.get("plan_name")
        joining_date = request.form.get("joining_date")
        duration_days = request.form.get("duration")
        end_date = request.form.get("end_date")
        remarks = request.form.get("remarks")
        payment_mode = request.form.get("payment_mode", "Cash")

        try:
            paid_amount = float(request.form.get("paid_amount", 0) or 0)
            due_amount = float(request.form.get("due_amount", 0) or 0)
        except ValueError:
            flash("Invalid amount entered.", "danger")
            conn.close()
            return render_template("memberships/create.html", student=student)

        total_fee = paid_amount + due_amount

        if total_fee <= 0:
            flash("Total fee must be greater than zero.", "danger")
            conn.close()
            return render_template("memberships/create.html", student=student)

        cursor.execute(
            """
            INSERT INTO memberships
            (
                student_id,
                plan_name,
                joining_date,
                duration_days,
                end_date,
                total_fee,
                paid_amount,
                pending_amount,
                remarks,
                membership_status
            )
            VALUES
            (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                student_id,
                plan_name,
                joining_date,
                duration_days,
                end_date,
                total_fee,
                paid_amount,
                due_amount,
                remarks,
                "Active"
            )
        )

        membership_id = cursor.lastrowid

        if paid_amount > 0:
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
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    membership_id,
                    student_id,
                    receipt_number,
                    payment_mode,
                    paid_amount,
                    date.today(),
                    remarks
                )
            )

        conn.commit()
        conn.close()

        flash(
            "Membership created successfully.",
            "success"
        )

        return redirect(
            url_for("student.view", student_id=student_id)
        )

    conn.close()

    return render_template(
        "memberships/create.html",
        student=student
    )


# ---------------------------------------
# Renew Membership
# ---------------------------------------

@membership_bp.route("/renew/<int:student_id>", methods=["GET", "POST"])
def renew(student_id):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT *
        FROM students
        WHERE student_id = ?
        """,
        (student_id,)
    )

    student = cursor.fetchone()

    if student is None:

        conn.close()

        flash("Student not found.", "danger")

        return redirect(url_for("student.index"))

    if request.method == "POST":

        plan_name = request.form.get("plan_name")
        joining_date = request.form.get("joining_date")
        duration_days = request.form.get("duration_days")
        end_date = request.form.get("end_date")
        remarks = request.form.get("remarks")
        payment_mode = request.form.get("payment_mode", "Cash")

        try:
            paid_amount = float(request.form.get("paid_amount", 0) or 0)
            due_amount = float(request.form.get("due_amount", 0) or 0)
        except ValueError:
            flash("Invalid amount entered.", "danger")
            conn.close()
            return render_template("memberships/renew.html", student=student)

        total_fee = paid_amount + due_amount

        if total_fee <= 0:
            flash("Total fee must be greater than zero.", "danger")
            conn.close()
            return render_template("memberships/renew.html", student=student)

        cursor.execute(
            """
            UPDATE memberships
            SET membership_status = 'Expired'
            WHERE student_id = ? AND membership_status = 'Active'
            """,
            (student_id,)
        )

        cursor.execute(
            """
            INSERT INTO memberships
            (
                student_id,
                plan_name,
                joining_date,
                duration_days,
                end_date,
                total_fee,
                paid_amount,
                pending_amount,
                remarks,
                membership_status
            )
            VALUES
            (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                student_id,
                plan_name,
                joining_date,
                duration_days,
                end_date,
                total_fee,
                paid_amount,
                due_amount,
                remarks,
                "Active"
            )
        )

        membership_id = cursor.lastrowid

        if paid_amount > 0:
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
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    membership_id,
                    student_id,
                    receipt_number,
                    payment_mode,
                    paid_amount,
                    date.today(),
                    remarks
                )
            )

        conn.commit()
        conn.close()

        flash(
            "Membership renewed successfully.",
            "success"
        )

        return redirect(
            url_for("student.view", student_id=student_id)
        )

    conn.close()

    return render_template(
        "memberships/renew.html",
        student=student
    )