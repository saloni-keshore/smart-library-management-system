import csv
import io
import os
import re
import secrets
import sqlite3
from datetime import datetime

from flask import (
    Blueprint, render_template, request, redirect, url_for, flash, session,
    current_app, jsonify, send_file, Response
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from postgrest.exceptions import APIError

from database.db import get_connection, DATABASE_PATH
from database.supabase_client import get_supabase_client
from database.settings_queries import (
    get_library_settings, save_library_settings, clear_library_logo
)
from database.membership_settings_queries import (
        get_membership_settings,
        save_membership_settings,
    )
from database.receipt_settings_queries import (
    get_receipt_settings, save_receipt_settings
)
from database.notification_settings_queries import (
    get_notification_settings, save_notification_settings
)
from database.backup_queries import get_backup_info, record_backup
from database.security_settings_queries import (
    get_security_settings, save_security_settings
)
from routes.auth import validate_password



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
    "auto_expiry": ("Auto Expiry", "boolean"),
    "allow_early_renewal": ("Allow Early Renewal", "boolean"),
}
# reminder_days/send_reminders moved to Settings > Notification Settings
# (library_settings.reminder_*/notify_* columns) - see
# docs/11_FUTURE_WORK.md. Membership Settings only displays them read-only.

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
    "auto_expiry": 1,
    "allow_early_renewal": 1,
}

RECEIPT_PREFIX_PATTERN = re.compile(r"^[A-Za-z0-9-]{1,10}$")

PAPER_SIZE_LABELS = {
    "A4": "A4",
    "thermal_80mm": "Thermal 80mm",
    "thermal_58mm": "Thermal 58mm",
}

RECEIPT_SETTING_FIELDS = {
    "receipt_prefix": ("Receipt Prefix", "text"),
    "next_receipt_number": ("Starting Receipt Number", "number"),
    "auto_increment_receipt": ("Auto Increment Receipt Number", "boolean"),
    "print_logo": ("Print Logo", "boolean"),
    "print_stamp": ("Print Stamp", "boolean"),
    "print_signature": ("Print Signature", "boolean"),
    "paper_size": ("Paper Size", "paper_size"),
    "auto_print": ("Auto Print After Payment", "boolean"),
    "open_pdf_after_save": ("Open PDF After Save", "boolean"),
    "duplicate_copy": ("Print Duplicate Copy", "boolean"),
    "auto_email": ("Auto Email Receipt", "boolean"),
}

