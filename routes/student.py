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

from database.id_sequence import insert_with_next_id
from database.membership_queries import get_memberships_for_admin, get_effective_status
from database.supabase_client import get_supabase_client
from utils.normalization import (
    normalize_name,
    normalize_category,
    normalize_free_text,
    clean_mobile,
)


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

    # Attach each student's latest membership + effective status the same
    # way the old correlated-subquery LEFT JOIN did, merged in Python
    # against the Supabase students list - Supabase `students`/`memberships`
    # (ADR-23) via database.membership_queries.get_memberships_for_admin(),
    # instead of a SQLite database-level join.
    memberships = get_memberships_for_admin(admin_id)
    membership_by_student = {}
    for m in memberships:
        current = membership_by_student.get(m["student_id"])
        if current is None or m["membership_id"] > current["membership_id"]:
            membership_by_student[m["student_id"]] = m

    # An admission is "incomplete" when it never got a membership, or the
    # membership still has a balance owing - i.e. the student isn't fully
    # admitted. New records sit at status 'Pending' until
    # promote_student_if_fully_paid() clears them; 'Active' is also counted
    # here so admissions created before the Pending flow existed (and left
    # half-done) still surface. Flagged on the list, never auto-modified.
    incomplete_count = 0

    for student in students:
        m = membership_by_student.get(student["student_id"], {})
        student["membership_id"] = m.get("membership_id")
        student["plan_name"] = m.get("plan_name")
        student["paid_amount"] = m.get("paid_amount")
        student["pending_amount"] = m.get("pending_amount")
        student["membership_status"] = (
            get_effective_status(m["membership_status"], m["end_date"]) if m else None
        )

        student["admission_incomplete"] = (
            student["status"] in ("Pending", "Active")
            and (
                student["membership_id"] is None
                or float(student["pending_amount"] or 0) > 0
            )
        )
        if student["admission_incomplete"]:
            incomplete_count += 1

    return render_template(
        "students/index.html",
        students=students,
        incomplete_count=incomplete_count,
    )


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

        address = normalize_free_text(request.form.get("address", ""))
        id_proof = normalize_free_text(request.form.get("id_proof", ""))
        join_date = _sanitize_date(request.form.get("join_date"))

        # Name/mobile/purpose/shift are inherited from the enquiry rather
        # than re-entered here, so admission must re-check them - an
        # enquiry saved before this validation existed, or missing one of
        # these, must not silently produce an incomplete student record.
        if not (enquiry.get("full_name") or "").strip():
            flash("Student name is required.", "danger")
            return redirect(url_for("student.admission", enquiry_id=enquiry_id))
        if not (enquiry.get("mobile") or "").strip():
            flash("Mobile number is required.", "danger")
            return redirect(url_for("student.admission", enquiry_id=enquiry_id))
        # The mobile is inherited from the enquiry; enquiries created before
        # 10-digit validation existed (ADR-59) could still carry a malformed
        # number, which would break the (admin_id, mobile) person key. Make
        # the operator fix it on the enquiry before a student record is cut.
        mobile = clean_mobile(enquiry.get("mobile"))
        if not mobile:
            flash(
                "This enquiry's mobile number isn't a valid 10-digit number. "
                "Edit the enquiry before admitting.",
                "danger",
            )
            return redirect(url_for("enquiry.edit", enquiry_id=enquiry_id))
        if not (enquiry.get("purpose") or "").strip():
            flash("Purpose is required.", "danger")
            return redirect(url_for("student.admission", enquiry_id=enquiry_id))
        if not (enquiry.get("preferred_shift") or "").strip():
            flash("Shift is required.", "danger")
            return redirect(url_for("student.admission", enquiry_id=enquiry_id))

        # Address / Join Date are entered on this form (not inherited). They
        # are HTML-`required`, but that is bypassable (JS off, a direct
        # POST) - re-check server-side so an admission can't be finalized
        # with them blank. Rejected here means nothing is created; the
        # operator refills the form and resubmits (and anything that still
        # slips through can be fixed in Student > Edit while the record is
        # still 'Pending').
        if not address:
            flash("Address is required.", "danger")
            return redirect(url_for("student.admission", enquiry_id=enquiry_id))
        if join_date is None:
            flash("Join date is required.", "danger")
            return redirect(url_for("student.admission", enquiry_id=enquiry_id))

        # This mobile identifies one person (ADR-58) - if they're already a
        # student, don't admit them a second time; send the operator to the
        # existing record (where "Renew" / "Log Another Enquiry" live).
        try:
            existing_response = (
                supabase.table("students")
                .select("student_id, full_name")
                .eq("mobile", mobile)
                .eq("admin_id", admin_id)
                .execute()
            )
            existing = existing_response.data[0] if existing_response.data else None
        except APIError:
            existing = None

        if existing is not None:
            flash(
                f"{existing['full_name']} is already registered. "
                "Renew their membership or log another enquiry from their profile.",
                "info",
            )
            return redirect(url_for("student.view", student_id=existing["student_id"]))

        # full_name/mobile/purpose/shift are inherited from the enquiry,
        # which is already normalized at the point it was saved
        # (routes/enquiries.py) - re-normalizing here is defensive/
        # idempotent, guarding against any enquiry row that predates this
        # normalization pass (see the one-time migration script). `mobile`
        # is the clean_mobile()-canonicalized value checked above (ADR-59).
        student_row = {
            "admin_id": admin_id,
            "enquiry_id": enquiry["enquiry_id"],
            "full_name": normalize_name(enquiry["full_name"]),
            "mobile": mobile,
            "address": address,
            "id_proof": id_proof,
            "purpose": normalize_category(enquiry["purpose"]),
            "shift": normalize_category(enquiry["preferred_shift"]),
            "join_date": join_date,
            # Provisional until the membership + payment steps actually
            # complete (fee fully paid) - database.membership_queries.
            # promote_student_if_fully_paid() flips this to 'Active' from
            # membership.create()/payment.collect(). Pressing Back or
            # navigating away after this point leaves a visible 'Pending'
            # record, never a silently fully-admitted one (ADR - admission
            # flow).
            "status": "Pending",
        }

        # student_id is assigned explicitly, not left to Supabase's
        # auto-assigned identity value -- ADR-18/ADR-29: the identity
        # sequence was seeded once from a one-time data copy (ADR-15) and
        # trails ordinary usage. insert_with_next_id() computes MAX(id)+1
        # and retries on the primary-key collision two concurrent
        # admissions can hit (TD-78).
        try:
            new_student_id = insert_with_next_id(
                "students", "student_id", student_row
            )
        except APIError:
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

        flash(
            "Student admitted successfully. The student stays Pending until "
            "the membership is created and the fee is fully paid.",
            "success",
        )
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

    # Supabase `memberships`/`payments` (ADR-23/ADR-25) instead of the
    # SQLite mirror - this was the last SQLite read in this file.
    try:
        membership_response = (
            supabase.table("memberships")
            .select("*")
            .eq("student_id", student_id)
            .order("membership_id", desc=True)
            .limit(1)
            .execute()
        )
        membership = membership_response.data[0] if membership_response.data else None
    except APIError:
        membership = None

    try:
        payments_response = (
            supabase.table("payments")
            .select("*")
            .eq("student_id", student_id)
            .order("payment_id", desc=True)
            .execute()
        )
        payments = payments_response.data
    except APIError:
        payments = []

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

        full_name = normalize_name(request.form.get("full_name"))
        raw_mobile = request.form.get("mobile") or ""
        # Canonicalize + validate to a bare 10-digit mobile (ADR-59) so an
        # edit can't put a malformed number onto a student and break the
        # (admin_id, mobile) person key.
        mobile = clean_mobile(raw_mobile)
        address = normalize_free_text(request.form.get("address"))
        purpose = normalize_category(request.form.get("purpose"))
        shift = normalize_category(request.form.get("shift"))
        status = request.form.get("status")

        if not raw_mobile.strip():
            flash("Mobile number is required.", "danger")
            return render_template("students/edit.html", student=student)
        if not mobile:
            flash("Please enter a valid 10-digit mobile number.", "danger")
            return render_template("students/edit.html", student=student)

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

        # Keep the originating enquiry's status in step with the student's
        # (a phone number is one person - ADR-58): deactivating a student
        # marks their enquiry "Inactive" so the Enquiries list/view stops
        # showing a stale "Admitted"; reactivating restores "Admitted". A
        # 'Pending' student (admission underway, not yet fully paid) also
        # counts as "Admitted" here - only an explicit "Inactive" breaks
        # the link. Best-effort - the student update above already succeeded.
        if student.get("enquiry_id"):
            enquiry_status = "Inactive" if status == "Inactive" else "Admitted"
            try:
                supabase.table("enquiries").update(
                    {"status": enquiry_status}
                ).eq("enquiry_id", student["enquiry_id"]).eq("admin_id", admin_id).execute()
            except APIError:
                pass

        flash("Student updated successfully.", "success")
        return redirect(url_for("student.view", student_id=student_id))

    return render_template("students/edit.html", student=student)
