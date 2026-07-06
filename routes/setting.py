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

setting_bp = Blueprint(
    "setting",
    __name__,
    url_prefix="/settings"
)

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@setting_bp.route("/")
def index():
    if "admin_id" not in session:
        return redirect("/")

    return render_template("settings/index.html")


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