RECEIPT_SETTING_DEFAULTS = {
    "receipt_prefix": "LIB",
    "next_receipt_number": 1001,
    "auto_increment_receipt": 1,
    "print_logo": 1,
    "print_stamp": 1,
    "print_signature": 1,
    "paper_size": "A4",
    "auto_print": 0,
    "open_pdf_after_save": 1,
    "duplicate_copy": 0,
    "auto_email": 0,
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


def _format_receipt_setting(value, value_type):
    if value_type == "boolean":
        return "Enabled" if int(value) else "Disabled"
    if value_type == "paper_size":
        return PAPER_SIZE_LABELS.get(value, value)
    if value_type == "number":
        return str(int(value))
    return str(value)


def _build_receipt_changes(existing, submitted):
    """Return display-ready changes while comparing normalized values."""

    previous = (
        {field: existing[field] for field in RECEIPT_SETTING_FIELDS}
        if existing else RECEIPT_SETTING_DEFAULTS
    )
    changes = []

    for field, (label, value_type) in RECEIPT_SETTING_FIELDS.items():
        old_value = previous[field]
        new_value = submitted[field]

        if value_type in ("text", "paper_size"):
            normalized_old, normalized_new = str(old_value), str(new_value)
        elif value_type == "number":
            normalized_old, normalized_new = int(old_value), int(new_value)
        else:
            normalized_old, normalized_new = int(old_value), int(new_value)

        if normalized_old != normalized_new:
            changes.append({
                "setting": label,
                "previous": _format_receipt_setting(old_value, value_type),
                "new": _format_receipt_setting(new_value, value_type),
            })

    return changes


NOTIFICATION_SETTING_FIELDS = {
    "reminder_7_days": ("7-Day Reminder", "boolean"),
    "reminder_3_days": ("3-Day Reminder", "boolean"),
    "reminder_1_day": ("1-Day Reminder", "boolean"),
    "notify_on_expiry_day": ("Notify On Expiry Day", "boolean"),
    "notify_after_expiry": ("Notify After Expiry", "boolean"),
    "notify_in_app": ("In-App Notifications", "boolean"),
    "notify_sms": ("SMS Notifications", "boolean"),
    "notify_email": ("Email Notifications", "boolean"),
    "notify_whatsapp": ("WhatsApp Notifications", "boolean"),
    "quiet_hours_enabled": ("Quiet Hours", "boolean"),
    "quiet_hours_start": ("Quiet Hours Start", "text"),
    "quiet_hours_end": ("Quiet Hours End", "text"),
    "quiet_hours_allow_critical": ("Allow Critical Alerts In Quiet Hours", "boolean"),
    "dash_show_badge_count": ("Show Badge Count", "boolean"),
    "dash_show_expiry_today": ("Show Expiry Today", "boolean"),
    "dash_show_expiry_tomorrow": ("Show Expiry Tomorrow", "boolean"),
    "dash_show_overdue": ("Show Overdue Students", "boolean"),
    "dash_show_pending_fees": ("Show Pending Fees", "boolean"),
    "dash_show_new_admissions": ("Show New Admissions", "boolean"),
}

NOTIFICATION_SETTING_DEFAULTS = {
    "reminder_7_days": 1,
    "reminder_3_days": 1,
    "reminder_1_day": 1,
    "notify_on_expiry_day": 1,
    "notify_after_expiry": 1,
    "notify_in_app": 1,
    "notify_sms": 0,
    "notify_email": 0,
    "notify_whatsapp": 0,
    "quiet_hours_enabled": 0,
    "quiet_hours_start": "22:00",
    "quiet_hours_end": "07:00",
    "quiet_hours_allow_critical": 1,
    "dash_show_badge_count": 1,
    "dash_show_expiry_today": 1,
    "dash_show_expiry_tomorrow": 1,
    "dash_show_overdue": 1,
    "dash_show_pending_fees": 1,
    "dash_show_new_admissions": 1,
}


def _format_notification_setting(value, value_type):
    if value_type == "boolean":
        return "Enabled" if int(value) else "Disabled"
    return str(value)


def _build_notification_changes(existing, submitted):
    """Return display-ready changes while comparing normalized values."""

    previous = (
        {field: existing[field] for field in NOTIFICATION_SETTING_FIELDS}
        if existing else NOTIFICATION_SETTING_DEFAULTS
    )
    changes = []

    for field, (label, value_type) in NOTIFICATION_SETTING_FIELDS.items():
        old_value = previous[field]
        new_value = submitted[field]

        if value_type == "boolean":
            normalized_old, normalized_new = int(old_value), int(new_value)
        else:
            normalized_old, normalized_new = str(old_value), str(new_value)

        if normalized_old != normalized_new:
            changes.append({
                "setting": label,
                "previous": _format_notification_setting(old_value, value_type),
                "new": _format_notification_setting(new_value, value_type),
            })

    return changes


def _format_file_size(size_bytes):
    size = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024


SESSION_TIMEOUT_OPTIONS = {15: "15 minutes", 30: "30 minutes", 60: "60 minutes", 0: "Never"}

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
        notification_settings=get_notification_settings(admin_id),
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
            if upload and upload.filename and not _allowed_upload(upload):
                errors[field_name] = "Only valid PNG, JPG, JPEG or WEBP images are allowed."

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

@setting_bp.route("/receipt", methods=["GET", "POST"])
def receipt_settings():

    if "admin_id" not in session:
        return redirect("/")

    admin_id = session["admin_id"]
    existing = get_receipt_settings(admin_id)

    if existing is None:
        flash(
            "Please complete your Library Profile before configuring receipt settings.",
            "info"
        )
        return redirect(url_for("setting.library_profile"))

    if request.method == "POST":

        receipt_prefix = request.form.get("receipt_prefix", "").strip().upper()
        paper_size = request.form.get("paper_size", "A4").strip()
        receipt_footer = request.form.get("receipt_footer", "").strip()

        errors = []

        if not receipt_prefix:
            errors.append("Receipt prefix is required.")
        elif not RECEIPT_PREFIX_PATTERN.match(receipt_prefix):
            errors.append(
                "Receipt prefix must be up to 10 characters: letters, numbers or dash only."
            )

        if paper_size not in PAPER_SIZE_LABELS:
            errors.append("Select a valid paper size.")

        try:
            next_receipt_number = int(request.form.get("next_receipt_number", "0").strip())
            if next_receipt_number <= 0:
                errors.append("Starting receipt number must be greater than zero.")
        except (TypeError, ValueError):
            errors.append("Starting receipt number must be a number.")
            next_receipt_number = None

        if errors:
            for error in errors:
                flash(error, "danger")
            return redirect(url_for("setting.receipt_settings"))

        data = {
            "receipt_prefix": receipt_prefix,
            "next_receipt_number": next_receipt_number,
            "auto_increment_receipt":
                1 if request.form.get("auto_increment_receipt") else 0,
            "print_logo":
                1 if request.form.get("print_logo") else 0,
            "print_stamp":
                1 if request.form.get("print_stamp") else 0,
            "print_signature":
                1 if request.form.get("print_signature") else 0,
            "paper_size": paper_size,
            "auto_print":
                1 if request.form.get("auto_print") else 0,
            "open_pdf_after_save":
                1 if request.form.get("open_pdf_after_save") else 0,
            "duplicate_copy":
                1 if request.form.get("duplicate_copy") else 0,
            "auto_email":
                1 if request.form.get("auto_email") else 0,
            "receipt_footer": receipt_footer or None,
        }

        changes = _build_receipt_changes(existing, data)
        save_receipt_settings(admin_id, data)

        session["receipt_change_summary"] = {
            "changes": changes,
            "updated_by": session.get("username", "Admin"),
            "updated_on": datetime.now().strftime("%d %b %Y %I:%M %p"),
        }

        flash(
            "✓ Receipt Settings saved successfully. "
            "These settings will be applied to all future payment receipts.",
            "success"
        )
        return redirect(url_for("setting.receipt_settings"))

    change_summary = session.pop("receipt_change_summary", None)

    return render_template(
        "settings/receipt_settings.html",
        settings=existing,
        paper_sizes=PAPER_SIZE_LABELS,
        changes=change_summary["changes"] if change_summary else None,
        updated_by=change_summary["updated_by"] if change_summary else None,
        updated_on=change_summary["updated_on"] if change_summary else None,
    )

@setting_bp.route("/notification", methods=["GET", "POST"])
def notification_settings():

    if "admin_id" not in session:
        return redirect("/")

    admin_id = session["admin_id"]
    existing = get_notification_settings(admin_id)

    if existing is None:
        flash(
            "Please complete your Library Profile before configuring notification settings.",
            "info"
        )
        return redirect(url_for("setting.library_profile"))

    if request.method == "POST":

        def time_value(name, default):
            raw_value = request.form.get(name, default).strip()
            try:
                datetime.strptime(raw_value, "%H:%M")
            except ValueError:
                raise ValueError(f"{name.replace('_', ' ').title()} must be a valid time.")
            return raw_value

        def flag(name):
            return 1 if request.form.get(name) else 0

        try:
            data = {
                "reminder_7_days": flag("reminder_7_days"),
                "reminder_3_days": flag("reminder_3_days"),
                "reminder_1_day": flag("reminder_1_day"),
                "notify_on_expiry_day": flag("notify_on_expiry_day"),
                "notify_after_expiry": flag("notify_after_expiry"),

                "notify_in_app": flag("notify_in_app"),
                "notify_sms": flag("notify_sms"),
                "notify_email": flag("notify_email"),
                "notify_whatsapp": flag("notify_whatsapp"),

                "quiet_hours_enabled": flag("quiet_hours_enabled"),
                "quiet_hours_start": time_value("quiet_hours_start", "22:00"),
                "quiet_hours_end": time_value("quiet_hours_end", "07:00"),
                "quiet_hours_allow_critical": flag("quiet_hours_allow_critical"),

                "dash_show_badge_count": flag("dash_show_badge_count"),
                "dash_show_expiry_today": flag("dash_show_expiry_today"),
                "dash_show_expiry_tomorrow": flag("dash_show_expiry_tomorrow"),
                "dash_show_overdue": flag("dash_show_overdue"),
                "dash_show_pending_fees": flag("dash_show_pending_fees"),
                "dash_show_new_admissions": flag("dash_show_new_admissions"),
            }
        except ValueError as error:
            flash(str(error), "danger")
            return redirect(url_for("setting.notification_settings"))

        changes = _build_notification_changes(existing, data)
        save_notification_settings(admin_id, data)

        session["notification_change_summary"] = {
            "changes": changes,
            "updated_by": session.get("username", "Admin"),
            "updated_on": datetime.now().strftime("%d %b %Y %I:%M %p"),
        }

        flash("Notification settings saved successfully.", "success")
        return redirect(url_for("setting.notification_settings"))

    change_summary = session.pop("notification_change_summary", None)

    return render_template(
        "settings/notification_settings.html",
        settings=existing,
        changes=change_summary["changes"] if change_summary else None,
        updated_by=change_summary["updated_by"] if change_summary else None,
        updated_on=change_summary["updated_on"] if change_summary else None,
    )


# ==========================================================
# Staff & User Access (placeholder)
# ==========================================================

@setting_bp.route("/staff")
def staff_access():

    if "admin_id" not in session:
        return redirect("/")

    return render_template("settings/staff_access.html")


# ==========================================================
# Data & Backup
# ==========================================================

@setting_bp.route("/backup")
def data_backup():

    if "admin_id" not in session:
        return redirect("/")

    admin_id = session["admin_id"]

    db_size = _format_file_size(os.path.getsize(DATABASE_PATH)) if os.path.exists(DATABASE_PATH) else "Unknown"
    backup_info = get_backup_info(admin_id)
    backups_dir = os.path.join(current_app.root_path, "backups")

    return render_template(
        "settings/data_backup.html",
        db_size=db_size,
        last_backup_at=backup_info["last_backup_at"] if backup_info else None,
        backup_location=backups_dir,
    )


@setting_bp.route("/backup/export-csv")
def backup_export_csv():

    if "admin_id" not in session:
        return redirect("/")

    admin_id = session["admin_id"]

    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM students WHERE admin_id = ? ORDER BY student_id",
        (admin_id,)
    )
    rows = cursor.fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)

    if rows:
        writer.writerow(rows[0].keys())
        for row in rows:
            writer.writerow(list(row))
    else:
        writer.writerow([
            "student_id", "full_name", "mobile", "address", "id_proof",
            "purpose", "shift", "join_date", "status"
        ])

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition":
                f"attachment; filename=students_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        }
    )


