import sqlite3
from datetime import date

from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    flash,
    request,
    session
)
from postgrest.exceptions import APIError

from database.db import get_connection
from database.membership_queries import EFFECTIVE_STATUS_SQL
from database.supabase_client import get_supabase_client


student_bp = Blueprint(
    "student",
    __name__,
    url_prefix="/students"
)


def _sanitize_date(value):
    """Return an ISO ('YYYY-MM-DD') date string or None. Supabase's
    join_date column is a strictly-typed PostgreSQL DATE, unlike SQLite's,
    which silently accepted any string -- blank/unparsable input must
    become NULL instead of raising an APIError on insert (same helper
    shape as routes/enquiries.py's _sanitize_date, ADR-18)."""
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        date.fromisoformat(text)
    except ValueError:
        return None
    return text


@student_bp.route("/")
def index():

    if "admin_id" not in session:
        return redirect("/")

    admin_id = session["admin_id"]

    supabase = get_supabase_client()
    try:
        response = (
            supabase.table("students")
            .select("*")
            .eq("admin_id", admin_id)
            .order("student_id", desc=True)
            .execute()
        )
        students = response.data
    except APIError:
        students = []

    # memberships stays SQLite (out of this session's scope) -- attach each
    # student's latest membership + effective status the same way the old
    # correlated-subquery LEFT JOIN did, merged in Python against the
    # Supabase students list instead of a database-level join.
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(f"""
        SELECT
            s.student_id,
            m.membership_id,
            m.plan_name,
            m.paid_amount,
            m.pending_amount,
            {EFFECTIVE_STATUS_SQL} AS membership_status

        FROM students s

        LEFT JOIN memberships m
            ON m.membership_id = (
                SELECT membership_id
                FROM memberships
                WHERE student_id = s.student_id
                ORDER BY membership_id DESC
                LIMIT 1
            )

        WHERE s.admin_id = ?
    """, (admin_id,))
    membership_by_student = {row["student_id"]: dict(row) for row in cursor.fetchall()}
    conn.close()

    for student in students:
        m = membership_by_student.get(student["student_id"], {})
        student["membership_id"] = m.get("membership_id")
        student["plan_name"] = m.get("plan_name")
        student["paid_amount"] = m.get("paid_amount")
        student["pending_amount"] = m.get("pending_amount")
        student["membership_status"] = m.get("membership_status")

    return render_template("students/index.html", students=students)


@student_bp.route("/admission/<int:enquiry_id>", methods=["GET", "POST"])
def admission(enquiry_id):

    if "admin_id" not in session:
        return redirect("/")

    admin_id = session["admin_id"]
    supabase = get_supabase_client()

    try:
        response = (
            supabase.table("enquiries")
            .select("*")
            .eq("enquiry_id", enquiry_id)
            .eq("admin_id", admin_id)
            .execute()
        )
        enquiry = response.data[0] if response.data else None
    except APIError:
        enquiry = None

    if enquiry is None:
        flash("Enquiry not found.", "danger")
        return redirect(url_for("enquiry.index"))

    if request.method == "POST":

        address = request.form.get("address", "").strip()
        id_proof = request.form.get("id_proof", "").strip()
        join_date = _sanitize_date(request.form.get("join_date"))

        # Check if this mobile already admitted under THIS admin
        try:
            existing_response = (
                supabase.table("students")
                .select("student_id")
                .eq("mobile", enquiry["mobile"])
                .eq("admin_id", admin_id)
                .execute()
            )
            existing = existing_response.data[0] if existing_response.data else None
        except APIError:
            existing = None

        if existing is not None:
            flash("This student has already been admitted.", "warning")
            return redirect(url_for("student.view", student_id=existing["student_id"]))

        # student_id is assigned explicitly, not left to Supabase's
        # auto-assigned identity value -- same reasoning as
        # routes/enquiries.py's add() (ADR-18): Supabase's identity
        # sequence was seeded once from a one-time data copy (ADR-15) and
        # trails SQLite's autoincrement counter, which has kept climbing
        # from ordinary (and test-suite) usage in every session since.
        # Assign one past SQLite's current max and insert that same value
        # into both.
        sqlite_conn = get_connection()
        next_id_row = sqlite_conn.execute(
            "SELECT MAX(student_id) AS m FROM students"
        ).fetchone()
        new_student_id = (next_id_row["m"] or 0) + 1

        student_row = {
            "student_id": new_student_id,
            "admin_id": admin_id,
            "enquiry_id": enquiry["enquiry_id"],
            "full_name": enquiry["full_name"],
            "mobile": enquiry["mobile"],
            "address": address,
            "id_proof": id_proof,
            "purpose": enquiry["purpose"],
            "shift": enquiry["preferred_shift"],
            "join_date": join_date,
            "status": "Active",
        }

        try:
            supabase.table("students").insert(student_row).execute()
        except APIError:
            sqlite_conn.close()
            flash("Something went wrong. Please try again.", "danger")
            return redirect(url_for("student.admission", enquiry_id=enquiry_id))

        # Bridge: routes/membership.py, routes/payment.py, and several
        # dashboard/report/notification queries still enforce a real
        # SQLite foreign key to students.student_id and JOIN it directly
        # (out of this session's scope). Mirror the new row into SQLite
        # too, under the same explicit student_id, until those modules are
        # migrated to Supabase.
        try:
            sqlite_conn.execute(
                """
                INSERT INTO students
                (student_id, admin_id, enquiry_id, full_name, mobile, address,
                 id_proof, purpose, shift, join_date, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_student_id,
                    admin_id,
                    enquiry["enquiry_id"],
                    enquiry["full_name"],
                    enquiry["mobile"],
                    address,
                    id_proof,
                    enquiry["purpose"],
                    enquiry["preferred_shift"],
                    join_date,
                    "Active"
                )
            )
            sqlite_conn.commit()
            sqlite_conn.close()
        except sqlite3.Error:
            supabase.table("students").delete().eq("student_id", new_student_id).execute()
            flash("Something went wrong. Please try again.", "danger")
            return redirect(url_for("student.admission", enquiry_id=enquiry_id))

        # Closes TD-36: this now flips enquiries.status in Supabase, the
        # copy routes/enquiries.py's index()/edit()/view() actually read --
        # previously this UPDATE only ever reached the SQLite mirror, so
        # the Enquiries pages never saw a just-admitted enquiry's status
        # change. Best-effort: the student is already admitted either way,
        # so a failure here shouldn't block the redirect to membership
        # creation.
        try:
            supabase.table("enquiries").update(
                {"status": "Admitted"}
            ).eq("enquiry_id", enquiry["enquiry_id"]).eq("admin_id", admin_id).execute()
        except APIError:
            pass

        flash("Student admitted successfully. Please create membership.", "success")
        return redirect(url_for("membership.create", student_id=new_student_id))

    return render_template("students/admission.html", enquiry=enquiry)


@student_bp.route("/view/<int:student_id>")
def view(student_id):

    if "admin_id" not in session:
        return redirect("/")

    admin_id = session["admin_id"]

    supabase = get_supabase_client()
    try:
        response = (
            supabase.table("students")
            .select("*")
            .eq("student_id", student_id)
            .eq("admin_id", admin_id)
            .execute()
        )
        student = response.data[0] if response.data else None
    except APIError:
        student = None

    if student is None:
        flash("Student not found.", "danger")
        return redirect(url_for("student.index"))

    # memberships/payments stay SQLite (out of this session's scope)
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM memberships
        WHERE student_id=?
        ORDER BY membership_id DESC
        LIMIT 1
    """, (student_id,))
    membership = cursor.fetchone()

    cursor.execute("""
        SELECT p.*
        FROM payments p
        INNER JOIN memberships m ON p.membership_id = m.membership_id
        WHERE m.student_id=?
        ORDER BY p.payment_id DESC
    """, (student_id,))
    payments = cursor.fetchall()

    conn.close()

    return render_template(
        "students/view.html",
        student=student,
        membership=membership,
        payments=payments
    )


