import secrets
from datetime import date

import httpx
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
from database.payment_queries import record_payment
from database.membership_settings_queries import get_membership_settings
from database.membership_queries import (
    get_effective_status,
    get_active_membership,
    get_plan_pricing,
    get_admission_fee,
    insert_membership,
    find_membership_by_idempotency_key,
    promote_student_if_fully_paid,
    split_payment_across_buckets,
    compute_slot_charge,
    resolve_slot_bucket,
    PLAN_MONTHS,
    DiscountColumnsUnavailable,
    AdmissionFeeColumnUnavailable,
)
from database.shift_slots_queries import get_shift_slots
from database.membership_charges_queries import (
    get_charge_config,
    get_membership_charges,
    insert_membership_charges,
    mark_charge_refunded,
    ChargeTableUnavailable,
)
from database.cashbook_queries import insert_transaction
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


def _fetch_student(supabase, student_id, admin_id):
    """This admin's student row, or None - shared by create()/renew()."""
    try:
        response = (
            supabase.table("students")
            .select("*")
            .eq("student_id", student_id)
            .eq("admin_id", admin_id)
            .execute()
        )
        return response.data[0] if response.data else None
    except (APIError, httpx.TransportError):
        return None


def _has_existing_membership(supabase, student_id):
    """True if this student has ever had a membership row - renew()'s guard
    that Create must run first for a brand-new student."""
    try:
        response = (
            supabase.table("memberships")
            .select("membership_id")
            .eq("student_id", student_id)
            .limit(1)
            .execute()
        )
        return bool(response.data)
    except (APIError, httpx.TransportError):
        return False


def _latest_membership_shift_slot_id(supabase, student_id):
    """shift_slot_id off this student's most recent membership row, or None
    - renew()'s pre-selected shift slot in the form."""
    try:
        response = (
            supabase.table("memberships")
            .select("shift_slot_id")
            .eq("student_id", student_id)
            .order("membership_id", desc=True)
            .limit(1)
            .execute()
        )
        return response.data[0].get("shift_slot_id") if response.data else None
    except (APIError, httpx.TransportError):
        return None


def _delete_membership_and_charges(supabase, membership_id):
    """Roll back a just-inserted membership. Its membership_charges rows (if
    any) must go first - they carry a foreign key to memberships."""
    try:
        supabase.table("membership_charges").delete().eq(
            "membership_id", membership_id
        ).execute()
    except APIError:
        pass
    supabase.table("memberships").delete().eq("membership_id", membership_id).execute()


