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
from database.membership_settings_queries import get_membership_settings
from database.membership_queries import (
    EFFECTIVE_STATUS_SQL,
    get_active_membership,
    get_plan_pricing,
    get_admission_fee,
)

membership_bp = Blueprint(
    "membership",
    __name__,
    url_prefix="/memberships"
)


@membership_bp.route("/")
def index():

    if "admin_id" not in session:
        return redirect("/")

    admin_id = session["admin_id"]

    conn = get_connection()
    cursor = conn.cursor()

    # Effective-status column listed before `m.*` deliberately - sqlite3.Row
    # resolves duplicate column names (both called membership_status) to
    # whichever appears first in the SELECT list, so this order is what
    # makes the computed value win over the raw, possibly-stale column.
    cursor.execute(f"""
        SELECT {EFFECTIVE_STATUS_SQL} AS membership_status,
               m.*, s.full_name, s.mobile
        FROM memberships m
        INNER JOIN students s ON m.student_id = s.student_id
        WHERE s.admin_id = ?
        ORDER BY m.membership_id DESC
    """, (admin_id,))

    memberships = cursor.fetchall()
    conn.close()

    return render_template("memberships/index.html", memberships=memberships)


@membership_bp.route("/create/<int:student_id>", methods=["GET", "POST"])
def create(student_id):

    if "admin_id" not in session:
        return redirect("/")

    admin_id = session["admin_id"]

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM students WHERE student_id=? AND admin_id=?",
        (student_id, admin_id)
    )
    student = cursor.fetchone()

    if student is None:
        conn.close()
        flash("Student not found.", "danger")
        return redirect(url_for("student.index"))

    # A student can only have one live membership at a time - Renewal is the
    # supported path once one exists (it explicitly expires the old row
    # before inserting the new one). Without this guard, navigating back to
    # this URL for a student who already has an active membership would
    # insert a second 'Active' row alongside it.
    existing_active = get_active_membership(student_id)
    if existing_active is not None:
        conn.close()
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
            return render_template(
                "memberships/create.html", student=student,
                plan_pricing=plan_pricing, admission_fee=admission_fee
            )

        if paid_amount < 0 or due_amount < 0:
            flash("Paid and due amounts cannot be negative.", "danger")
            conn.close()
            return render_template(
                "memberships/create.html", student=student,
                plan_pricing=plan_pricing, admission_fee=admission_fee
            )

        total_fee = paid_amount + due_amount

        if total_fee <= 0:
            flash("Total fee must be greater than zero.", "danger")
            conn.close()
            return render_template(
                "memberships/create.html", student=student,
                plan_pricing=plan_pricing, admission_fee=admission_fee
            )

        try:
            cursor.execute("""
                INSERT INTO memberships
                (student_id, plan_name, joining_date, duration_days, end_date,
                 total_fee, paid_amount, pending_amount, remarks, membership_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                student_id, plan_name, joining_date, duration_days, end_date,
                total_fee, paid_amount, due_amount, remarks, "Active"
            ))

            membership_id = cursor.lastrowid
            receipt_number = None

            if paid_amount > 0:
                receipt_number = record_payment(
                    conn,
                    admin_id,
                    membership_id=membership_id,
                    student_id=student_id,
                    student_name=student["full_name"],
                    payment_mode=payment_mode,
                    amount=paid_amount,
                    remarks=remarks,
                    category="Admission Fee",
                    description=remarks or f"Admission payment - {plan_name}",
                    source="Admission"
                )

            conn.commit()
        except sqlite3.Error:
            conn.rollback()
            flash(
                "Could not create this membership due to a database error. "
                "Nothing was saved - please try again.",
                "danger"
            )
            conn.close()
            return render_template(
                "memberships/create.html", student=student,
                plan_pricing=plan_pricing, admission_fee=admission_fee
            )

        conn.close()

        if receipt_number:
            flash(
                f"Membership created successfully. Receipt No: {receipt_number}",
                "success"
            )
        else:
            flash("Membership created successfully.", "success")
        return redirect(url_for("student.view", student_id=student_id))

    conn.close()
    return render_template(
        "memberships/create.html", student=student,
        plan_pricing=plan_pricing, admission_fee=admission_fee
    )


@membership_bp.route("/renew/<int:student_id>", methods=["GET", "POST"])
def renew(student_id):

    if "admin_id" not in session:
        return redirect("/")

    admin_id = session["admin_id"]

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM students WHERE student_id=? AND admin_id=?",
        (student_id, admin_id)
    )
    student = cursor.fetchone()

    if student is None:
        conn.close()
        flash("Student not found.", "danger")
        return redirect(url_for("student.index"))

    # Guard: must have at least one existing membership to renew
    cursor.execute(
        "SELECT membership_id FROM memberships WHERE student_id=? LIMIT 1",
        (student_id,)
    )
    if cursor.fetchone() is None:
        conn.close()
        flash("No existing membership found. Please create a membership first.", "warning")
        return redirect(url_for("membership.create", student_id=student_id))

    settings = get_membership_settings(admin_id)
    plan_pricing = get_plan_pricing(settings)

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
            return render_template(
                "memberships/renew.html", student=student, plan_pricing=plan_pricing
            )

        if paid_amount < 0 or due_amount < 0:
            flash("Paid and due amounts cannot be negative.", "danger")
            conn.close()
            return render_template(
                "memberships/renew.html", student=student, plan_pricing=plan_pricing
            )

        total_fee = paid_amount + due_amount

        if total_fee <= 0:
            flash("Total fee must be greater than zero.", "danger")
            conn.close()
            return render_template(
                "memberships/renew.html", student=student, plan_pricing=plan_pricing
            )

        try:
            # Mark previous active membership as Expired
            cursor.execute("""
                UPDATE memberships
                SET membership_status = 'Expired'
                WHERE student_id=? AND membership_status = 'Active'
            """, (student_id,))

            cursor.execute("""
                INSERT INTO memberships
                (student_id, plan_name, joining_date, duration_days, end_date,
                 total_fee, paid_amount, pending_amount, remarks, membership_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                student_id, plan_name, joining_date, duration_days, end_date,
                total_fee, paid_amount, due_amount, remarks, "Active"
            ))

            membership_id = cursor.lastrowid
            receipt_number = None

            if paid_amount > 0:
                receipt_number = record_payment(
                    conn,
                    admin_id,
                    membership_id=membership_id,
                    student_id=student_id,
                    student_name=student["full_name"],
                    payment_mode=payment_mode,
                    amount=paid_amount,
                    remarks=remarks,
                    category="Membership Renewal",
                    description=remarks or f"Membership renewal - {plan_name}",
                    source="Renewal"
                )

            conn.commit()
        except sqlite3.Error:
            conn.rollback()
            flash(
                "Could not renew this membership due to a database error. "
                "Nothing was saved - please try again.",
                "danger"
            )
            conn.close()
            return render_template(
                "memberships/renew.html", student=student, plan_pricing=plan_pricing
            )

        conn.close()

        if receipt_number:
            flash(
                f"Membership renewed successfully. Receipt No: {receipt_number}",
                "success"
            )
        else:
            flash("Membership renewed successfully.", "success")
        return redirect(url_for("student.view", student_id=student_id))

    conn.close()
    return render_template(
        "memberships/renew.html", student=student, plan_pricing=plan_pricing
    )
