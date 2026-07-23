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
from postgrest.exceptions import APIError

from database.db import get_connection
from database.supabase_client import get_supabase_client
from database.payment_queries import record_payment
from database.membership_settings_queries import get_membership_settings
from database.membership_queries import (
    get_effective_status,
    get_active_membership,
    get_plan_pricing,
    get_admission_fee,
)

membership_bp = Blueprint(
    "membership",
    __name__,
    url_prefix="/memberships"
)


def _sanitize_int(value):
    """Return an int or None. Postgres's duration_days column is a
    strictly-typed INTEGER, unlike SQLite's, which silently accepted any
    string -- blank/unparsable input must become NULL instead of raising an
    APIError on insert (same helper shape as routes/student.py's
    _sanitize_date, ADR-19)."""
    if not value:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@membership_bp.route("/")
def index():

    if "admin_id" not in session:
        return redirect("/")

    admin_id = session["admin_id"]
    supabase = get_supabase_client()

    # students already lives in Supabase (routes/student.py, ADR-19) -
    # fetch this admin's students first so memberships can be scoped to
    # them in Python, the same shape routes/student.py's own index() uses
    # to merge in membership data from the other direction.
    try:
        students_response = (
            supabase.table("students")
            .select("student_id, full_name, mobile")
            .eq("admin_id", admin_id)
            .execute()
        )
        students_by_id = {s["student_id"]: s for s in students_response.data}
    except APIError:
        students_by_id = {}

    memberships_data = []
    if students_by_id:
        try:
            memberships_response = (
                supabase.table("memberships")
                .select("*")
                .in_("student_id", list(students_by_id.keys()))
                .order("membership_id", desc=True)
                .execute()
            )
            memberships_data = memberships_response.data
        except APIError:
            memberships_data = []

    memberships = []
    for m in memberships_data:
        student = students_by_id.get(m["student_id"], {})
        memberships.append({
            **m,
            "membership_status": get_effective_status(m["membership_status"], m["end_date"]),
            "full_name": student.get("full_name"),
            "mobile": student.get("mobile"),
        })

    return render_template("memberships/index.html", memberships=memberships)


