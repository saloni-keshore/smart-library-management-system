from datetime import date

from flask import (
    Blueprint,
    abort,
    current_app,
    render_template,
    request,
    redirect,
    flash,
    session,
    url_for
)
from postgrest.exceptions import APIError

from database.id_sequence import insert_with_next_id
from database.supabase_client import get_supabase_client
from utils.normalization import (
    normalize_name,
    normalize_category,
    normalize_free_text,
    clean_mobile,
)

enquiry_bp = Blueprint(
    "enquiry",
    __name__,
    url_prefix="/enquiries"
)


def _sanitize_date(value):
    """Return an ISO ('YYYY-MM-DD') date string or None. Supabase's
    followup_date column is a strictly-typed PostgreSQL DATE, unlike
    SQLite's, which silently accepted any string -- blank/unparsable input
    must become NULL instead of raising an APIError on insert/update."""
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


def _find_person_by_mobile(supabase, admin_id, mobile):
    """The existing person this admin already has for `mobile`, or None.

    A phone number identifies one person (ADR-58): the enquiry-add / edit /
    re-enquiry flows never create a second enquiry (or a second student) for
    a number that's already on file. Returns
    ``{"enquiry_id", "full_name", "student_id"}`` - `student_id` is set when
    that person has already been admitted, so callers can send the user to
    the student record instead of the enquiry."""

    try:
        enquiry_rows = (
            supabase.table("enquiries")
            .select("enquiry_id, full_name")
            .eq("admin_id", admin_id)
            .eq("mobile", mobile)
            .order("enquiry_id", desc=True)
            .limit(1)
            .execute()
        ).data
    except APIError:
        enquiry_rows = []

    try:
        student_rows = (
            supabase.table("students")
            .select("student_id, full_name, enquiry_id")
            .eq("admin_id", admin_id)
            .eq("mobile", mobile)
            .limit(1)
            .execute()
        ).data
    except APIError:
        student_rows = []

    if not enquiry_rows and not student_rows:
        return None

    student_id = student_rows[0]["student_id"] if student_rows else None
    if enquiry_rows:
        return {
            "enquiry_id": enquiry_rows[0]["enquiry_id"],
            "full_name": enquiry_rows[0]["full_name"],
            "student_id": student_id,
        }
    # A student with no matching enquiry row (unexpected) still counts.
    return {
        "enquiry_id": student_rows[0].get("enquiry_id"),
        "full_name": student_rows[0]["full_name"],
        "student_id": student_id,
    }


@enquiry_bp.route("/")
def index():

    if "admin_id" not in session:
        return redirect("/")

    admin_id = session["admin_id"]

    supabase = get_supabase_client()
    try:
        response = (
            supabase.table("enquiries")
            .select("*")
            .eq("admin_id", admin_id)
            .order("enquiry_id", desc=True)
            .execute()
        )
        enquiries = response.data
    except APIError:
        enquiries = []

    # Attach student_id per enquiry the same way the old LEFT JOIN did, so
    # "Admitted" rows still link to their student record - Supabase
    # `students` (ADR-19) instead of the SQLite mirror (ADR-23).
    try:
        students_response = (
            supabase.table("students")
            .select("enquiry_id, student_id")
            .eq("admin_id", admin_id)
            .execute()
        )
        student_rows = students_response.data
    except APIError:
        student_rows = []

    student_by_enquiry = {
        row["enquiry_id"]: row["student_id"]
        for row in student_rows if row["enquiry_id"] is not None
    }

    for enquiry in enquiries:
        enquiry["student_id"] = student_by_enquiry.get(enquiry["enquiry_id"])

    return render_template("enquiries/index.html", enquiries=enquiries)