def _resolve_applied_charges(charge_config, form, plan_name, recurring_only=False):
    """Which configured charges apply to this membership: every compulsory
    one, plus every optional one whose key was posted as `applied_charge`.
    Each returned dict's `amount` is the term total (a recurring charge is
    its monthly amount x the plan's month count). Charges with a 0 amount
    are skipped - there is nothing to record. `recurring_only` restricts to
    seat/locker (renewal)."""

    selected = set(form.getlist("applied_charge"))
    months = PLAN_MONTHS.get(plan_name, 1)
    applied = []
    for c in charge_config:
        if recurring_only and not c["recurring"]:
            continue
        if not (c["compulsory"] or c["key"] in selected):
            continue
        if c["amount"] <= 0:
            continue
        applied.append({
            "key": c["key"],
            "label": c["label"],
            "cashbook": c["cashbook"],
            "recurring": c["recurring"],
            "refundable": c["refundable"],
            "amount": c["amount"] * (months if c["recurring"] else 1),
        })
    return applied


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

    student = _fetch_student(supabase, student_id, admin_id)

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
    shift_slots = get_shift_slots(admin_id)
    slots_by_id = {s["slot_id"]: s for s in shift_slots}
    charge_config = get_charge_config(settings)

    def _render():
        return render_template(
            "memberships/create.html",
            student=student,
            plan_pricing=plan_pricing,
            admission_fee=admission_fee,
            shift_slots=shift_slots,
            charge_config=charge_config,
            plan_months=PLAN_MONTHS,
            idempotency_key=secrets.token_urlsafe(24),
        )

    if request.method != "POST":
        return _render()

    # Idempotency (TD-30, ADR-53): the hidden token this form's GET render
    # embedded. A double-click / back-button resubmit posts it twice -
    # short-circuit before creating a second identical membership.
    idempotency_key = request.form.get("idempotency_key") or None
    if idempotency_key:
        # A dropped connection here (httpx.TransportError, TD-70/TD-99) is
        # treated the same as the "idempotency_key isn't a column yet"
        # case find_membership_by_idempotency_key() itself already
        # degrades to: proceed as if no earlier submission was found. This
        # dedup check is an invisible safety net (TD-30/ADR-53), not a hard
        # gate - failing the whole request over it would be worse than
        # occasionally skipping the duplicate check.
        try:
            existing_membership = find_membership_by_idempotency_key(idempotency_key)
        except httpx.TransportError:
            existing_membership = None
        if existing_membership is not None:
            flash("This membership was already created.", "info")
            return redirect(url_for("student.view", student_id=student_id))

    plan_name = normalize_category(request.form.get("plan_name"))
    # Pricing lookups use the raw Title-Case plan value the form posts
    # ("Monthly", ...); normalize_category() uppercases it only for storage.
    raw_plan = request.form.get("plan_name")
    joining_date = request.form.get("joining_date")
    duration_days = _sanitize_int(request.form.get("duration"))
    end_date = request.form.get("end_date")
    remarks = normalize_free_text(request.form.get("remarks"))
    payment_mode = request.form.get("payment_mode", "Cash")

    if not plan_name:
        flash("Membership plan is required.", "danger")
        return _render()

    if not (joining_date or "").strip():
        flash("Joining date is required.", "danger")
        return _render()

    # Shift slot (ADR-65) - optional; when set, its monthly fee x plan term
    # replaces the flat plan fee below.
    slot = None
    shift_slot_id = _sanitize_int(request.form.get("shift_slot_id"))
    if shift_slot_id is not None:
        slot = slots_by_id.get(shift_slot_id)
        if slot is None:
            flash("The selected shift is not available. Please pick another.", "danger")
            return _render()

    night_hours = _sanitize_int(request.form.get("night_hours")) or 0
    if slot is not None and slot.get("is_night_hourly") and night_hours <= 0:
        flash("Enter the number of night hours for this shift.", "danger")
        return _render()

    try:
        paid_amount = float(request.form.get("paid_amount", 0) or 0)
    except ValueError:
        flash("Invalid amount entered.", "danger")
        return _render()

    if paid_amount < 0:
        flash("Paid amount cannot be negative.", "danger")
        return _render()

    is_custom = raw_plan == "Custom"

    # Base fee: a Custom plan's staff-entered total, else the shift-slot
    # component, else the configured plan fee. Never trusted from client
    # input except for Custom (ADR-45/ADR-65).
    if is_custom:
        try:
            base_fee = float(request.form.get("total_fee", 0) or 0)
        except ValueError:
            flash("Invalid Total Payable entered.", "danger")
            return _render()
        if base_fee < 0:
            flash("Total Payable cannot be negative.", "danger")
            return _render()
    elif slot is not None:
        base_fee = compute_slot_charge(slot, raw_plan, night_hours)
        if base_fee is None:
            flash("Membership plan is required.", "danger")
            return _render()
    elif raw_plan in plan_pricing:
        base_fee = plan_pricing[raw_plan]["fee"]
    else:
        flash("Membership plan is required.", "danger")
        return _render()

    # Extra charges (ADR-66): every compulsory one, plus the optional ones
    # ticked in the Extra Charges box. "registration" is the ADR-62
    # admission fee - it stays on admission_fee_amount, and (like that fee)
    # is never applied on a Custom plan, whose manual total is the whole
    # payable.
    applied = _resolve_applied_charges(charge_config, request.form, raw_plan)
    if is_custom:
        applied = []
    registration_amount = next(
        (a["amount"] for a in applied if a["key"] == "registration"), 0.0
    )
    extra_charges = [a for a in applied if a["key"] != "registration"]
    extras_total = sum(a["amount"] for a in extra_charges)

    total_fee = base_fee + registration_amount + extras_total

    if total_fee <= 0:
        flash("Total Payable must be greater than zero.", "danger")
        return _render()

    # Discount (ADR-46): a transparent line item on top of Total Payable,
    # never folded silently into it. Final Payable = Total Payable - Discount.
    try:
        discount_amount = float(request.form.get("discount_amount", 0) or 0)
    except ValueError:
        flash("Invalid discount entered.", "danger")
        return _render()
    discount_reason = normalize_free_text(request.form.get("discount_reason", ""))

    if discount_amount < 0:
        flash("Discount cannot be negative.", "danger")
        return _render()
    if discount_amount >= total_fee:
        flash("Discount cannot be greater than or equal to Total Payable.", "danger")
        return _render()

    total_fee = total_fee - discount_amount
    # A discount deep enough to undercut the pass-through charges must not let
    # the split attribute more to a charge bucket than the student now owes.
    admission_fee_amount = min(registration_amount, total_fee)

    if paid_amount > total_fee:
        flash("Paid cannot exceed Final Payable.", "danger")
        return _render()

    pending_amount = total_fee - paid_amount

    # membership_id assigned explicitly from Supabase's own MAX (ADR-29).
    # Catches httpx.TransportError alongside APIError (TD-70/TD-99): a
    # transient dropped connection here is not an APIError, and this call
    # previously had no try/except at all - an unhandled crash, not a
    # friendly "please try again" flash.
    try:
        next_id_response = (
            supabase.table("memberships")
            .select("membership_id")
            .order("membership_id", desc=True)
            .limit(1)
            .execute()
        )
    except (APIError, httpx.TransportError):
        flash(
            "Could not create this membership due to a database error. "
            "Nothing was saved - please try again.",
            "danger",
        )
        return _render()
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
        "shift_slot_id": slot["slot_id"] if slot else None,
        "shift_slot_name": slot["name"] if slot else None,
        "time_bucket": resolve_slot_bucket(slot) if slot else None,
    }

    try:
        existing_membership = insert_membership(supabase, membership_row)
    except DiscountColumnsUnavailable:
        flash(
            "Discounts aren't available yet on this system - the database "
            "needs a one-time update. Contact your administrator, or create "
            "this membership without a discount.",
            "danger",
        )
        return _render()
    except AdmissionFeeColumnUnavailable:
        flash(
            "Admission fee tracking isn't available yet on this system - the "
            "database needs a one-time update. Contact your administrator, or "
            "set Registration Fee to ₹0 in Settings > Membership Settings.",
            "danger",
        )
        return _render()
    except (APIError, httpx.TransportError):
        flash(
            "Could not create this membership due to a database error. "
            "Nothing was saved - please try again.",
            "danger",
        )
        return _render()

    if existing_membership is not None:
        # Lost a race to an earlier, identical submission (TD-30, ADR-53).
        flash("This membership was already created.", "info")
        return redirect(url_for("student.view", student_id=student_id))

    # Extra-charge rows (ADR-66). ChargeTableUnavailable => the table isn't
    # on this project yet and a real charge would be lost: undo the
    # membership we just inserted so nothing is half-saved.
    try:
        insert_membership_charges(
            supabase,
            new_membership_id,
            [
                {
                    "charge_key": a["key"],
                    "label": a["label"],
                    "amount": a["amount"],
                    "recurring": a["recurring"],
                    "refundable": a["refundable"],
                }
                for a in extra_charges
            ],
        )
    except ChargeTableUnavailable:
        _delete_membership_and_charges(supabase, new_membership_id)
        flash(
            "Seat / locker / deposit charges aren't available yet on this "
            "system - the database needs a one-time update. Contact your "
            "administrator, or create this membership without extra charges.",
            "danger",
        )
        return _render()
    except (APIError, httpx.TransportError):
        # Previously uncaught here (TD-70/TD-99) - any other database error
        # or dropped connection while writing the extra-charge rows must
        # roll back the membership too, same as ChargeTableUnavailable above.
        _delete_membership_and_charges(supabase, new_membership_id)
        flash(
            "Could not create this membership due to a database error. "
            "Nothing was saved - please try again.",
            "danger",
        )
        return _render()

    receipt_number = None
    payment_id = None

    if paid_amount > 0:
        # Admission-fee-first waterfall across every charge bucket, then the
        # membership fee (ADR-62/ADR-66). Brand-new membership => old_paid 0.
        buckets = [("Admission Fee", admission_fee_amount)]
        buckets += [(a["cashbook"], a["amount"]) for a in extra_charges]
        buckets.append((
            "Membership Fee",
            max(0.0, total_fee - admission_fee_amount - extras_total),
        ))
        components = split_payment_across_buckets(
            buckets, old_paid=0, amount=paid_amount
        )
        try:
            receipt_number, payment_id = record_payment(
                admin_id,
                membership_id=new_membership_id,
                student_id=student_id,
                student_name=student["full_name"],
                payment_mode=payment_mode,
                amount=paid_amount,
                remarks=remarks,
                category=components,
                description=remarks or f"Admission payment - {plan_name}",
                source="Admission",
                idempotency_key=f"{idempotency_key}-payment" if idempotency_key else None,
            )
        except (APIError, httpx.TransportError):
            _delete_membership_and_charges(supabase, new_membership_id)
            flash(
                "Could not create this membership due to a database error. "
                "Nothing was saved - please try again.",
                "danger",
            )
            return _render()

    # End of the admission money flow - promote the student from provisional
    # 'Pending' to 'Active' iff nothing is still owing. Best-effort.
    promote_student_if_fully_paid(supabase, student_id)

    if receipt_number:
        flash(
            f"Membership created successfully. Receipt No: {receipt_number}",
            "success",
        )
    else:
        flash("Membership created successfully.", "success")

    if payment_id:
        return redirect(url_for("payment.receipt", payment_id=payment_id))
    return redirect(url_for("student.view", student_id=student_id))


