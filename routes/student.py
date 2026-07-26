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

from database.membership_queries import get_memberships_for_admin, get_effective_status
from database.supabase_client import get_supabase_client
from utils.normalization import (
    normalize_name,
    normalize_phone,
    normalize_category,
    normalize_free_text,
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

    for student in students:
        m = membership_by_student.get(student["student_id"], {})
        student["membership_id"] = m.get("membership_id")
        student["plan_name"] = m.get("plan_name")
        student["paid_amount"] = m.get("paid_amount")
        student["pending_amount"] = m.get("pending_amount")
        student["membership_status"] = (
            get_effective_status(m["membership_status"], m["end_date"]) if m else None
        )

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
        if not (enquiry.get("purpose") or "").strip():
            flash("Purpose is required.", "danger")
            return redirect(url_for("student.admission", enquiry_id=enquiry_id))
        if not (enquiry.get("preferred_shift") or "").strip():
            flash("Shift is required.", "danger")
            return redirect(url_for("student.admission", enquiry_id=enquiry_id))

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
        # trails ordinary usage. As of 2026-07-24 (ADR-29), computed from
        # Supabase's own MAX(student_id) - the SQLite mirror this used to
        # read is gone.
        next_id_response = (
            supabase.table("students")
            .select("student_id")
            .order("student_id", desc=True)
            .limit(1)
            .execute()
        )
        new_student_id = (
            next_id_response.data[0]["student_id"] + 1
            if next_id_response.data else 1
        )

        # full_name/mobile/purpose/shift are inherited from the enquiry,
        # which is already normalized at the point it was saved
        # (routes/enquiries.py) - re-normalizing here is defensive/
        # idempotent, guarding against any enquiry row that predates this
        # normalization pass (see the one-time migration script).
        student_row = {
            "student_id": new_student_id,
            "admin_id": admin_id,
            "enquiry_id": enquiry["enquiry_id"],
            "full_name": normalize_name(enquiry["full_name"]),
            "mobile": normalize_phone(enquiry["mobile"]),
            "address": address,
            "id_proof": id_proof,
            "purpose": normalize_category(enquiry["purpose"]),
            "shift": normalize_category(enquiry["preferred_shift"]),
            "join_date": join_date,
            "status": "Active",
        }

        try:
            supabase.table("students").insert(student_row).execute()
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
        mobile = normalize_phone(request.form.get("mobile"))
        address = normalize_free_text(request.form.get("address"))
        purpose = normalize_category(request.form.get("purpose"))
        shift = normalize_category(request.form.get("shift"))
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

        flash("Student updated successfully.", "success")
        return redirect(url_for("student.view", student_id=student_id))

    return render_template("students/edit.html", student=student)
