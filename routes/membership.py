from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash
)

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

    return "Membership Module Coming Soon"


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
        total_fee = request.form.get("total_fee")
        remarks = request.form.get("remarks")
 
        if float(total_fee) <=0:
            flash("Total fee must be greater than zero.", "danger")
            conn.close()

            return render_template(
                "memberships/create.html", student=student
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
                0,
                total_fee,
                remarks,
                "Active"
            )
        )

        membership_id = cursor.lastrowid

        conn.commit()
        conn.close()

        flash(
            "Membership created successfully.",
            "success"
        )

        return redirect(
            url_for(
                "payment.create",
                membership_id=membership_id
            )
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
        total_fee = request.form.get("total_fee")
        remarks = request.form.get("remarks")

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
                0,
                total_fee,
                remarks,
                "Active"
            )
        )

        membership_id = cursor.lastrowid

        conn.commit()
        conn.close()

        flash(
            "Membership renewed successfully.",
            "success"
        )

        return redirect(
            url_for(
                "payment.create",
                membership_id=membership_id
            )
        )

    conn.close()

    return render_template(
        "memberships/renew.html",
        student=student
    )