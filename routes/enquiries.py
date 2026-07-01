from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    flash,
    session,
    url_for
)

from database.db import get_connection

enquiry_bp = Blueprint(
    "enquiry",
    __name__,
    url_prefix="/enquiries"
)


@enquiry_bp.route("/")
def index():

    if "admin_id" not in session:
        return redirect("/")

    admin_id = session["admin_id"]

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT e.*, s.student_id AS student_id
        FROM enquiries e
        LEFT JOIN students s ON s.enquiry_id = e.enquiry_id
        WHERE e.admin_id = ?
        ORDER BY e.enquiry_id DESC
    """, (admin_id,))

    enquiries = cursor.fetchall()
    conn.close()

    return render_template("enquiries/index.html", enquiries=enquiries)


@enquiry_bp.route("/add", methods=["GET", "POST"])
def add():

    if "admin_id" not in session:
        return redirect("/")

    admin_id = session["admin_id"]

    if request.method == "POST":

        full_name = request.form.get("full_name", "").strip()
        mobile = request.form.get("mobile", "").strip()
        purpose = request.form.get("purpose", "").strip()
        preferred_shift = request.form.get("preferred_shift", "").strip()
        followup_date = request.form.get("followup_date", "")
        remarks = request.form.get("remarks", "").strip()

        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO enquiries
            (admin_id, full_name, mobile, purpose, preferred_shift, followup_date, remarks)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (admin_id, full_name, mobile, purpose, preferred_shift, followup_date, remarks))

        conn.commit()
        conn.close()

        flash("Enquiry added successfully.", "success")
        return redirect(url_for("enquiry.index"))

    return render_template("enquiries/add.html")


@enquiry_bp.route("/edit/<int:enquiry_id>", methods=["GET", "POST"])
def edit(enquiry_id):

    if "admin_id" not in session:
        return redirect("/")

    admin_id = session["admin_id"]

    conn = get_connection()
    cursor = conn.cursor()

    if request.method == "POST":

        full_name = request.form.get("full_name", "").strip()
        mobile = request.form.get("mobile", "").strip()
        purpose = request.form.get("purpose", "").strip()
        preferred_shift = request.form.get("preferred_shift", "").strip()
        followup_date = request.form.get("followup_date")
        remarks = request.form.get("remarks", "").strip()

        cursor.execute("""
            UPDATE enquiries
            SET full_name=?, mobile=?, purpose=?, preferred_shift=?,
                followup_date=?, remarks=?
            WHERE enquiry_id=? AND admin_id=?
        """, (full_name, mobile, purpose, preferred_shift,
              followup_date, remarks, enquiry_id, admin_id))

        conn.commit()
        conn.close()

        flash("Enquiry updated successfully.", "success")
        return redirect(url_for("enquiry.index"))

    cursor.execute(
        "SELECT * FROM enquiries WHERE enquiry_id=? AND admin_id=?",
        (enquiry_id, admin_id)
    )
    enquiry = cursor.fetchone()
    conn.close()

    if enquiry is None:
        flash("Enquiry not found.", "danger")
        return redirect(url_for("enquiry.index"))

    return render_template("enquiries/edit.html", enquiry=enquiry)


@enquiry_bp.route("/delete/<int:enquiry_id>")
def delete(enquiry_id):

    if "admin_id" not in session:
        return redirect("/")

    admin_id = session["admin_id"]

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "DELETE FROM enquiries WHERE enquiry_id=? AND admin_id=?",
        (enquiry_id, admin_id)
    )

    conn.commit()
    conn.close()

    flash("Enquiry deleted successfully.", "success")
    return redirect(url_for("enquiry.index"))


@enquiry_bp.route("/view/<int:enquiry_id>")
def view(enquiry_id):

    if "admin_id" not in session:
        return redirect("/")

    admin_id = session["admin_id"]

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM enquiries WHERE enquiry_id=? AND admin_id=?",
        (enquiry_id, admin_id)
    )
    enquiry = cursor.fetchone()

    if enquiry is None:
        conn.close()
        flash("Enquiry not found.", "danger")
        return redirect(url_for("enquiry.index"))

    cursor.execute(
        "SELECT student_id FROM students WHERE enquiry_id=? AND admin_id=?",
        (enquiry_id, admin_id)
    )
    student = cursor.fetchone()
    conn.close()

    return render_template("enquiries/view.html", enquiry=enquiry, student=student)
