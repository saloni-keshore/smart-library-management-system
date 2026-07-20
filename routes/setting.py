import os
import re
from datetime import datetime

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, session,
    current_app, jsonify
)
from werkzeug.utils import secure_filename

from database.settings_queries import (
    get_library_settings, save_library_settings, clear_library_logo
)
from database.membership_settings_queries import (
        get_membership_settings,
        save_membership_settings,
    )



setting_bp = Blueprint(
    "setting",
    __name__,
    url_prefix="/settings"
)

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

MEMBERSHIP_SETTING_FIELDS = {
    "monthly_fee": ("Monthly Plan Fee", "currency"),
    "monthly_days": ("Monthly Plan Days", "number"),
    "quarterly_fee": ("Quarterly Plan Fee", "currency"),
    "quarterly_days": ("Quarterly Plan Days", "number"),
    "half_yearly_fee": ("Half-yearly Plan Fee", "currency"),
    "half_yearly_days": ("Half-yearly Plan Days", "number"),
    "yearly_fee": ("Yearly Plan Fee", "currency"),
    "yearly_days": ("Yearly Plan Days", "number"),
    "admission_fee": ("Admission Fee", "currency"),
    "late_fee_per_day": ("Late Fee Per Day", "currency"),
    "renewal_grace_days": ("Renewal Grace Days", "number"),
    "reminder_days": ("Reminder Days", "number"),
    "auto_expiry": ("Auto Expiry", "boolean"),
    "allow_early_renewal": ("Allow Early Renewal", "boolean"),
    "send_reminders": ("Send Reminders", "boolean"),
}

MEMBERSHIP_SETTING_DEFAULTS = {
    "monthly_fee": 0.0,
    "monthly_days": 30,
    "quarterly_fee": 0.0,
    "quarterly_days": 90,
    "half_yearly_fee": 0.0,
    "half_yearly_days": 180,
    "yearly_fee": 0.0,
    "yearly_days": 365,
    "admission_fee": 0.0,
    "late_fee_per_day": 0.0,
    "renewal_grace_days": 7,
    "reminder_days": 3,
    "auto_expiry": 1,
    "allow_early_renewal": 1,
    "send_reminders": 1,
}


def _format_membership_setting(value, value_type):
    if value_type == "currency":
        return f"₹{float(value):g}"
    if value_type == "boolean":
        return "Enabled" if int(value) else "Disabled"
    return str(int(value))


def _build_membership_changes(existing, submitted):
    """Return display-ready changes while comparing normalized values."""

    previous = (
        {field: existing[field] for field in MEMBERSHIP_SETTING_FIELDS}
        if existing else MEMBERSHIP_SETTING_DEFAULTS
    )
    changes = []

    for field, (label, value_type) in MEMBERSHIP_SETTING_FIELDS.items():
        old_value = previous[field]
        new_value = submitted[field]
        normalized_old = float(old_value) if value_type == "currency" else int(old_value)
        normalized_new = float(new_value) if value_type == "currency" else int(new_value)

        if normalized_old != normalized_new:
            changes.append({
                "setting": label,
                "previous": _format_membership_setting(old_value, value_type),
                "new": _format_membership_setting(new_value, value_type),
            })

    return changes

# ==========================================================
# Settings Home
# ==========================================================

@setting_bp.route("/")
def index():

    if "admin_id" not in session:
        return redirect("/")

    return render_template("settings/index.html")

# ==========================================================
# Membership Settings