@membership_bp.route("/create/<int:student_id>", methods=["GET", "POST"])
def create(student_id):

    if "admin_id" not in session:
        return redirect("/")

    admin_id = session["admin_id"]
    supabase = get_supabase_client()

    try:
        student_response = (
            supabase.table("students")
            .select("*")
            .eq("student_id", student_id)
            .eq("admin_id", admin_id)
            .execute()
        )
        student = student_response.data[0] if student_response.data else None
    except APIError:
        student = None

    if student is None:
        flash("Student not found.", "danger")
        return redirect(url_for("student.index"))

    # A student can only have one live membership at a time - Renewal is the
    # supported path once one exists (it explicitly expires the old row
    # before inserting the new one). Without this guard, navigating back to
    # this URL for a student who already has an active membership would
    # insert a second 'Active' row alongside it.
    existing_active = get_active_membership(student_id)
    if existing_active is not None:
        flash(
            "This student already has an active membership. Use Renew instead.",
            "warning"
        )
        return redirect(url_for("membership.renew", student_id=student_id))

    settings = get_membership_settings(admin_id)
    plan_pricing = get_plan_pricing(settings)
    admission_fee = get_admission_fee(settings)

    if request.method == "POST":

        plan_name = request.form.get("plan_name")
        joining_date = request.form.get("joining_date")
        duration_days = _sanitize_int(request.form.get("duration"))
        end_date = request.form.get("end_date")
        remarks = request.form.get("remarks")
        payment_mode = request.form.get("payment_mode", "Cash")

        try:
            paid_amount = float(request.form.get("paid_amount", 0) or 0)
            due_amount = float(request.form.get("due_amount", 0) or 0)
        except ValueError:
            flash("Invalid amount entered.", "danger")
            return render_template(
                "memberships/create.html", student=student,
                plan_pricing=plan_pricing, admission_fee=admission_fee
            )

        if paid_amount < 0 or due_amount < 0:
            flash("Paid and due amounts cannot be negative.", "danger")
            return render_template(
                "memberships/create.html", student=student,
                plan_pricing=plan_pricing, admission_fee=admission_fee
            )

        total_fee = paid_amount + due_amount

        if total_fee <= 0:
            flash("Total fee must be greater than zero.", "danger")
            return render_template(
                "memberships/create.html", student=student,
                plan_pricing=plan_pricing, admission_fee=admission_fee
            )

        # membership_id is assigned explicitly, not left to Supabase's
        # auto-assigned identity value -- same reasoning as
        # routes/enquiries.py's add() (ADR-18) and routes/student.py's
        # admission() (ADR-19): Supabase's identity sequence was seeded
        # once from a one-time data copy (ADR-15) and trails SQLite's
        # autoincrement counter, which has kept climbing from ordinary (and
        # test-suite) usage in every session since. Assign one past
        # SQLite's current max and insert that same value into both.
        sqlite_conn = get_connection()
        next_id_row = sqlite_conn.execute(
            "SELECT MAX(membership_id) AS m FROM memberships"
        ).fetchone()
        new_membership_id = (next_id_row["m"] or 0) + 1

        membership_row = {
            "membership_id": new_membership_id,
            "student_id": student_id,
            "plan_name": plan_name,
            "joining_date": joining_date,
            "duration_days": duration_days,
            "end_date": end_date,
            "total_fee": total_fee,
            "paid_amount": paid_amount,
            "pending_amount": due_amount,
            "remarks": remarks,
            "membership_status": "Active",
        }

        try:
            supabase.table("memberships").insert(membership_row).execute()
        except APIError:
            sqlite_conn.close()
            flash(
                "Could not create this membership due to a database error. "
                "Nothing was saved - please try again.",
                "danger"
            )
            return render_template(
                "memberships/create.html", student=student,
                plan_pricing=plan_pricing, admission_fee=admission_fee
            )

        # Bridge: routes/payment.py, routes/dashboard.py,
        # routes/membership_distribution.py, and routes/notification.py
        # still enforce a real SQLite foreign key to students.student_id
        # and JOIN memberships directly (out of this session's scope).
        # Mirror the new row into SQLite too, under the same explicit
        # membership_id, until those modules are migrated to Supabase.
        try:
            sqlite_conn.execute("""
                INSERT INTO memberships
                (membership_id, student_id, plan_name, joining_date, duration_days, end_date,
                 total_fee, paid_amount, pending_amount, remarks, membership_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                new_membership_id, student_id, plan_name, joining_date, duration_days, end_date,
                total_fee, paid_amount, due_amount, remarks, "Active"
            ))

            receipt_number = None

            if paid_amount > 0:
                receipt_number = record_payment(
                    sqlite_conn,
                    admin_id,
                    membership_id=new_membership_id,
                    student_id=student_id,
                    student_name=student["full_name"],
                    payment_mode=payment_mode,
                    amount=paid_amount,
                    remarks=remarks,
                    category="Admission Fee",
                    description=remarks or f"Admission payment - {plan_name}",
                    source="Admission"
                )

            sqlite_conn.commit()
            sqlite_conn.close()
        except sqlite3.Error:
            sqlite_conn.rollback()
            sqlite_conn.close()
            supabase.table("memberships").delete().eq("membership_id", new_membership_id).execute()
            flash(
                "Could not create this membership due to a database error. "
                "Nothing was saved - please try again.",
                "danger"
            )
            return render_template(
                "memberships/create.html", student=student,
                plan_pricing=plan_pricing, admission_fee=admission_fee
            )

        if receipt_number:
            flash(
                f"Membership created successfully. Receipt No: {receipt_number}",
                "success"
            )
        else:
            flash("Membership created successfully.", "success")
        return redirect(url_for("student.view", student_id=student_id))

    return render_template(
        "memberships/create.html", student=student,
        plan_pricing=plan_pricing, admission_fee=admission_fee
    )


@membership_bp.route("/renew/<int:student_id>", methods=["GET", "POST"])
def renew(student_id):

    if "admin_id" not in session:
        return redirect("/")

    admin_id = session["admin_id"]
    supabase = get_supabase_client()

    try:
        student_response = (
            supabase.table("students")
            .select("*")
            .eq("student_id", student_id)
            .eq("admin_id", admin_id)
            .execute()
        )
        student = student_response.data[0] if student_response.data else None
    except APIError:
        student = None

    if student is None:
        flash("Student not found.", "danger")
        return redirect(url_for("student.index"))

    # Guard: must have at least one existing membership to renew
    try:
        existing_response = (
            supabase.table("memberships")
            .select("membership_id")
            .eq("student_id", student_id)
            .limit(1)
            .execute()
        )
        has_existing = bool(existing_response.data)
    except APIError:
        has_existing = False

    if not has_existing:
        flash("No existing membership found. Please create a membership first.", "warning")
        return redirect(url_for("membership.create", student_id=student_id))

    settings = get_membership_settings(admin_id)
    plan_pricing = get_plan_pricing(settings)

    if request.method == "POST":

        plan_name = request.form.get("plan_name")
        joining_date = request.form.get("joining_date")
        duration_days = _sanitize_int(request.form.get("duration_days"))
        end_date = request.form.get("end_date")
        remarks = request.form.get("remarks")
        payment_mode = request.form.get("payment_mode", "Cash")

        try:
            paid_amount = float(request.form.get("paid_amount", 0) or 0)
            due_amount = float(request.form.get("due_amount", 0) or 0)
        except ValueError:
            flash("Invalid amount entered.", "danger")
            return render_template(
                "memberships/renew.html", student=student, plan_pricing=plan_pricing
            )

        if paid_amount < 0 or due_amount < 0:
            flash("Paid and due amounts cannot be negative.", "danger")
            return render_template(
                "memberships/renew.html", student=student, plan_pricing=plan_pricing
            )

        total_fee = paid_amount + due_amount

        if total_fee <= 0:
            flash("Total fee must be greater than zero.", "danger")
            return render_template(
                "memberships/renew.html", student=student, plan_pricing=plan_pricing
            )

        # Same explicit-id bridging as create() above (ADR-18/ADR-19/ADR-20).
        sqlite_conn = get_connection()
        next_id_row = sqlite_conn.execute(
            "SELECT MAX(membership_id) AS m FROM memberships"
        ).fetchone()
        new_membership_id = (next_id_row["m"] or 0) + 1

        # Capture which rows this expires so a failure partway through this
        # request (either DB) can be rolled back without guessing which
        # rows were live beforehand.
        try:
            previously_active_response = (
                supabase.table("memberships")
                .select("membership_id")
                .eq("student_id", student_id)
                .eq("membership_status", "Active")
                .execute()
            )
            previously_active_ids = [
                row["membership_id"] for row in previously_active_response.data
            ]
        except APIError:
            previously_active_ids = []

        membership_row = {
            "membership_id": new_membership_id,
            "student_id": student_id,
            "plan_name": plan_name,
            "joining_date": joining_date,
            "duration_days": duration_days,
            "end_date": end_date,
            "total_fee": total_fee,
            "paid_amount": paid_amount,
            "pending_amount": due_amount,
            "remarks": remarks,
            "membership_status": "Active",
        }

        try:
            if previously_active_ids:
                supabase.table("memberships").update(
                    {"membership_status": "Expired"}
                ).eq("student_id", student_id).eq("membership_status", "Active").execute()

            supabase.table("memberships").insert(membership_row).execute()
        except APIError:
            if previously_active_ids:
                supabase.table("memberships").update(
                    {"membership_status": "Active"}
                ).in_("membership_id", previously_active_ids).execute()
            sqlite_conn.close()
            flash(
                "Could not renew this membership due to a database error. "
                "Nothing was saved - please try again.",
                "danger"
            )
            return render_template(
                "memberships/renew.html", student=student, plan_pricing=plan_pricing
            )

        # Bridge: same as create() above - mirror both writes into SQLite
        # for routes/payment.py, routes/dashboard.py,
        # routes/membership_distribution.py, and routes/notification.py.
        try:
            sqlite_conn.execute("""
                UPDATE memberships
                SET membership_status = 'Expired'
                WHERE student_id=? AND membership_status = 'Active'
            """, (student_id,))

            sqlite_conn.execute("""
                INSERT INTO memberships
                (membership_id, student_id, plan_name, joining_date, duration_days, end_date,
                 total_fee, paid_amount, pending_amount, remarks, membership_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                new_membership_id, student_id, plan_name, joining_date, duration_days, end_date,
                total_fee, paid_amount, due_amount, remarks, "Active"
            ))

            receipt_number = None

            if paid_amount > 0:
                receipt_number = record_payment(
                    sqlite_conn,
                    admin_id,
                    membership_id=new_membership_id,
                    student_id=student_id,
                    student_name=student["full_name"],
                    payment_mode=payment_mode,
                    amount=paid_amount,
                    remarks=remarks,
                    category="Membership Renewal",
                    description=remarks or f"Membership renewal - {plan_name}",
                    source="Renewal"
                )

            sqlite_conn.commit()
            sqlite_conn.close()
        except sqlite3.Error:
            sqlite_conn.rollback()
            sqlite_conn.close()
            supabase.table("memberships").delete().eq("membership_id", new_membership_id).execute()
            if previously_active_ids:
                supabase.table("memberships").update(
                    {"membership_status": "Active"}
                ).in_("membership_id", previously_active_ids).execute()
            flash(
                "Could not renew this membership due to a database error. "
                "Nothing was saved - please try again.",
                "danger"
            )
            return render_template(
                "memberships/renew.html", student=student, plan_pricing=plan_pricing
            )

        if receipt_number:
            flash(
                f"Membership renewed successfully. Receipt No: {receipt_number}",
                "success"
            )
        else:
            flash("Membership renewed successfully.", "success")
        return redirect(url_for("student.view", student_id=student_id))

    return render_template(
        "memberships/renew.html", student=student, plan_pricing=plan_pricing
    )
