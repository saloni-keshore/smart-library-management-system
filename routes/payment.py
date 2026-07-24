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
from database.payment_queries import record_payment, get_payments_for_admin


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

    # Supabase `payments`/`students` (ADR-25) instead of the SQLite mirror.
    payments = sorted(
        get_payments_for_admin(admin_id),
        key=lambda p: p["payment_id"],
        reverse=True
    )

    return render_template("payments/index.html", payments=payments)


@payment_bp.route("/collect/<int:membership_id>", methods=["GET", "POST"])
def collect(membership_id):

    if "admin_id" not in session:
        return redirect("/")

    admin_id = session["admin_id"]
    supabase = get_supabase_client()

    # memberships lives in Supabase (routes/membership.py, ADR-20) - read it
    # from there, the source of truth, instead of the SQLite mirror.
    try:
        membership_response = (
            supabase.table("memberships")
            .select("*")
            .eq("membership_id", membership_id)
            .execute()
        )
        membership = membership_response.data[0] if membership_response.data else None
    except APIError:
        membership = None

    if membership is None:
        flash("Membership not found.", "danger")
        return redirect(url_for("student.index"))

    # Verify membership belongs to this admin via student ownership -
    # students also lives in Supabase (routes/student.py, ADR-19).
    try:
        student_response = (
            supabase.table("students")
            .select("*")
            .eq("student_id", membership["student_id"])
            .eq("admin_id", admin_id)
            .execute()
        )
        student = student_response.data[0] if student_response.data else None
    except APIError:
        student = None

    if student is None:
        flash("Membership not found.", "danger")
        return redirect(url_for("student.index"))

    pending = float(membership["pending_amount"])

    if request.method == "POST":

        if pending <= 0:
            flash("This membership has no pending balance to collect.", "warning")
            return redirect(url_for("student.view", student_id=student["student_id"]))

        amount_str = request.form.get("amount_paid", "0")

        try:
            amount = float(amount_str)
        except ValueError:
            flash("Invalid amount entered.", "danger")
            return render_template(
                "payments/collect.html",
                membership=membership,
                student=student
            )

        if amount <= 0:
            flash("Amount must be greater than zero.", "danger")
            return render_template(
                "payments/collect.html",
                membership=membership,
                student=student
            )

        if amount > pending:
            flash(
                f"Amount cannot exceed pending balance of ₹{pending:.0f}.",
                "danger"
            )
            return render_template(
                "payments/collect.html",
                membership=membership,
                student=student
            )

        payment_mode = request.form.get("payment_mode")
        remarks = request.form.get("remarks")

        old_paid = float(membership["paid_amount"])
        new_paid = old_paid + amount
        new_pending = pending - amount

        # Primary write: memberships.paid_amount/pending_amount in Supabase,
        # the source of truth routes/membership.py's index() reads (closes
        # TD-37 - this was previously SQLite-only, going stale on Supabase).
        try:
            supabase.table("memberships").update(
                {"paid_amount": new_paid, "pending_amount": new_pending}
            ).eq("membership_id", membership_id).execute()
        except APIError:
            flash(
                "Could not record this payment due to a database error. "
                "Nothing was saved - please try again.",
                "danger"
            )
            return render_template(
                "payments/collect.html",
                membership=membership,
                student=student
            )

        # Bridge: this mirror has zero remaining readers as of ADR-25 (every
        # consumer that used to JOIN memberships directly against SQLite has
        # migrated to Supabase). As of 2026-07-24 (ADR-28), record_payment()
        # below no longer writes SQLite payments at all either, so nothing
        # in the SQLite FK graph still requires this memberships row to
        # exist for a write to succeed - memberships is now a removal
        # candidate itself, pending Phase 10's next removal call. See
        # docs/MIRROR_TRACKER.md.
        conn = get_connection()
        try:
            conn.execute("""
                UPDATE memberships
                SET paid_amount=?, pending_amount=?
                WHERE membership_id=?
            """, (new_paid, new_pending, membership_id))

            receipt_number = record_payment(
                admin_id,
                membership_id=membership_id,
                student_id=student["student_id"],
                student_name=student["full_name"],
                payment_mode=payment_mode,
                amount=amount,
                remarks=remarks,
                category="Membership Fee",
                description=remarks or f"Pending fee payment - {membership['plan_name']}",
                source="Payments"
            )

            conn.commit()
        except (sqlite3.Error, APIError):
            # As of 2026-07-24 (ADR-28), record_payment() writes only
            # Supabase and raises APIError (not sqlite3.Error) on failure -
            # caught here alongside sqlite3.Error so a payments failure
            # still rolls back the SQLite memberships mirror and reverts
            # Supabase exactly as before.
            conn.rollback()
            # Restore Supabase to its pre-payment values so the source of
            # truth doesn't advance ahead of a rolled-back SQLite write.
            supabase.table("memberships").update(
                {"paid_amount": old_paid, "pending_amount": pending}
            ).eq("membership_id", membership_id).execute()
            flash(
                "Could not record this payment due to a database error. "
                "Nothing was saved - please try again.",
                "danger"
            )
            return render_template(
                "payments/collect.html",
                membership=membership,
                student=student
            )
        finally:
            conn.close()

        flash(
            f"Payment of ₹{amount:.0f} collected successfully. Receipt No: {receipt_number}",
            "success"
        )
        return redirect(url_for("student.view", student_id=student["student_id"]))

    return render_template(
        "payments/collect.html",
        membership=membership,
        student=student
    )