@setting_bp.route("/membership", methods=["GET", "POST"])
def membership_settings():

    if "admin_id" not in session:
        return redirect("/")

    admin_id = session["admin_id"]

    if request.method == "POST":

        existing = get_membership_settings(admin_id)

        def number(name, default, integer=False):
            raw_value = request.form.get(name, str(default)).strip()
            try:
                value = int(raw_value) if integer else float(raw_value)
            except (TypeError, ValueError):
                raise ValueError(f"{name.replace('_', ' ').title()} must be a number.")
            if value < 0:
                raise ValueError(f"{name.replace('_', ' ').title()} cannot be negative.")
            return value

        try:
            data = {

                "monthly_fee": number("monthly_fee", 0),
                "monthly_days": number("monthly_days", 30, integer=True),

                "quarterly_fee": number("quarterly_fee", 0),
                "quarterly_days": number("quarterly_days", 90, integer=True),

                "half_yearly_fee": number("half_yearly_fee", 0),
                "half_yearly_days": number("half_yearly_days", 180, integer=True),

                "yearly_fee": number("yearly_fee", 0),
                "yearly_days": number("yearly_days", 365, integer=True),

                "admission_fee": number("admission_fee", 0),
                "late_fee_per_day": number("late_fee_per_day", 0),
                "renewal_grace_days": number("renewal_grace_days", 7, integer=True),

                "auto_expiry":
                    1 if request.form.get("auto_expiry") else 0,

                "allow_early_renewal":
                    1 if request.form.get("allow_early_renewal") else 0,

                "send_reminders":
                    1 if request.form.get("send_reminders") else 0,

                "reminder_days": number("reminder_days", 3, integer=True),
            }
        except ValueError as error:
            flash(str(error), "danger")
            return redirect(url_for("setting.membership_settings"))

        changes = _build_membership_changes(existing, data)
        save_membership_settings(admin_id, data)

        session["membership_change_summary"] = {
            "changes": changes,
            "updated_by": session.get("username", "Admin"),
            "updated_on": datetime.now().strftime("%d %b %Y %I:%M %p"),
        }

        flash(
            "Membership settings updated successfully.",
            "success"
        )

        return redirect(
            url_for("setting.membership_settings")
        )

    settings = get_membership_settings(admin_id)
    change_summary = session.pop("membership_change_summary", None)

    return render_template(
        "settings/membership_settings.html",
        settings=settings,
        changes=change_summary["changes"] if change_summary else None,
        updated_by=change_summary["updated_by"] if change_summary else None,
        updated_on=change_summary["updated_on"] if change_summary else None,
    )