@membership_bp.route("/renew/<int:student_id>", methods=["GET", "POST"])
def renew(student_id):

    if "admin_id" not in session:
        return redirect("/")

    admin_id = session["admin_id"]
    supabase = get_supabase_client()

    student = _fetch_student(supabase, student_id, admin_id)

    if student is None:
        flash("Student not found.", "danger")
        return redirect(url_for("student.index"))

    # Guard: must have at least one existing membership to renew
    has_existing = _has_existing_membership(supabase, student_id)
    if not has_existing:
        flash("No existing membership found. Please create a membership first.", "warning")
        return redirect(url_for("membership.create", student_id=student_id))

    settings = get_membership_settings(admin_id)
    plan_pricing = get_plan_pricing(settings)
    shift_slots = get_shift_slots(admin_id)
    slots_by_id = {s["slot_id"]: s for s in shift_slots}
    charge_config = get_charge_config(settings)
    recurring_charges = [c for c in charge_config if c["recurring"]]
    # Registration and the security deposit are one-time new-admission
    # charges (ADR-45/ADR-62) - a renewal only re-charges the recurring
    # ones (seat reservation, locker).

    # Pre-select the shift slot the student's latest membership was sold on.
    prev_slot_id = _latest_membership_shift_slot_id(supabase, student_id)

    def _render():
        return render_template(
            "memberships/renew.html",
            student=student,
            plan_pricing=plan_pricing,
            shift_slots=shift_slots,
            charge_config=recurring_charges,
            plan_months=PLAN_MONTHS,
            prev_slot_id=prev_slot_id,
            idempotency_key=secrets.token_urlsafe(24),
        )

    if request.method != "POST":
        return _render()

    # Idempotency (TD-30, ADR-53): the hidden token this form's GET render
    # embedded - short-circuit a double-submit before expiring the previous
    # membership twice or inserting a second new row.
    idempotency_key = request.form.get("idempotency_key") or None
    if idempotency_key:
        # See create()'s equivalent block above for why a dropped
        # connection (httpx.TransportError, TD-70/TD-99) here degrades to
        # "proceed as if no earlier submission was found" instead of
        # crashing.
        try:
            existing_membership = find_membership_by_idempotency_key(idempotency_key)
        except httpx.TransportError:
            existing_membership = None
        if existing_membership is not None:
            flash("This membership renewal was already recorded.", "info")
            return redirect(url_for("student.view", student_id=student_id))

    plan_name = normalize_category(request.form.get("plan_name"))
    raw_plan = request.form.get("plan_name")
    joining_date = request.form.get("joining_date")
    duration_days = _sanitize_int(request.form.get("duration_days"))
    end_date = request.form.get("end_date")
    remarks = normalize_free_text(request.form.get("remarks"))
    payment_mode = request.form.get("payment_mode", "Cash")

    slot = None
    shift_slot_id = _sanitize_int(request.form.get("shift_slot_id"))
    if shift_slot_id is not None:
        slot = slots_by_id.get(shift_slot_id)
        if slot is None:
            flash("The selected shift is not available. Please pick another.", "danger")
            return _render()

    night_hours = _sanitize_int(request.form.get("night_hours")) or 0
    if slot is not None and slot.get("is_night_hourly") and night_hours <= 0:
        flash("Enter the number of night hours for this shift.", "danger")
        return _render()

    try:
        paid_amount = float(request.form.get("paid_amount", 0) or 0)
    except ValueError:
        flash("Invalid amount entered.", "danger")
        return _render()
    if paid_amount < 0:
        flash("Paid amount cannot be negative.", "danger")
        return _render()

    is_custom = raw_plan == "Custom"

    if is_custom:
        try:
            base_fee = float(request.form.get("total_fee", 0) or 0)
        except ValueError:
            flash("Invalid Total Payable entered.", "danger")
            return _render()
        if base_fee < 0:
            flash("Total Payable cannot be negative.", "danger")
            return _render()
    elif slot is not None:
        base_fee = compute_slot_charge(slot, raw_plan, night_hours)
        if base_fee is None:
            flash("Membership plan is required.", "danger")
            return _render()
    elif raw_plan in plan_pricing:
        base_fee = plan_pricing[raw_plan]["fee"]
    else:
        flash("Membership plan is required.", "danger")
        return _render()

    # A renewal re-charges only the recurring extras (seat / locker).
    applied = (
        [] if is_custom
        else _resolve_applied_charges(
            charge_config, request.form, raw_plan, recurring_only=True
        )
    )
    extras_total = sum(a["amount"] for a in applied)
    total_fee = base_fee + extras_total

    if total_fee <= 0:
        flash("Total Payable must be greater than zero.", "danger")
        return _render()

    if paid_amount > total_fee:
        flash("Paid cannot exceed Total Payable.", "danger")
        return _render()

    pending_amount = total_fee - paid_amount

    # Same explicit-id bridging as create() (ADR-29). Catches
    # httpx.TransportError alongside APIError (TD-70/TD-99) - see create()'s
    # equivalent block for why.
    try:
        next_id_response = (
            supabase.table("memberships")
            .select("membership_id")
            .order("membership_id", desc=True)
            .limit(1)
            .execute()
        )
    except (APIError, httpx.TransportError):
        flash(
            "Could not renew this membership due to a database error. "
            "Nothing was saved - please try again.",
            "danger",
        )
        return _render()
    new_membership_id = (
        next_id_response.data[0]["membership_id"] + 1
        if next_id_response.data else 1
    )

    # Capture which rows this expires so a failure partway through can be
    # rolled back without guessing which rows were live beforehand.
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

    def _reactivate_previous():
        if previously_active_ids:
            supabase.table("memberships").update(
                {"membership_status": "Active"}
            ).in_("membership_id", previously_active_ids).execute()

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
        # A renewal never carries an admission charge (ADR-45/ADR-62).
        "admission_fee_amount": 0,
        "remarks": remarks,
        "membership_status": "Active",
        "idempotency_key": idempotency_key,
        "shift_slot_id": slot["slot_id"] if slot else None,
        "shift_slot_name": slot["name"] if slot else None,
        "time_bucket": resolve_slot_bucket(slot) if slot else None,
    }

    existing_membership = None
    try:
        if previously_active_ids:
            supabase.table("memberships").update(
                {"membership_status": "Expired"}
            ).eq("student_id", student_id).eq("membership_status", "Active").execute()
        existing_membership = insert_membership(supabase, membership_row)
    except (APIError, httpx.TransportError):
        _reactivate_previous()
        flash(
            "Could not renew this membership due to a database error. "
            "Nothing was saved - please try again.",
            "danger",
        )
        return _render()

    if existing_membership is not None:
        # Lost a race to an earlier, identical submission (TD-30, ADR-53).
        flash("This membership renewal was already recorded.", "info")
        return redirect(url_for("student.view", student_id=student_id))

    try:
        insert_membership_charges(
            supabase,
            new_membership_id,
            [
                {
                    "charge_key": a["key"],
                    "label": a["label"],
                    "amount": a["amount"],
                    "recurring": a["recurring"],
                    "refundable": a["refundable"],
                }
                for a in applied
            ],
        )
    except ChargeTableUnavailable:
        _delete_membership_and_charges(supabase, new_membership_id)
        _reactivate_previous()
        flash(
            "Seat / locker charges aren't available yet on this system - the "
            "database needs a one-time update. Contact your administrator, or "
            "renew without extra charges.",
            "danger",
        )
        return _render()
    except (APIError, httpx.TransportError):
        # Previously uncaught here (TD-70/TD-99) - see create()'s equivalent
        # block above.
        _delete_membership_and_charges(supabase, new_membership_id)
        _reactivate_previous()
        flash(
            "Could not renew this membership due to a database error. "
            "Nothing was saved - please try again.",
            "danger",
        )
        return _render()

    receipt_number = None
    payment_id = None

    if paid_amount > 0:
        if applied:
            buckets = [(a["cashbook"], a["amount"]) for a in applied]
            buckets.append(("Membership Renewal", total_fee - extras_total))
            category = split_payment_across_buckets(
                buckets, old_paid=0, amount=paid_amount
            )
        else:
            category = "Membership Renewal"
        try:
            receipt_number, payment_id = record_payment(
                admin_id,
                membership_id=new_membership_id,
                student_id=student_id,
                student_name=student["full_name"],
                payment_mode=payment_mode,
                amount=paid_amount,
                remarks=remarks,
                category=category,
                description=remarks or f"Membership renewal - {plan_name}",
                source="Renewal",
                idempotency_key=f"{idempotency_key}-payment" if idempotency_key else None,
            )
        except (APIError, httpx.TransportError):
            _delete_membership_and_charges(supabase, new_membership_id)
            _reactivate_previous()
            flash(
                "Could not renew this membership due to a database error. "
                "Nothing was saved - please try again.",
                "danger",
            )
            return _render()

    if receipt_number:
        flash(
            f"Membership renewed successfully. Receipt No: {receipt_number}",
            "success",
        )
    else:
        flash("Membership renewed successfully.", "success")

    if payment_id:
        return redirect(url_for("payment.receipt", payment_id=payment_id))
    return redirect(url_for("student.view", student_id=student_id))


