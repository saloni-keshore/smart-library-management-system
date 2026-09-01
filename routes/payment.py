import secrets
from datetime import datetime

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

from database.supabase_client import get_supabase_client
from database.payment_queries import (
    record_payment,
    get_payments_for_admin,
    get_payment_id_by_receipt_number,
    find_payment_by_idempotency_key,
)
from database.membership_queries import (
    promote_student_if_fully_paid,
    split_admission_and_membership_fee,
)
from database.receipt_settings_queries import get_receipt_settings
from utils.normalization import normalize_free_text


payment_bp = Blueprint(
    "payment",
    __name__,
    url_prefix="/payments"
)


def _fmt_receipt_date(value):
    """Format a stored ISO date ("YYYY-MM-DD") as "01 Jan 2026" for the receipt.

    Mirrors the inline formatting already used for the payment date; returns the
    raw value (or None) untouched if it can't be parsed.
    """
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%d %b %Y")
    except (ValueError, TypeError):
        return value or None


def _plan_label(membership):
    """Human-readable plan for the receipt's "Membership" line.

    Preset plans keep their stored name (MONTHLY/QUARTERLY/...). A Custom plan is
    stored as the bare string "CUSTOM", which tells the reader nothing about the
    term bought, so surface its day count instead (e.g. "Custom - 45 days").
    """
    if not membership:
        return "-"

    plan_name = membership.get("plan_name") or "-"

    if plan_name == "CUSTOM":
        days = membership.get("duration_days")
        if days:
            return f"Custom - {days} day" + ("s" if days != 1 else "")
        return "Custom"

    return plan_name


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

        # Idempotency (TD-30, ADR-53): the hidden token this form's GET
        # render embedded. A double-click/back-button resubmit posts the
        # same token twice - short-circuit here, before touching the
        # membership balance, instead of decrementing pending_amount twice
        # for what was really one payment.
        idempotency_key = request.form.get("idempotency_key") or None
        if idempotency_key:
            existing_payment = find_payment_by_idempotency_key(idempotency_key)
            if existing_payment is not None:
                flash(
                    f"This payment was already recorded. Receipt No: "
                    f"{existing_payment['receipt_number']}",
                    "info"
                )
                return redirect(url_for("payment.receipt", payment_id=existing_payment["payment_id"]))

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
                student=student,
                idempotency_key=secrets.token_urlsafe(24)
            )

        if amount <= 0:
            flash("Amount must be greater than zero.", "danger")
            return render_template(
                "payments/collect.html",
                membership=membership,
                student=student,
                idempotency_key=secrets.token_urlsafe(24)
            )

        if amount > pending:
            flash(
                f"Amount cannot exceed pending balance of ₹{pending:.0f}.",
                "danger"
            )
            return render_template(
                "payments/collect.html",
                membership=membership,
                student=student,
                idempotency_key=secrets.token_urlsafe(24)
            )

        payment_mode = request.form.get("payment_mode")
        remarks = normalize_free_text(request.form.get("remarks"))

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
                student=student,
                idempotency_key=secrets.token_urlsafe(24)
            )

        # Admission-fee-first waterfall (ADR-62): whatever of this
        # membership's admission_fee_amount isn't covered by old_paid yet
        # comes out of this payment first; the rest is Membership Fee. A
        # membership created before this feature (or with no configured
        # admission fee / Custom plan) has admission_fee_amount 0, so this
        # collapses to today's single "Membership Fee" behavior.
        admission_fee_amount = membership.get("admission_fee_amount") or 0
        admission_share, membership_share = split_admission_and_membership_fee(
            admission_fee_amount, old_paid=old_paid, amount=amount
        )

        try:
            receipt_number = record_payment(
                admin_id,
                membership_id=membership_id,
                student_id=student["student_id"],
                student_name=student["full_name"],
                payment_mode=payment_mode,
                amount=amount,
                remarks=remarks,
                category=[
                    ("Admission Fee", admission_share),
                    ("Membership Fee", membership_share),
                ],
                description=remarks or f"Pending fee payment - {membership['plan_name']}",
                source="Payments",
                idempotency_key=idempotency_key
            )
        except APIError:
            # Restore Supabase to its pre-payment values so the source of
            # truth doesn't advance ahead of a failed payment write - same
            # revert shape as before ADR-29 removed the SQLite mirror.
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
                student=student,
                idempotency_key=secrets.token_urlsafe(24)
            )

        # If this payment clears the balance, a still-provisional student
        # (admitted but never fully paid) becomes 'Active' - the same
        # promotion membership.create() does at the front of this flow.
        # Best-effort; the payment itself has already succeeded.
        if new_pending == 0:
            promote_student_if_fully_paid(supabase, student["student_id"])

        flash(
            f"Payment of ₹{amount:.0f} collected successfully. Receipt No: {receipt_number}",
            "success"
        )
        payment_id = get_payment_id_by_receipt_number(receipt_number)
        if payment_id:
            return redirect(url_for("payment.receipt", payment_id=payment_id))
        return redirect(url_for("student.view", student_id=student["student_id"]))

    return render_template(
        "payments/collect.html",
        membership=membership,
        student=student,
        idempotency_key=secrets.token_urlsafe(24)
    )


@payment_bp.route("/receipt/<int:payment_id>")
def receipt(payment_id):

    if "admin_id" not in session:
        return redirect("/")

    admin_id = session["admin_id"]
    supabase = get_supabase_client()

    try:
        payment_response = (
            supabase.table("payments")
            .select("*")
            .eq("payment_id", payment_id)
            .execute()
        )
        payment = payment_response.data[0] if payment_response.data else None
    except APIError:
        payment = None

    if payment is None:
        flash("Receipt not found.", "danger")
        return redirect(url_for("student.index"))

    # Admin-scope the receipt through student ownership, same pattern as
    # collect() above - payments has no admin_id column of its own.
    try:
        student_response = (
            supabase.table("students")
            .select("*")
            .eq("student_id", payment["student_id"])
            .eq("admin_id", admin_id)
            .execute()
        )
        student = student_response.data[0] if student_response.data else None
    except APIError:
        student = None

    if student is None:
        flash("Receipt not found.", "danger")
        return redirect(url_for("student.index"))

    membership = None
    if payment.get("membership_id"):
        try:
            membership_response = (
                supabase.table("memberships")
                .select("*")
                .eq("membership_id", payment["membership_id"])
                .execute()
            )
            membership = membership_response.data[0] if membership_response.data else None
        except APIError:
            membership = None

    settings = get_receipt_settings(admin_id)

    if membership:
        joining_date_display = _fmt_receipt_date(membership.get("joining_date"))
        expiry_date_display = _fmt_receipt_date(membership.get("end_date"))
    else:
        # Payment not tied to a membership - fall back to the payment date and
        # hide the expiry row.
        joining_date_display = _fmt_receipt_date(payment["payment_date"])
        expiry_date_display = None

    issued_date_display = datetime.now().strftime("%d %b %Y")
    plan_display = _plan_label(membership)

    return render_template(
        "payments/receipt.html",
        payment=payment,
        student=student,
        membership=membership,
        settings=settings,
        joining_date_display=joining_date_display,
        expiry_date_display=expiry_date_display,
        issued_date_display=issued_date_display,
        plan_display=plan_display
    )