@student_bp.route("/edit/<int:student_id>", methods=["GET", "POST"])
def edit(student_id):

    if "admin_id" not in session:
        return redirect("/")

    admin_id = session["admin_id"]
    supabase = get_supabase_client()

    try:
        response = (
            supabase.table("students")
            .select("*")
            .eq("student_id", student_id)
            .eq("admin_id", admin_id)
            .execute()
        )
        student = response.data[0] if response.data else None
    except APIError:
        student = None

    if student is None:
        flash("Student not found.", "danger")
        return redirect(url_for("student.index"))

    if request.method == "POST":

        full_name = request.form.get("full_name")
        mobile = request.form.get("mobile")
        address = request.form.get("address")
        purpose = request.form.get("purpose")
        shift = request.form.get("shift")
        status = request.form.get("status")

        # UNIQUE(mobile, admin_id) exists on both databases -- check for a
        # collision with another student of this admin before writing,
        # same check-first shape as routes/auth.py's register() existence
        # checks, since a Supabase unique-violation can't be told apart
        # from any other postgrest.exceptions.APIError without parsing
        # its error code.
        try:
            collision_response = (
                supabase.table("students")
                .select("student_id")
                .eq("mobile", mobile)
                .eq("admin_id", admin_id)
                .neq("student_id", student_id)
                .execute()
            )
            collision = collision_response.data[0] if collision_response.data else None
        except APIError:
            collision = None

        if collision is not None:
            flash(
                "Another student already uses that mobile number. "
                "Please use a different number.",
                "danger"
            )
            return render_template("students/edit.html", student=student)

        try:
            supabase.table("students").update({
                "full_name": full_name,
                "mobile": mobile,
                "address": address,
                "purpose": purpose,
                "shift": shift,
                "status": status,
            }).eq("student_id", student_id).eq("admin_id", admin_id).execute()
        except APIError:
            flash("Something went wrong. Please try again.", "danger")
            return render_template("students/edit.html", student=student)

        # Bridge: routes/membership.py, routes/payment.py, and several
        # dashboard/report/notification queries still read this student's
        # full_name/mobile/purpose/shift/status straight from the SQLite
        # mirror (out of this session's scope) -- keep it in sync the same
        # way routes/enquiries.py's edit() does.
        sqlite_conn = get_connection()
        sqlite_conn.execute("""
            UPDATE students
            SET full_name=?, mobile=?, address=?, purpose=?, shift=?, status=?
            WHERE student_id=? AND admin_id=?
        """, (full_name, mobile, address, purpose, shift, status, student_id, admin_id))
        sqlite_conn.commit()
        sqlite_conn.close()

        flash("Student updated successfully.", "success")
        return redirect(url_for("student.view", student_id=student_id))

    return render_template("students/edit.html", student=student)