@membership_bp.route("/refund-charge/<int:membership_id>/<charge_key>", methods=["POST"])
def refund_charge(membership_id, charge_key):
    """Refund a refundable membership charge (the security deposit): record
    one Cashbook Expense and stamp membership_charges.refunded_on. Does not
    touch total_fee / paid_amount / pending_amount - the deposit was
    collected as part of payables; giving it back is a separate cash
    outflow (ADR-66). Idempotent: a charge already refunded is a no-op."""

    if "admin_id" not in session:
        return redirect("/")

    admin_id = session["admin_id"]
    supabase = get_supabase_client()

    # Admin-ownership: the membership's student must belong to this admin.
    try:
        membership_response = (
            supabase.table("memberships")
            .select("membership_id, student_id")
            .eq("membership_id", membership_id)
            .limit(1)
            .execute()
        )
        membership = membership_response.data[0] if membership_response.data else None
    except APIError:
        membership = None

    student = None
    if membership is not None:
        try:
            student_response = (
                supabase.table("students")
                .select("student_id, full_name, admin_id")
                .eq("student_id", membership["student_id"])
                .limit(1)
                .execute()
            )
            student = student_response.data[0] if student_response.data else None
        except APIError:
            student = None

    if membership is None or student is None or student["admin_id"] != admin_id:
        flash("Membership not found.", "danger")
        return redirect(url_for("student.index"))

    charge = next(
        (c for c in get_membership_charges(membership_id) if c["charge_key"] == charge_key),
        None,
    )
    if charge is None or not charge.get("refundable"):
        flash("That charge cannot be refunded.", "warning")
        return redirect(url_for("student.view", student_id=student["student_id"]))
    if charge.get("refunded_on"):
        flash("That charge has already been refunded.", "info")
        return redirect(url_for("student.view", student_id=student["student_id"]))

    payment_method = request.form.get("payment_method", "Cash")
    today = date.today().isoformat()

    try:
        insert_transaction(
            admin_id,
            transaction_type="Expense",
            category="Security Deposit Refund",
            person=student["full_name"],
            description=f"{charge['label']} refund - {student['full_name']}",
            amount=charge["amount"],
            payment_method=payment_method,
            entry_date=today,
        )
        mark_charge_refunded(supabase, membership_id, charge_key, today)
    except APIError:
        flash(
            "Could not record the refund due to a database error. Please try again.",
            "danger",
        )
        return redirect(url_for("student.view", student_id=student["student_id"]))

    flash(
        f"{charge['label']} of ₹{charge['amount']:,.0f} refunded.",
        "success",
    )
    return redirect(url_for("student.view", student_id=student["student_id"]))