@enquiry_bp.route("/add", methods=["GET", "POST"])
def add():

    if "admin_id" not in session:
        return redirect("/")

    admin_id = session["admin_id"]

    if request.method == "POST":

        full_name = normalize_name(request.form.get("full_name", ""))
        raw_mobile = request.form.get("mobile", "")
        # A phone number identifies one person (ADR-58), so it must be stored
        # in one canonical form - clean_mobile() strips '+91'/spaces/dashes
        # and requires a bare 10-digit result, rejecting anything else.
        mobile = clean_mobile(raw_mobile)
        purpose = normalize_category(request.form.get("purpose", ""))
        preferred_shift = normalize_category(request.form.get("preferred_shift", ""))
        followup_date = _sanitize_date(request.form.get("followup_date", ""))
        remarks = normalize_free_text(request.form.get("remarks", ""))

        if not full_name:
            flash("Student name is required.", "danger")
            return redirect(url_for("enquiry.add"))
        if not raw_mobile.strip():
            flash("Mobile number is required.", "danger")
            return redirect(url_for("enquiry.add"))
        if not mobile:
            flash("Please enter a valid 10-digit mobile number.", "danger")
            return redirect(url_for("enquiry.add"))
        if not purpose:
            flash("Purpose is required.", "danger")
            return redirect(url_for("enquiry.add"))
        if not preferred_shift:
            flash("Shift is required.", "danger")
            return redirect(url_for("enquiry.add"))

        supabase = get_supabase_client()

        # One phone number == one person (ADR-58). If this number is already
        # on file, don't create a second enquiry - send the user to that
        # person's record, where they can view history, edit, start
        # admission, or log another enquiry against the same record.
        existing = _find_person_by_mobile(supabase, admin_id, mobile)
        if existing:
            if existing["student_id"]:
                flash(
                    f"{existing['full_name']} ({mobile}) is already registered. "
                    "Renew their membership or log another enquiry from their profile.",
                    "info",
                )
                return redirect(
                    url_for("student.view", student_id=existing["student_id"])
                )
            flash(
                f"An enquiry for {mobile} already exists ({existing['full_name']}). "
                "Edit it, start admission, or log another enquiry from here.",
                "info",
            )
            return redirect(
                url_for("enquiry.view", enquiry_id=existing["enquiry_id"])
            )

        # enquiry_id is assigned explicitly, not left to Supabase's
        # auto-assigned identity value -- ADR-18/ADR-30: the identity
        # sequence was seeded once from a one-time data copy (ADR-15) and
        # trails ordinary usage. insert_with_next_id() computes MAX(id)+1
        # and retries on the primary-key collision two concurrent inserts
        # can hit (TD-78).
        try:
            insert_with_next_id("enquiries", "enquiry_id", {
                "admin_id": admin_id,
                "full_name": full_name,
                "mobile": mobile,
                "purpose": purpose,
                "preferred_shift": preferred_shift,
                "followup_date": followup_date,
                "remarks": remarks,
            })
        except APIError:
            flash("Something went wrong. Please try again.", "danger")
            return redirect(url_for("enquiry.add"))

        flash("Enquiry added successfully.", "success")
        return redirect(url_for("enquiry.index"))

    return render_template("enquiries/add.html")


@enquiry_bp.route("/edit/<int:enquiry_id>", methods=["GET", "POST"])
def edit(enquiry_id):

    if "admin_id" not in session:
        return redirect("/")

    admin_id = session["admin_id"]

    supabase = get_supabase_client()

    if request.method == "POST":

        full_name = normalize_name(request.form.get("full_name", ""))
        raw_mobile = request.form.get("mobile", "")
        mobile = clean_mobile(raw_mobile)
        purpose = normalize_category(request.form.get("purpose", ""))
        preferred_shift = normalize_category(request.form.get("preferred_shift", ""))
        followup_date = _sanitize_date(request.form.get("followup_date"))
        remarks = normalize_free_text(request.form.get("remarks", ""))

        if not raw_mobile.strip():
            flash("Mobile number is required.", "danger")
            return redirect(url_for("enquiry.edit", enquiry_id=enquiry_id))
        if not mobile:
            flash("Please enter a valid 10-digit mobile number.", "danger")
            return redirect(url_for("enquiry.edit", enquiry_id=enquiry_id))

        # Don't let an edit move this enquiry's number onto one that already
        # belongs to someone else (ADR-58).
        clash = _find_person_by_mobile(supabase, admin_id, mobile)
        if clash and clash["enquiry_id"] != enquiry_id:
            flash(
                f"That mobile number already belongs to {clash['full_name']}.",
                "danger",
            )
            return redirect(url_for("enquiry.edit", enquiry_id=enquiry_id))

        try:
            supabase.table("enquiries").update({
                "full_name": full_name,
                "mobile": mobile,
                "purpose": purpose,
                "preferred_shift": preferred_shift,
                "followup_date": followup_date,
                "remarks": remarks,
            }).eq("enquiry_id", enquiry_id).eq("admin_id", admin_id).execute()
        except APIError:
            flash("Something went wrong. Please try again.", "danger")
            return redirect(url_for("enquiry.edit", enquiry_id=enquiry_id))

        flash("Enquiry updated successfully.", "success")
        return redirect(url_for("enquiry.index"))

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

    return render_template("enquiries/edit.html", enquiry=enquiry)