@setting_bp.route("/backup/create", methods=["POST"])
def backup_create():

    if "admin_id" not in session:
        return redirect("/")

    admin_id = session["admin_id"]

    backups_dir = os.path.join(current_app.root_path, "backups")
    os.makedirs(backups_dir, exist_ok=True)

    backup_filename = f"library_backup_{admin_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    backup_path = os.path.join(backups_dir, backup_filename)

    # SQLite's backup API produces a consistent snapshot even while WAL mode
    # has uncheckpointed writes; copying the database file does not.
    source = get_connection()
    target = sqlite3.connect(backup_path)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    record_backup(admin_id, backup_filename)

    return send_file(backup_path, as_attachment=True, download_name=backup_filename)


# ==========================================================
# Security Settings
# ==========================================================

@setting_bp.route("/security", methods=["GET", "POST"])
def security_settings():

    if "admin_id" not in session:
        return redirect("/")

    admin_id = session["admin_id"]

    if request.method == "POST":

        form_type = request.form.get("form_type")

        if form_type == "password":
            current_password = request.form.get("current_password", "")
            new_password = request.form.get("new_password", "")
            confirm_password = request.form.get("confirm_password", "")

            supabase = get_supabase_client()
            try:
                response = supabase.table("admins").select("*").eq("admin_id", admin_id).execute()
                admin = response.data[0] if response.data else None
            except APIError:
                admin = None

            if not admin or not check_password_hash(admin["password"], current_password):
                flash("Current password is incorrect.", "danger")
                return redirect(url_for("setting.security_settings"))

            if new_password != confirm_password:
                flash("New passwords do not match.", "danger")
                return redirect(url_for("setting.security_settings"))

            error = validate_password(new_password)
            if error:
                flash(error, "danger")
                return redirect(url_for("setting.security_settings"))

            try:
                supabase.table("admins").update(
                    {"password": generate_password_hash(new_password)}
                ).eq("admin_id", admin_id).execute()
            except APIError:
                flash("Something went wrong. Please try again.", "danger")
                return redirect(url_for("setting.security_settings"))

            flash("Password changed successfully.", "success")
            return redirect(url_for("setting.security_settings"))

        try:
            session_timeout_minutes = int(request.form.get("session_timeout_minutes", "60"))
        except (TypeError, ValueError):
            session_timeout_minutes = 60

        if session_timeout_minutes not in SESSION_TIMEOUT_OPTIONS:
            session_timeout_minutes = 60

        data = {
            "session_timeout_minutes": session_timeout_minutes,
            "remember_me_enabled": 1 if request.form.get("remember_me_enabled") else 0,
            "login_notifications_enabled": 1 if request.form.get("login_notifications_enabled") else 0,
        }

        save_security_settings(admin_id, data)
        flash("Security preferences saved successfully.", "success")
        return redirect(url_for("setting.security_settings"))

    settings = get_security_settings(admin_id)

    return render_template(
        "settings/security_settings.html",
        settings=settings,
        timeout_options=SESSION_TIMEOUT_OPTIONS,
    )


def _allowed_file(filename):
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return extension in ALLOWED_EXTENSIONS


def _allowed_upload(file):
    if not _allowed_file(file.filename):
        return False
    header = file.stream.read(512)
    file.stream.seek(0)
    return (
        header.startswith(b"\x89PNG\r\n\x1a\n")
        or header.startswith(b"\xff\xd8\xff")
        or (header.startswith(b"RIFF") and header[8:12] == b"WEBP")
    )


def _save_upload(file, admin_id, field_name):
    """Save an uploaded file under static/uploads/settings/ and return the
    path to store in the database (relative to static/)."""

    upload_dir = os.path.join(current_app.static_folder, "uploads", "settings")
    os.makedirs(upload_dir, exist_ok=True)

    original_name = secure_filename(file.filename)
    stored_name = f"{field_name}_{admin_id}_{secrets.token_hex(8)}_{original_name}"
    file.save(os.path.join(upload_dir, stored_name))

    return f"uploads/settings/{stored_name}"
