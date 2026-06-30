from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    flash,
    request
)

from database.db import get_connection


student_bp = Blueprint(
    "student",
    __name__,
    url_prefix="/students"
)


# ---------------------------------------
# Student List
# ---------------------------------------

@student_bp.route("/")
def index():

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            s.student_id,
            s.full_name,
            s.mobile,
            s.purpose,
            s.shift,
            s.status,

            m.membership_id,
            m.plan_name,
            m.pending_amount,
            m.membership_status

        FROM students s

        LEFT JOIN memberships m
            ON m.membership_id = (
                SELECT membership_id
                FROM memberships
                WHERE student_id = s.student_id
                ORDER BY membership_id DESC
                LIMIT 1
            )

        ORDER BY s.student_id DESC
    """)

    students = cursor.fetchall()

    conn.close()

    return render_template(
        "students/index.html",
        students=students
    )


# ---------------------------------------
# Student Admission
# ---------------------------------------

@student_bp.route("/admission/<int:enquiry_id>", methods=["GET", "POST"])
def admission(enquiry_id):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM enquiries
        WHERE enquiry_id = ?
    """, (enquiry_id,))

    enquiry = cursor.fetchone()

    if enquiry is None:
        conn.close()
        flash("Enquiry not found.", "danger")
        return redirect(url_for("enquiry.index"))

    if request.method == "POST":

        address = request.form.get("address", "").strip()
        id_proof = request.form.get("id_proof", "").strip()
        join_date = request.form.get("join_date")

        # -------------------------------
        # Check Existing Student
        # -------------------------------

        cursor.execute("""
            SELECT student_id
            FROM students
            WHERE mobile = ?
        """, (enquiry["mobile"],))

        existing_student = cursor.fetchone()

        if existing_student is not None:

            conn.close()

            flash(
                "This student has already been admitted.",
                "warning"
            )

            return redirect(
                url_for(
                    "student.view",
                    student_id=existing_student["student_id"]
                )
            )

        # -------------------------------
        # Insert Student
        # -------------------------------

        cursor.execute("""
            INSERT INTO students
            (
                enquiry_id,
                full_name,
                mobile,
                address,
                id_proof,
                purpose,
                shift,
                join_date,
                status
            )
            VALUES
            (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            enquiry["enquiry_id"],
            enquiry["full_name"],
            enquiry["mobile"],
            address,
            id_proof,
            enquiry["purpose"],
            enquiry["preferred_shift"],
            join_date,
            "Active"
        ))

        student_id = cursor.lastrowid

        cursor.execute("""
            UPDATE enquiries
            SET status = ?
            WHERE enquiry_id = ?
        """,
        (
            "Admitted",
            enquiry["enquiry_id"]
        ))

        conn.commit()
        conn.close()

        flash(
            "Student admitted successfully. Please create membership.",
            "success"
        )

        return redirect(
            url_for(
                "membership.create",
                student_id=student_id
            )
        )

    conn.close()

    return render_template(
        "students/admission.html",
        enquiry=enquiry
    )


# ---------------------------------------
# Student Profile
# ---------------------------------------

@student_bp.route("/view/<int:student_id>")
def view(student_id):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM students
        WHERE student_id = ?
    """, (student_id,))

    student = cursor.fetchone()

    if student is None:

        conn.close()

        flash("Student not found.", "danger")

        return redirect(url_for("student.index"))

    cursor.execute("""
        SELECT *
        FROM memberships
        WHERE student_id = ?
        ORDER BY membership_id DESC
        LIMIT 1
    """, (student_id,))

    membership = cursor.fetchone()

    cursor.execute("""
        SELECT p.*
        FROM payments p

        INNER JOIN memberships m
            ON p.membership_id = m.membership_id

        WHERE m.student_id = ?
        ORDER BY payment_id DESC
    """, (student_id,))

    payments = cursor.fetchall()

    conn.close()

    return render_template(
        "students/view.html",
        student=student,
        membership=membership,
        payments=payments
    )


# ---------------------------------------
# Edit Student
# ---------------------------------------

@student_bp.route("/edit/<int:student_id>", methods=["GET", "POST"])
def edit(student_id):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT *
        FROM students
        WHERE student_id = ?
    """, (student_id,))

    student = cursor.fetchone()

    if student is None:

        conn.close()

        flash("Student not found.", "danger")

        return redirect(url_for("student.index"))

    if request.method == "POST":

        full_name = request.form.get("full_name")
        mobile = request.form.get("mobile")
        address = request.form.get("address")
        purpose = request.form.get("purpose")
        shift = request.form.get("shift")
        status = request.form.get("status")

        cursor.execute("""
            UPDATE students
            SET
                full_name = ?,
                mobile = ?,
                address = ?,
                purpose = ?,
                shift = ?,
                status = ?
            WHERE student_id = ?
        """,
        (
            full_name,
            mobile,
            address,
            purpose,
            shift,
            status,
            student_id
        ))

        conn.commit()
        conn.close()

        flash(
            "Student updated successfully.",
            "success"
        )

        return redirect(
            url_for(
                "student.view",
                student_id=student_id
            )
        )

    conn.close()

    return render_template(
        "students/edit.html",
        student=student
    )