import secrets

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
from database.payment_queries import record_payment, get_payment_id_by_receipt_number
from database.membership_settings_queries import get_membership_settings
from database.membership_queries import (
    get_effective_status,
    get_active_membership,
    get_plan_pricing,
    get_admission_fee,
    insert_membership,
    find_membership_by_idempotency_key,
    promote_student_if_fully_paid,
    split_admission_and_membership_fee,
    DiscountColumnsUnavailable,
    AdmissionFeeColumnUnavailable,
)
from utils.normalization import normalize_category, normalize_free_text

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

        # Idempotency (TD-30, ADR-53): the hidden token this form's GET
        # render embedded (see the render_template call below). A
        # double-click/back-button resubmit posts the same token twice -
        # short-circuit here, before touching anything, instead of letting
        # a second identical membership get created.
        idempotency_key = request.form.get("idempotency_key") or None
        if idempotency_key:
            existing_membership = find_membership_by_idempotency_key(idempotency_key)
            if existing_membership is not None:
                flash("This membership was already created.", "info")
                return redirect(url_for("student.view", student_id=student_id))

        plan_name = normalize_category(request.form.get("plan_name"))
        joining_date = request.form.get("joining_date")
        duration_days = _sanitize_int(request.form.get("duration"))
        end_date = request.form.get("end_date")
        remarks = normalize_free_text(request.form.get("remarks"))
        payment_mode = request.form.get("payment_mode", "Cash")

        if not plan_name:
            flash("Membership plan is required.", "danger")
            return render_template(
                "memberships/create.html", student=student,
                plan_pricing=plan_pricing, admission_fee=admission_fee,
                idempotency_key=secrets.token_urlsafe(24)
            )

        if not (joining_date or "").strip():
            flash("Joining date is required.", "danger")
            return render_template(
                "memberships/create.html", student=student,
                plan_pricing=plan_pricing, admission_fee=admission_fee,
                idempotency_key=secrets.token_urlsafe(24)
            )

        # Pricing lookup must use the raw, pre-normalization plan value --
        # normalize_category() below uppercases plan_name for storage, but
        # plan_pricing/admission_fee are keyed by the Title-Case names shown
        # on the form ("Monthly", "Quarterly", ...).
        raw_plan = request.form.get("plan_name")

        try:
            paid_amount = float(request.form.get("paid_amount", 0) or 0)
        except ValueError:
            flash("Invalid amount entered.", "danger")
            return render_template(
                "memberships/create.html", student=student,
                plan_pricing=plan_pricing, admission_fee=admission_fee,
                idempotency_key=secrets.token_urlsafe(24)
            )

        if paid_amount < 0:
            flash("Paid amount cannot be negative.", "danger")
            return render_template(
                "memberships/create.html", student=student,
                plan_pricing=plan_pricing, admission_fee=admission_fee,
                idempotency_key=secrets.token_urlsafe(24)
            )

        # admission_fee_amount is this membership's own snapshot of the
        # admission fee actually folded into its total_fee (ADR-62) - 0 for
        # Custom (see the comment below), the current Settings value for a
        # standard plan, capped after discount below. Persisted on the row
        # (not re-read from live Settings later) so a future Settings change
        # can never retroactively re-categorize this membership's payments -
        # database/membership_queries.py's split_admission_and_membership_fee()
        # is what actually uses it, from both this route and payment.collect().
        admission_fee_amount = 0

        # Total Payable is never taken from client input for standard plans
        # -- it is derived from the admin-configured plan fee + admission
        # fee (a one-time new-admission charge) so it can never drift from
        # what Settings > Membership Settings says. Only "Custom" has no
        # configured price, so it alone accepts a manually-entered total --
        # and that entered value already represents the complete payable
        # amount (including any admission charge the operator has folded
        # in), so admission_fee is not added a second time for Custom.
        if raw_plan == "Custom":
            try:
                total_fee = float(request.form.get("total_fee", 0) or 0)
            except ValueError:
                flash("Invalid Total Payable entered.", "danger")
                return render_template(
                    "memberships/create.html", student=student,
                    plan_pricing=plan_pricing, admission_fee=admission_fee,
                    idempotency_key=secrets.token_urlsafe(24)
                )
            if total_fee < 0:
                flash("Total Payable cannot be negative.", "danger")
                return render_template(
                    "memberships/create.html", student=student,
                    plan_pricing=plan_pricing, admission_fee=admission_fee,
                    idempotency_key=secrets.token_urlsafe(24)
                )
        elif raw_plan in plan_pricing:
            total_fee = plan_pricing[raw_plan]["fee"] + admission_fee
            admission_fee_amount = admission_fee
        else:
            flash("Membership plan is required.", "danger")
            return render_template(
                "memberships/create.html", student=student,
                plan_pricing=plan_pricing, admission_fee=admission_fee,
                idempotency_key=secrets.token_urlsafe(24)
            )

        if total_fee <= 0:
            flash("Total Payable must be greater than zero.", "danger")
            return render_template(
                "memberships/create.html", student=student,
                plan_pricing=plan_pricing, admission_fee=admission_fee,
                idempotency_key=secrets.token_urlsafe(24)
            )

        # Discount is a separate, staff-entered line item on top of Total
        # Payable, never folded silently into it (ADR-46, same transparency
        # principle as Plan Fee/Admission Fee not being merged into Paid).
        # Final Payable = Total Payable - Discount.
        try:
            discount_amount = float(request.form.get("discount_amount", 0) or 0)
        except ValueError:
            flash("Invalid discount entered.", "danger")
            return render_template(
                "memberships/create.html", student=student,
                plan_pricing=plan_pricing, admission_fee=admission_fee,
                idempotency_key=secrets.token_urlsafe(24)
            )
        discount_reason = normalize_free_text(request.form.get("discount_reason", ""))

        if discount_amount < 0:
            flash("Discount cannot be negative.", "danger")
            return render_template(
                "memberships/create.html", student=student,
                plan_pricing=plan_pricing, admission_fee=admission_fee,
                idempotency_key=secrets.token_urlsafe(24)
            )

        if discount_amount >= total_fee:
            flash("Discount cannot be greater than or equal to Total Payable.", "danger")
            return render_template(
                "memberships/create.html", student=student,
                plan_pricing=plan_pricing, admission_fee=admission_fee,
                idempotency_key=secrets.token_urlsafe(24)
            )

        total_fee = total_fee - discount_amount

        # A discount large enough to undercut the configured admission fee
        # itself must not let the split later attribute more to "Admission
        # Fee" than the student actually ends up owing in total.
        admission_fee_amount = min(admission_fee_amount, total_fee)

        if paid_amount > total_fee:
            flash("Paid cannot exceed Final Payable.", "danger")
            return render_template(
                "memberships/create.html", student=student,
                plan_pricing=plan_pricing, admission_fee=admission_fee,
                idempotency_key=secrets.token_urlsafe(24)
            )

        pending_amount = total_fee - paid_amount

        # membership_id is assigned explicitly, not left to Supabase's
        # auto-assigned identity value -- same reasoning as
        # routes/enquiries.py's add() (ADR-18) and routes/student.py's
        # admission() (ADR-19): Supabase's identity sequence was seeded
        # once from a one-time data copy (ADR-15) and trails ordinary
        # usage. As of 2026-07-24 (ADR-29), computed from Supabase's own
        # MAX(membership_id) - the SQLite mirror this used to read is gone.
        next_id_response = (
            supabase.table("memberships")
            .select("membership_id")
            .order("membership_id", desc=True)
            .limit(1)
            .execute()
        )
        new_membership_id = (
            next_id_response.data[0]["membership_id"] + 1
            if next_id_response.data else 1
        )

        membership_row = {
            "membership_id": new_membership_id,
            "student_id": student_id,
            "plan_name": plan_name,
            "joining_date": joining_date,
            "duration_days": duration_days,
            "end_date": end_date,
            "total_fee": total_fee,
            "paid_amount": paid_amount,
            "pending_amount": pending_amount,
            "discount_amount": discount_amount,
            "discount_reason": discount_reason or None,
            "admission_fee_amount": admission_fee_amount,
            "remarks": remarks,
            "membership_status": "Active",
            "idempotency_key": idempotency_key,
        }

        try:
            existing_membership = insert_membership(supabase, membership_row)
        except DiscountColumnsUnavailable:
            flash(
                "Discounts aren't available yet on this system - the database "
                "needs a one-time update. Contact your administrator, or "
                "create this membership without a discount.",
                "danger"
            )
            return render_template(
                "memberships/create.html", student=student,
                plan_pricing=plan_pricing, admission_fee=admission_fee,
                idempotency_key=secrets.token_urlsafe(24)
            )
        except AdmissionFeeColumnUnavailable:
            flash(
                "Admission fee tracking isn't available yet on this system - "
                "the database needs a one-time update. Contact your "
                "administrator, or set Admission Fee to ₹0 in Settings > "
                "Membership Settings for now.",
                "danger"
            )
            return render_template(
                "memberships/create.html", student=student,
                plan_pricing=plan_pricing, admission_fee=admission_fee,
                idempotency_key=secrets.token_urlsafe(24)
            )
        except APIError:
            flash(
                "Could not create this membership due to a database error. "
                "Nothing was saved - please try again.",
                "danger"
            )
            return render_template(
                "memberships/create.html", student=student,
                plan_pricing=plan_pricing, admission_fee=admission_fee,
                idempotency_key=secrets.token_urlsafe(24)
            )

        if existing_membership is not None:
            # Lost a race to an earlier, identical submission that already
            # created this membership (TD-30, ADR-53) - not an error.
            flash("This membership was already created.", "info")
            return redirect(url_for("student.view", student_id=student_id))

        receipt_number = None
        payment_id = None

        if paid_amount > 0:
            # Admission-fee-first waterfall (ADR-62): this is a brand new
            # membership, so old_paid is always 0 - the whole of paid_amount
            # is split against admission_fee_amount from scratch.
            admission_share, membership_share = split_admission_and_membership_fee(
                admission_fee_amount, old_paid=0, amount=paid_amount
            )
            try:
                receipt_number = record_payment(
                    admin_id,
                    membership_id=new_membership_id,
                    student_id=student_id,
                    student_name=student["full_name"],
                    payment_mode=payment_mode,
                    amount=paid_amount,
                    remarks=remarks,
                    category=[
                        ("Admission Fee", admission_share),
                        ("Membership Fee", membership_share),
                    ],
                    description=remarks or f"Admission payment - {plan_name}",
                    source="Admission",
                    idempotency_key=f"{idempotency_key}-payment" if idempotency_key else None
                )
                payment_id = get_payment_id_by_receipt_number(receipt_number)
            except APIError:
                supabase.table("memberships").delete().eq("membership_id", new_membership_id).execute()
                flash(
                    "Could not create this membership due to a database error. "
                    "Nothing was saved - please try again.",
                    "danger"
                )
                return render_template(
                    "memberships/create.html", student=student,
                    plan_pricing=plan_pricing, admission_fee=admission_fee,
                    idempotency_key=secrets.token_urlsafe(24)
                )

        # This is the end of the admission money flow - promote the student
        # from provisional 'Pending' to 'Active' iff the fee is now fully
        # paid (no pending balance). A partially-paid admission stays
        # 'Pending' until the balance is cleared via payment.collect().
        # Best-effort - a status-flip failure must not undo the membership.
        promote_student_if_fully_paid(supabase, student_id)

        if receipt_number:
            flash(
                f"Membership created successfully. Receipt No: {receipt_number}",
                "success"
            )
        else:
            flash("Membership created successfully.", "success")

        if payment_id:
            return redirect(url_for("payment.receipt", payment_id=payment_id))
        return redirect(url_for("student.view", student_id=student_id))

    return render_template(
        "memberships/create.html", student=student,
        plan_pricing=plan_pricing, admission_fee=admission_fee,
        idempotency_key=secrets.token_urlsafe(24)
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
    # Admission fee is a one-time new-admission charge only (see create()
    # above) -- deliberately not fetched/applied here. A renewal's Total
    # Payable is the configured plan price alone.

    if request.method == "POST":

        # Idempotency (TD-30, ADR-53): the hidden token this form's GET
        # render embedded. A double-click/back-button resubmit posts the
        # same token twice - short-circuit here, before touching the
        # previous membership's status, instead of expiring it twice or
        # (the real risk) inserting a second new membership row.
        idempotency_key = request.form.get("idempotency_key") or None
        if idempotency_key:
            existing_membership = find_membership_by_idempotency_key(idempotency_key)
            if existing_membership is not None:
                flash("This membership renewal was already recorded.", "info")
                return redirect(url_for("student.view", student_id=student_id))

        plan_name = normalize_category(request.form.get("plan_name"))
        joining_date = request.form.get("joining_date")
        duration_days = _sanitize_int(request.form.get("duration_days"))
        end_date = request.form.get("end_date")
        remarks = normalize_free_text(request.form.get("remarks"))
        payment_mode = request.form.get("payment_mode", "Cash")
        raw_plan = request.form.get("plan_name")

        try:
            paid_amount = float(request.form.get("paid_amount", 0) or 0)
        except ValueError:
            flash("Invalid amount entered.", "danger")
            return render_template(
                "memberships/renew.html", student=student, plan_pricing=plan_pricing,
                idempotency_key=secrets.token_urlsafe(24)
            )

        if paid_amount < 0:
            flash("Paid amount cannot be negative.", "danger")
            return render_template(
                "memberships/renew.html", student=student, plan_pricing=plan_pricing,
                idempotency_key=secrets.token_urlsafe(24)
            )

        if raw_plan == "Custom":
            try:
                total_fee = float(request.form.get("total_fee", 0) or 0)
            except ValueError:
                flash("Invalid Total Payable entered.", "danger")
                return render_template(
                    "memberships/renew.html", student=student, plan_pricing=plan_pricing,
                    idempotency_key=secrets.token_urlsafe(24)
                )
            if total_fee < 0:
                flash("Total Payable cannot be negative.", "danger")
                return render_template(
                    "memberships/renew.html", student=student, plan_pricing=plan_pricing,
                    idempotency_key=secrets.token_urlsafe(24)
                )
        elif raw_plan in plan_pricing:
            total_fee = plan_pricing[raw_plan]["fee"]
        else:
            flash("Membership plan is required.", "danger")
            return render_template(
                "memberships/renew.html", student=student, plan_pricing=plan_pricing,
                idempotency_key=secrets.token_urlsafe(24)
            )

        if total_fee <= 0:
            flash("Total Payable must be greater than zero.", "danger")
            return render_template(
                "memberships/renew.html", student=student, plan_pricing=plan_pricing,
                idempotency_key=secrets.token_urlsafe(24)
            )

        if paid_amount > total_fee:
            flash("Paid cannot exceed Total Payable.", "danger")
            return render_template(
                "memberships/renew.html", student=student, plan_pricing=plan_pricing,
                idempotency_key=secrets.token_urlsafe(24)
            )

        pending_amount = total_fee - paid_amount

        # Same explicit-id bridging as create() above - as of 2026-07-24
        # (ADR-29), computed from Supabase's own MAX(membership_id).
        next_id_response = (
            supabase.table("memberships")
            .select("membership_id")
            .order("membership_id", desc=True)
            .limit(1)
            .execute()
        )
        new_membership_id = (
            next_id_response.data[0]["membership_id"] + 1
            if next_id_response.data else 1
        )

        # Capture which rows this expires so a failure partway through this
        # request can be rolled back without guessing which rows were live
        # beforehand.
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
            "pending_amount": pending_amount,
            # A renewal never carries an admission charge (ADR-45/ADR-62) -
            # explicit 0 rather than relying on the column default, so it's
            # unambiguous in the code that this is deliberate, not an
            # oversight.
            "admission_fee_amount": 0,
            "remarks": remarks,
            "membership_status": "Active",
            "idempotency_key": idempotency_key,
        }

        existing_membership = None

        try:
            if previously_active_ids:
                supabase.table("memberships").update(
                    {"membership_status": "Expired"}
                ).eq("student_id", student_id).eq("membership_status", "Active").execute()

            # insert_membership() (database/membership_queries.py) instead of
            # a raw .insert() - reused here for its idempotency handling
            # (TD-30, ADR-53): renew() never sets discount_amount/
            # discount_reason and always sets admission_fee_amount=0, so its
            # DiscountColumnsUnavailable/AdmissionFeeColumnUnavailable
            # branches can never trigger for this call site.
            existing_membership = insert_membership(supabase, membership_row)
        except APIError:
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
                "memberships/renew.html", student=student, plan_pricing=plan_pricing,
                idempotency_key=secrets.token_urlsafe(24)
            )

        if existing_membership is not None:
            # Lost a race to an earlier, identical submission that already
            # renewed this membership (TD-30, ADR-53). The "expire previous"
            # update above is idempotent either way (it only ever matches
            # rows still 'Active'), so nothing needs reverting - just treat
            # this as success, not a new renewal.
            flash("This membership renewal was already recorded.", "info")
            return redirect(url_for("student.view", student_id=student_id))

        receipt_number = None
        payment_id = None

        if paid_amount > 0:
            try:
                receipt_number = record_payment(
                    admin_id,
                    membership_id=new_membership_id,
                    student_id=student_id,
                    student_name=student["full_name"],
                    payment_mode=payment_mode,
                    amount=paid_amount,
                    remarks=remarks,
                    category="Membership Renewal",
                    description=remarks or f"Membership renewal - {plan_name}",
                    source="Renewal",
                    idempotency_key=f"{idempotency_key}-payment" if idempotency_key else None
                )
                payment_id = get_payment_id_by_receipt_number(receipt_number)
            except APIError:
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
                    "memberships/renew.html", student=student, plan_pricing=plan_pricing,
                    idempotency_key=secrets.token_urlsafe(24)
                )

        if receipt_number:
            flash(
                f"Membership renewed successfully. Receipt No: {receipt_number}",
                "success"
            )
        else:
            flash("Membership renewed successfully.", "success")

        if payment_id:
            return redirect(url_for("payment.receipt", payment_id=payment_id))
        return redirect(url_for("student.view", student_id=student_id))

    return render_template(
        "memberships/renew.html", student=student, plan_pricing=plan_pricing,
        idempotency_key=secrets.token_urlsafe(24)
    )