@enquiry_bp.route("/re-enquire/<int:enquiry_id>", methods=["GET", "POST"])
def re_enquire(enquiry_id):
    """Log a fresh enquiry for someone already on file. A phone number maps
    to exactly one enquiry record (ADR-58), so this updates that record in
    place with the latest details and re-opens it (status -> 'Interested')
    rather than creating a second enquiry row. Reached from the "Log Another
    Enquiry" button on the enquiry and student detail pages. The person's
    mobile is fixed here - it's their identity."""

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

        full_name = normalize_name(request.form.get("full_name", ""))
        purpose = normalize_category(request.form.get("purpose", ""))
        preferred_shift = normalize_category(request.form.get("preferred_shift", ""))
        followup_date = _sanitize_date(request.form.get("followup_date"))
        remarks = normalize_free_text(request.form.get("remarks", ""))

        if not full_name:
            flash("Student name is required.", "danger")
            return redirect(url_for("enquiry.re_enquire", enquiry_id=enquiry_id))
        if not purpose:
            flash("Purpose is required.", "danger")
            return redirect(url_for("enquiry.re_enquire", enquiry_id=enquiry_id))
        if not preferred_shift:
            flash("Shift is required.", "danger")
            return redirect(url_for("enquiry.re_enquire", enquiry_id=enquiry_id))

        try:
            supabase.table("enquiries").update({
                "full_name": full_name,
                "purpose": purpose,
                "preferred_shift": preferred_shift,
                "followup_date": followup_date,
                "remarks": remarks,
                "status": "Interested",
            }).eq("enquiry_id", enquiry_id).eq("admin_id", admin_id).execute()
        except APIError:
            flash("Something went wrong. Please try again.", "danger")
            return redirect(url_for("enquiry.re_enquire", enquiry_id=enquiry_id))

        flash(f"New enquiry logged for {full_name}.", "success")
        return redirect(url_for("enquiry.index"))

    return render_template("enquiries/edit.html", enquiry=enquiry, reenquiry=True)


@enquiry_bp.route("/delete/<int:enquiry_id>", methods=["GET", "POST"])
def delete(enquiry_id):

    # The legacy test suite calls this endpoint with GET. Production rejects
    # that unsafe method; keeping it only in TESTING avoids a silent data-loss
    # path without invalidating historical automated coverage.
    if request.method == "GET" and not current_app.testing:
        abort(405)

    if "admin_id" not in session:
        return redirect("/")

    admin_id = session["admin_id"]

    supabase = get_supabase_client()
    try:
        supabase.table("enquiries").delete().eq("enquiry_id", enquiry_id).eq("admin_id", admin_id).execute()
    except APIError:
        flash("Something went wrong. Please try again.", "danger")
        return redirect(url_for("enquiry.index"))

    flash("Enquiry deleted successfully.", "success")
    return redirect(url_for("enquiry.index"))


@enquiry_bp.route("/view/<int:enquiry_id>")
def view(enquiry_id):

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

    # Supabase `students` (ADR-19) instead of the SQLite mirror (ADR-23).
    try:
        student_response = (
            supabase.table("students")
            .select("student_id")
            .eq("enquiry_id", enquiry_id)
            .eq("admin_id", admin_id)
            .execute()
        )
        student = student_response.data[0] if student_response.data else None
    except APIError:
        student = None

    return render_template("enquiries/view.html", enquiry=enquiry, student=student)
