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

from database.supabase_client import get_supabase_client

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

        full_name = request.form.get("full_name", "").strip()
        mobile = request.form.get("mobile", "").strip()
        purpose = request.form.get("purpose", "").strip()
        preferred_shift = request.form.get("preferred_shift", "").strip()
        followup_date = _sanitize_date(request.form.get("followup_date", ""))
        remarks = request.form.get("remarks", "").strip()

        supabase = get_supabase_client()

        # enquiry_id is assigned explicitly, not left to Supabase's
        # auto-assigned identity value -- same reasoning ADR-18 originally
        # established (Supabase's identity sequence was seeded once from a
        # one-time data copy, ADR-15, and can't be trusted to stay ahead of
        # explicit inserts). As of 2026-07-24 (ADR-30), computed from
        # Supabase's own MAX(enquiry_id) - the SQLite mirror this used to
        # read is gone.
        next_id_response = (
            supabase.table("enquiries")
            .select("enquiry_id")
            .order("enquiry_id", desc=True)
            .limit(1)
            .execute()
        )
        new_enquiry_id = (
            next_id_response.data[0]["enquiry_id"] + 1
            if next_id_response.data else 1
        )

        try:
            supabase.table("enquiries").insert({
                "enquiry_id": new_enquiry_id,
                "admin_id": admin_id,
                "full_name": full_name,
                "mobile": mobile,
                "purpose": purpose,
                "preferred_shift": preferred_shift,
                "followup_date": followup_date,
                "remarks": remarks,
            }).execute()
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

        full_name = request.form.get("full_name", "").strip()
        mobile = request.form.get("mobile", "").strip()
        purpose = request.form.get("purpose", "").strip()
        preferred_shift = request.form.get("preferred_shift", "").strip()
        followup_date = _sanitize_date(request.form.get("followup_date"))
        remarks = request.form.get("remarks", "").strip()

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