@setting_bp.route("/library", methods=["GET", "POST"])
def library_profile():
    if "admin_id" not in session:
        return redirect("/")
    admin_id = session["admin_id"]

    existing = get_library_settings(admin_id)
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    if request.method == "POST":
        library_name = request.form.get("library_name", "").strip()
        owner_name = request.form.get("owner_name", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        address = request.form.get("address", "").strip()
        city = request.form.get("city", "").strip()
        state = request.form.get("state", "").strip()
        pincode = request.form.get("pincode", "").strip()
        opening_time = request.form.get("opening_time", "").strip()
        closing_time = request.form.get("closing_time", "").strip()
        weekly_holiday = request.form.get("weekly_holiday", "").strip()
        receipt_footer = request.form.get("receipt_footer", "").strip()
        remove_logo = request.form.get("remove_logo") == "1"

        errors = {}

        if not library_name:
            errors["library_name"] = "Library name is required."

        if not owner_name:
            errors["owner_name"] = "Owner name is required."

        if not phone:
            errors["phone"] = "Phone number is required."
        elif not phone.isdigit():
            errors["phone"] = "Phone number must contain digits only."

        if email and not EMAIL_PATTERN.match(email):
            errors["email"] = "Enter a valid email address."

        if opening_time and closing_time:
            try:
                opens = datetime.strptime(opening_time, "%H:%M")
                closes = datetime.strptime(closing_time, "%H:%M")
                if opens >= closes:
                    errors["closing_time"] = "Opening time must be before closing time."
            except ValueError:
                errors["closing_time"] = "Opening and closing time must be valid times."

        logo_file = request.files.get("logo")
        stamp_file = request.files.get("stamp")
        signature_file = request.files.get("signature")

        for field_name, upload in (("logo", logo_file), ("stamp", stamp_file), ("signature", signature_file)):
            if upload and upload.filename and not _allowed_file(upload.filename):
                errors[field_name] = "Only PNG, JPG, JPEG or WEBP images are allowed."

        if errors:
            message = "Please fix the highlighted fields."
            if is_ajax:
                return jsonify(success=False, message=message, errors=errors), 400

            flash(message, "danger")
            return redirect(url_for("setting.library_profile"))

        if logo_file and logo_file.filename:
            logo_path = _save_upload(logo_file, admin_id, "logo")
        elif remove_logo:
            logo_path = None
        else:
            logo_path = existing["logo_path"] if existing else None

        if stamp_file and stamp_file.filename:
            stamp_path = _save_upload(stamp_file, admin_id, "stamp")
        else:
            stamp_path = existing["stamp_path"] if existing else None

        if signature_file and signature_file.filename:
            signature_path = _save_upload(signature_file, admin_id, "signature")
        else:
            signature_path = existing["signature_path"] if existing else None

        data = {
            "library_name": library_name,
            "owner_name": owner_name,
            "phone": phone,
            "email": email or None,
            "address": address or None,
            "city": city or None,
            "state": state or None,
            "pincode": pincode or None,
            "opening_time": opening_time or None,
            "closing_time": closing_time or None,
            "weekly_holiday": weekly_holiday or None,
            "logo_path": logo_path,
            "stamp_path": stamp_path,
            "signature_path": signature_path,
            "receipt_footer": receipt_footer or None,
        }

        save_library_settings(admin_id, data)

        if is_ajax:
            saved = get_library_settings(admin_id)
            return jsonify(
                success=True,
                message="Library Profile Updated Successfully",
                settings={
                    "library_name": saved["library_name"],
                    "registration_date": saved["created_at"][:16],
                    "last_updated": saved["updated_at"][:16],
                    "logo_url": url_for("static", filename=saved["logo_path"]) if saved["logo_path"] else None,
                    "stamp_filename": saved["stamp_path"].split("/")[-1] if saved["stamp_path"] else None,
                    "signature_filename": saved["signature_path"].split("/")[-1] if saved["signature_path"] else None,
                }
            )

        flash("Library profile saved successfully.", "success")
        return redirect(url_for("setting.library_profile"))

    library_id = f"LIB{admin_id:04d}"
    return render_template(
        "settings/library_profile.html",
        settings=existing,
        library_id=library_id
    )


@setting_bp.route("/library/remove-logo", methods=["POST"])
def remove_library_logo():
    if "admin_id" not in session:
        return jsonify(success=False, message="Please log in again."), 401
    admin_id = session["admin_id"]

    existing = get_library_settings(admin_id)

    if existing and existing["logo_path"]:
        file_path = os.path.join(current_app.static_folder, existing["logo_path"])
        if os.path.exists(file_path):
            os.remove(file_path)

        clear_library_logo(admin_id)

    return jsonify(success=True, message="Logo removed successfully.")

@setting_bp.route("/receipt")
def receipt_settings():

    if "admin_id" not in session:
        return redirect("/")

    flash("Receipt Settings module coming soon.", "info")

    return redirect(url_for("setting.index"))

@setting_bp.route("/notification")
def notification_settings():

    if "admin_id" not in session:
        return redirect("/")

    flash("Notification Settings coming soon.", "info")
    return redirect(url_for("setting.index"))

def _allowed_file(filename):
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return extension in ALLOWED_EXTENSIONS


def _save_upload(file, admin_id, field_name):
    """Save an uploaded file under static/uploads/settings/ and return the
    path to store in the database (relative to static/)."""

    upload_dir = os.path.join(current_app.static_folder, "uploads", "settings")
    os.makedirs(upload_dir, exist_ok=True)

    stored_name = f"{field_name}_{admin_id}_{secure_filename(file.filename)}"
    file.save(os.path.join(upload_dir, stored_name))

    return f"uploads/settings/{stored_name}"
