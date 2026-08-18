from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for
from postgrest.exceptions import APIError

from database.ai_center_queries import compute_student_risk, search_students
from database.ai_center_settings_queries import get_effective_settings, save_ai_center_settings

ai_center_bp = Blueprint("ai_center", __name__, url_prefix="/ai-center")


@ai_center_bp.route("/")
def index():

    if "admin_id" not in session:
        return redirect("/")

    admin_id = session["admin_id"]
    student_id = request.args.get("student_id", type=int)

    risk = compute_student_risk(admin_id, student_id) if student_id else None

    return render_template("ai_center/student_risk.html", risk=risk)


@ai_center_bp.route("/student-suggestions")
def student_suggestions():
    """JSON autocomplete source for the Student Risk Analysis search box -
    the admin picks a suggestion from here before anything is loaded;
    typing alone never selects or renders a student (see ADR-41)."""

    if "admin_id" not in session:
        return jsonify([]), 401

    matches = search_students(session["admin_id"], request.args.get("q", ""))

    return jsonify([
        {
            "student_id": m["student_id"],
            "full_name": m["full_name"],
            "mobile": m["mobile"],
            "plan_name": m.get("plan_name"),
        }
        for m in matches
    ])


def _parse_settings_form(form):
    """Parses+validates the Settings form. Returns (data, error) - exactly
    one of the two is not None, so the caller never has to guess which."""

    fields = (
        "weight_payment_delay", "weight_renewal_history", "weight_membership_duration",
        "high_risk_max", "low_risk_min",
    )

    try:
        data = {field: int(form.get(field, "")) for field in fields}
    except ValueError:
        return None, "Please enter a whole number (no decimals) in every field."

    if any(value < 0 or value > 100 for value in data.values()):
        return None, "Every number must be between 0 and 100."

    weight_sum = (
        data["weight_payment_delay"]
        + data["weight_renewal_history"]
        + data["weight_membership_duration"]
    )
    if weight_sum != 100:
        return None, f"The three percentages under \"What Affects the Score\" must add up to 100% (they currently add up to {weight_sum}%)."

    if data["high_risk_max"] >= data["low_risk_min"]:
        return None, "The High Risk number must be lower than the Low Risk number."

    return data, None


@ai_center_bp.route("/settings", methods=["GET", "POST"])
def settings():

    if "admin_id" not in session:
        return redirect("/")

    admin_id = session["admin_id"]

    if request.method == "POST":
        data, error = _parse_settings_form(request.form)
        if error:
            flash(error, "danger")
            return redirect(url_for("ai_center.settings"))

        try:
            save_ai_center_settings(admin_id, data)
            flash("Settings saved.", "success")
        except APIError:
            flash(
                "Couldn't save - this Supabase project is missing the "
                "ai_center_settings table. Ask your project owner to run the "
                "CREATE TABLE statement in database/supabase_migration.sql.",
                "danger",
            )
        return redirect(url_for("ai_center.settings"))

    return render_template(
        "ai_center/settings.html",
        settings=get_effective_settings(admin_id),
    )
