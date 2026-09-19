import csv
import io
import json
import re
import secrets
from datetime import datetime

from flask import (
    Blueprint, current_app, render_template, request, redirect, url_for, flash, session,
    jsonify, send_file, Response
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from postgrest.exceptions import APIError

from database.supabase_client import get_supabase_client
from database.branding_storage import upload_branding_image, delete_branding_image
from database.settings_queries import (
    get_library_settings, save_library_settings, clear_library_logo
)
from database.bi_queries import DEFAULT_SHIFT_CAPACITY
from database.membership_settings_queries import (
        get_membership_settings,
        save_membership_settings,
    )
from database.shift_slots_queries import (
    get_shift_slots,
    get_shift_slot,
    create_shift_slot,
    update_shift_slot,
    set_shift_slot_active,
    HOURS_LABELS,
)
from database.membership_charges_queries import get_charge_config
from database.membership_queries import describe_time_buckets
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
from utils.branding import branding_src
from utils.security import login_required, rate_limited
from utils.normalization import (
    normalize_name,
    normalize_phone,
    normalize_location,
    normalize_free_text,
    normalize_category,
)



setting_bp = Blueprint(
    "setting",
    __name__,
    url_prefix="/settings"
)

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class UploadStorageUnavailable(Exception):
    """Raised by _save_upload() when Supabase Storage can't be reached to
    store a branding image. Callers catch this and save the rest of the
    form instead of returning a 500. See ADR-57 / TD-73."""

MEMBERSHIP_SETTING_FIELDS = {
    "monthly_fee": ("Monthly Plan Fee", "currency"),
    "monthly_days": ("Monthly Plan Days", "number"),
    "quarterly_fee": ("Quarterly Plan Fee", "currency"),
    "quarterly_days": ("Quarterly Plan Days", "number"),
    "half_yearly_fee": ("Half-yearly Plan Fee", "currency"),
    "half_yearly_days": ("Half-yearly Plan Days", "number"),
    "yearly_fee": ("Yearly Plan Fee", "currency"),
    "yearly_days": ("Yearly Plan Days", "number"),
    "admission_fee": ("Registration Fee", "currency"),
    "late_fee_per_day": ("Late Fee Per Day", "currency"),
    "renewal_grace_days": ("Renewal Grace Days", "number"),
    "auto_expiry": ("Auto Expiry", "boolean"),
    "allow_early_renewal": ("Allow Early Renewal", "boolean"),
    # Extra charges (ADR-66) - amount + a compulsory/optional flag each.
    "seat_reservation_fee": ("Seat Reservation Fee (monthly)", "currency"),
    "locker_fee": ("Locker Fee (monthly)", "currency"),
    "security_deposit_amount": ("Security Deposit", "currency"),
    "registration_compulsory": ("Registration Fee Compulsory", "boolean"),
    "seat_reservation_compulsory": ("Seat Reservation Compulsory", "boolean"),
    "locker_compulsory": ("Locker Compulsory", "boolean"),
    "security_deposit_compulsory": ("Security Deposit Compulsory", "boolean"),
    # Walk-in / Day Pass (ADR-71)
    "day_pass_fee": ("Day Pass Fee (per visit)", "currency"),
    "day_pass_days": ("Day Pass Days", "number"),
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
    "seat_reservation_fee": 0.0,
    "locker_fee": 0.0,
    "security_deposit_amount": 0.0,
    "registration_compulsory": 1,
    "seat_reservation_compulsory": 0,
    "locker_compulsory": 0,
    "security_deposit_compulsory": 1,
    "day_pass_fee": 0.0,
    "day_pass_days": 1,
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
        {
            field: existing.get(field, MEMBERSHIP_SETTING_DEFAULTS[field])
            for field in MEMBERSHIP_SETTING_FIELDS
        }
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


SESSION_TIMEOUT_OPTIONS = {15: "15 minutes", 30: "30 minutes", 60: "60 minutes", 0: "Never"}

# ==========================================================
# Settings Home
# ==========================================================

@setting_bp.route("/")
@login_required
def index():

    return render_template("settings/index.html")

# ==========================================================
# Membership Settings

@setting_bp.route("/membership", methods=["GET", "POST"])
@login_required
def membership_settings():

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

                # Extra charges (ADR-66)
                "seat_reservation_fee": number("seat_reservation_fee", 0),
                "locker_fee": number("locker_fee", 0),
                "security_deposit_amount": number("security_deposit_amount", 0),
                "registration_compulsory":
                    1 if request.form.get("registration_compulsory") else 0,
                "seat_reservation_compulsory":
                    1 if request.form.get("seat_reservation_compulsory") else 0,
                "locker_compulsory":
                    1 if request.form.get("locker_compulsory") else 0,
                "security_deposit_compulsory":
                    1 if request.form.get("security_deposit_compulsory") else 0,

                # Walk-in / Day Pass (ADR-71)
                "day_pass_fee": number("day_pass_fee", 0),
                "day_pass_days": number("day_pass_days", 1, integer=True),
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
        charge_config=get_charge_config(settings),
        notification_settings=get_notification_settings(admin_id),
        changes=change_summary["changes"] if change_summary else None,
        updated_by=change_summary["updated_by"] if change_summary else None,
        updated_on=change_summary["updated_on"] if change_summary else None,
    )


# ==========================================================
# Shift Slots (ADR-65)
# ==========================================================

_VALID_SLOT_BUCKETS = {"", "Morning", "Afternoon", "Evening", "Night", "Full Day"}


def _parse_shift_slot_form(form):
    """Validate the Shift Slots add/edit form into a shift_slots payload.
    Raises ValueError with a user-facing message on bad input."""

    name = normalize_free_text(form.get("name", "")).strip()
    if not name:
        raise ValueError("Slot name is required.")

    def _time(field):
        raw = (form.get(field) or "").strip()
        if not raw:
            return None
        try:
            datetime.strptime(raw, "%H:%M")
        except ValueError:
            raise ValueError(f"{field.replace('_', ' ').title()} must be a valid HH:MM time.")
        return raw

    def _amount(field):
        raw = (form.get(field) or "0").strip() or "0"
        try:
            value = float(raw)
        except ValueError:
            raise ValueError(f"{field.replace('_', ' ').title()} must be a number.")
        if value < 0:
            raise ValueError(f"{field.replace('_', ' ').title()} cannot be negative.")
        return value

    hours_label = form.get("hours_label", "Custom")
    if hours_label not in HOURS_LABELS:
        hours_label = "Custom"

    time_bucket = (form.get("time_bucket") or "").strip()
    if time_bucket not in _VALID_SLOT_BUCKETS:
        raise ValueError("Please choose a valid time bucket (or leave it on Auto).")

    try:
        sort_order = int((form.get("sort_order") or "0").strip() or "0")
    except ValueError:
        sort_order = 0

    return {
        "name": name,
        "start_time": _time("start_time"),
        "end_time": _time("end_time"),
        "hours_label": hours_label,
        "monthly_fee": _amount("monthly_fee"),
        "time_bucket": time_bucket,
        "sort_order": sort_order,
    }


@setting_bp.route("/shift-slots", methods=["GET", "POST"])
@login_required
def shift_slots():

    admin_id = session["admin_id"]

    if request.method == "POST":
        try:
            payload = _parse_shift_slot_form(request.form)
        except ValueError as error:
            flash(str(error), "danger")
            return redirect(url_for("setting.shift_slots"))

        try:
            create_shift_slot(admin_id, payload)
        except APIError:
            flash(
                "Shift slots aren't available yet on this system - the database "
                "needs a one-time update. Contact your administrator.",
                "danger",
            )
            return redirect(url_for("setting.shift_slots"))

        flash(f"Shift slot '{payload['name']}' added.", "success")
        return redirect(url_for("setting.shift_slots"))

    return render_template(
        "settings/shift_slots.html",
        slots=get_shift_slots(admin_id, include_inactive=True),
        hours_labels=HOURS_LABELS,
        bucket_windows=describe_time_buckets(),
    )


@setting_bp.route("/shift-slots/<int:slot_id>/edit", methods=["POST"])
@login_required
def shift_slot_edit(slot_id):

    admin_id = session["admin_id"]

    if get_shift_slot(admin_id, slot_id) is None:
        flash("Shift slot not found.", "danger")
        return redirect(url_for("setting.shift_slots"))

    try:
        payload = _parse_shift_slot_form(request.form)
    except ValueError as error:
        flash(str(error), "danger")
        return redirect(url_for("setting.shift_slots"))

    try:
        update_shift_slot(admin_id, slot_id, payload)
    except APIError:
        flash("Could not update the shift slot due to a database error.", "danger")
        return redirect(url_for("setting.shift_slots"))

    flash(f"Shift slot '{payload['name']}' updated.", "success")
    return redirect(url_for("setting.shift_slots"))


@setting_bp.route("/shift-slots/<int:slot_id>/toggle", methods=["POST"])
@login_required
def shift_slot_toggle(slot_id):

    admin_id = session["admin_id"]

    slot = get_shift_slot(admin_id, slot_id)
    if slot is None:
        flash("Shift slot not found.", "danger")
        return redirect(url_for("setting.shift_slots"))

    new_state = 0 if slot.get("active") else 1
    try:
        set_shift_slot_active(admin_id, slot_id, new_state)
    except APIError:
        flash("Could not update the shift slot due to a database error.", "danger")
        return redirect(url_for("setting.shift_slots"))

    flash(
        f"Shift slot '{slot['name']}' {'enabled' if new_state else 'disabled'}.",
        "success",
    )
    return redirect(url_for("setting.shift_slots"))


@setting_bp.route("/library", methods=["GET", "POST"])
@login_required
def library_profile():
    admin_id = session["admin_id"]

    existing = get_library_settings(admin_id)
    is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

    if request.method == "POST":
        library_name = request.form.get("library_name", "").strip()
        owner_name = normalize_name(request.form.get("owner_name", ""))
        phone = normalize_phone(request.form.get("phone", ""))
        email = request.form.get("email", "").strip()
        address = normalize_free_text(request.form.get("address", ""))
        city = normalize_location(request.form.get("city", ""))
        state = normalize_location(request.form.get("state", ""))
        pincode = request.form.get("pincode", "").strip()
        opening_time = request.form.get("opening_time", "").strip()
        closing_time = request.form.get("closing_time", "").strip()
        weekly_holiday = request.form.get("weekly_holiday", "").strip()
        receipt_footer = normalize_free_text(request.form.get("receipt_footer", ""))
        remove_logo = request.form.get("remove_logo") == "1"

        errors = {}

        def seat_capacity(field_name):
            raw_value = request.form.get(field_name, "").strip()
            if not raw_value:
                return DEFAULT_SHIFT_CAPACITY
            try:
                value = int(raw_value)
            except ValueError:
                errors[field_name] = "Seat capacity must be a whole number."
                return DEFAULT_SHIFT_CAPACITY
            if value < 0:
                errors[field_name] = "Seat capacity cannot be negative."
                return DEFAULT_SHIFT_CAPACITY
            return value

        morning_capacity = seat_capacity("morning_capacity")
        afternoon_capacity = seat_capacity("afternoon_capacity")
        evening_capacity = seat_capacity("evening_capacity")
        night_capacity = seat_capacity("night_capacity")

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

        # Branding-image storage is best-effort: on a read-only-filesystem
        # host (e.g. serverless) _save_upload() raises UploadStorageUnavailable
        # and we keep the previously-stored path, save every other field, and
        # tell the admin the image part didn't stick (see TD-73) instead of
        # failing the whole form with a 500.
        uploads_unavailable = False
        try:
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
        except UploadStorageUnavailable:
            uploads_unavailable = True
            logo_path = None if remove_logo else (existing["logo_path"] if existing else None)
            stamp_path = existing["stamp_path"] if existing else None
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
            "morning_capacity": morning_capacity,
            "afternoon_capacity": afternoon_capacity,
            "evening_capacity": evening_capacity,
            "night_capacity": night_capacity,
        }

        save_library_settings(admin_id, data)

        upload_warning = (
            "Your profile was saved. Image uploads aren't available on this deployment."
            if uploads_unavailable else None
        )

        if is_ajax:
            saved = get_library_settings(admin_id)
            return jsonify(
                success=True,
                message=upload_warning or "Library Profile Updated Successfully",
                warning=upload_warning,
                settings={
                    "library_name": saved["library_name"],
                    "registration_date": saved["created_at"][:16],
                    "last_updated": saved["updated_at"][:16],
                    "logo_url": branding_src(saved["logo_path"]) or None,
                    "stamp_filename": saved["stamp_path"].split("/")[-1] if saved["stamp_path"] else None,
                    "signature_filename": saved["signature_path"].split("/")[-1] if saved["signature_path"] else None,
                }
            )

        if upload_warning:
            flash(upload_warning, "warning")
        else:
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
        # Best-effort: remove the Storage object (or legacy local file).
        # A failed cleanup must not stop the DB row from being cleared.
        delete_branding_image(existing["logo_path"])
        clear_library_logo(admin_id)

    return jsonify(success=True, message="Logo removed successfully.")

@setting_bp.route("/receipt", methods=["GET", "POST"])
@login_required
def receipt_settings():

    admin_id = session["admin_id"]
    existing = get_receipt_settings(admin_id)

    if existing is None:
        flash(
            "Please complete your Library Profile before configuring receipt settings.",
            "info"
        )
        return redirect(url_for("setting.library_profile"))

    if request.method == "POST":

        receipt_prefix = normalize_category(request.form.get("receipt_prefix", ""))
        paper_size = request.form.get("paper_size", "A4").strip()
        receipt_footer = normalize_free_text(request.form.get("receipt_footer", ""))

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
@login_required
def notification_settings():

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
@login_required
def staff_access():

    return render_template("settings/staff_access.html")


# ==========================================================
# Data & Backup
# ==========================================================

# Every table with a direct admin_id column (ADR-75 gave memberships/
# payments/membership_charges/panda_messages one too, closing the previous
# gap where they could only be reached via a join) - each queried with
# .eq("admin_id", ...). This list is also what Settings > Data & Backup's
# Danger Zone (rpc_delete_tenant_data) permanently removes, so it must stay
# a complete inventory of this admin's data - see ADR-76.
_BACKUP_DIRECT_TABLES = (
    "enquiries", "students", "cashbook", "audit_log",
    "library_settings", "membership_settings", "security_settings",
    "ai_center_settings", "backup_log", "shift_slots",
    "memberships", "payments", "membership_charges",
    "panda_conversations", "panda_messages", "expenses",
)


def _collect_admin_backup_data(admin_id):
    """Every Supabase row belonging to this admin, table by table - the
    Supabase-native replacement for the old whole-file SQLite snapshot
    (ADR-32): there is no single database file left to copy, so the
    backup is now a per-table export of this admin's own rows instead."""

    supabase = get_supabase_client()
    data = {}

    admin_response = (
        supabase.table("admins")
        .select("admin_id, full_name, username, mobile, email, role, created_at")
        .eq("admin_id", admin_id)
        .execute()
    )
    data["admin_profile"] = admin_response.data[0] if admin_response.data else None

    for table in _BACKUP_DIRECT_TABLES:
        try:
            data[table] = supabase.table(table).select("*").eq("admin_id", admin_id).execute().data
        except APIError:
            # A brand-new table (ai_center_settings/panda_*/shift_slots/
            # membership_charges) not yet created on an older, un-migrated
            # project (PGRST205) - degrade to an empty list rather than
            # failing the whole export.
            data[table] = []

    return data


@setting_bp.route("/backup")
@login_required
def data_backup():

    admin_id = session["admin_id"]

    backup_info = get_backup_info(admin_id)

    return render_template(
        "settings/data_backup.html",
        last_backup_at=backup_info["last_backup_at"] if backup_info else None,
        backup_location="Downloaded to your device",
        danger_zone_ready=_backup_is_fresh(backup_info),
        danger_zone_window_hours=_DANGER_ZONE_BACKUP_WINDOW_HOURS,
        username=session.get("username"),
    )


@setting_bp.route("/backup/export-csv")
@login_required
def backup_export_csv():

    admin_id = session["admin_id"]

    # Supabase `students` (ADR-19) instead of the SQLite mirror (ADR-24).
    supabase = get_supabase_client()
    try:
        response = (
            supabase.table("students")
            .select("*")
            .eq("admin_id", admin_id)
            .order("student_id")
            .execute()
        )
        rows = response.data
    except APIError:
        rows = []

    output = io.StringIO()
    writer = csv.writer(output)

    if rows:
        writer.writerow(rows[0].keys())
        for row in rows:
            writer.writerow(list(row.values()))
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
@login_required
def backup_create():

    admin_id = session["admin_id"]

    backup_filename = f"library_backup_{admin_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    export = {
        "exported_at": datetime.now().isoformat(),
        "admin_id": admin_id,
        "tables": _collect_admin_backup_data(admin_id),
    }

    # Built and streamed from memory (no local file) so this works on a
    # read-only-filesystem host too; record_backup() only logs the filename
    # to Supabase, it never touches disk.
    payload = json.dumps(export, indent=2, default=str).encode("utf-8")
    record_backup(admin_id, backup_filename)

    return send_file(
        io.BytesIO(payload),
        mimetype="application/json",
        as_attachment=True,
        download_name=backup_filename,
    )


# Danger Zone (ADR-76): Export -> Confirm -> Archive/Delete. A recent backup
# (taken via backup_create() above) is required before either action is
# allowed, so an admin can't wipe/deactivate their account without ever
# having downloaded a copy of it first.
_DANGER_ZONE_BACKUP_WINDOW_HOURS = 24


def _backup_is_fresh(backup_info):
    """True if backup_info's last_backup_at is within the Danger Zone's
    required window - the one thing that must be true before Archive/
    Delete can be attempted at all (ADR-76)."""

    if not backup_info or not backup_info.get("last_backup_at"):
        return False
    try:
        backed_up_at = datetime.fromisoformat(backup_info["last_backup_at"])
        now = datetime.now(backed_up_at.tzinfo) if backed_up_at.tzinfo else datetime.now()
        age_hours = (now - backed_up_at).total_seconds() / 3600
    except (TypeError, ValueError):
        return False
    return age_hours <= _DANGER_ZONE_BACKUP_WINDOW_HOURS


def _verify_current_password(current_password):
    """True if current_password matches the logged-in admin's stored hash.

    Verifies via rpc_verify_current_password (ADR-80/TD-112): a bcrypt hash
    is checked entirely in Postgres via pgcrypto's crypt() and never leaves
    the database; a still-legacy werkzeug hash is returned once (mirroring
    rpc_login_lookup's one-time round-trip, ADR-77) and checked here with
    check_password_hash() exactly as before. Werkzeug's check_password_hash()
    cannot parse a bcrypt hash at all - calling it directly on
    admins.password (the pre-fix behavior here and in security_settings())
    raised an unhandled ValueError, surfacing as an HTTP 500 for any admin
    already migrated to bcrypt by a prior login. Returns False (not a raise)
    for any lookup/RPC failure, matching "wrong password"'s existing UX."""
    supabase = get_supabase_client()
    try:
        response = supabase.rpc(
            "rpc_verify_current_password", {"p_password": current_password}
        ).execute()
    except APIError:
        return False
    if not response.data:
        return False
    row = response.data[0]
    if row.get("legacy_hash") is not None:
        return check_password_hash(row["legacy_hash"], current_password)
    return bool(row.get("is_valid"))


def _danger_zone_confirmation_error(admin_id, form):
    """Returns an error message string if the Danger Zone's required
    confirmations aren't all satisfied, else None. Re-checked server-side
    on every submit - the template's disabled-button gating is a UX
    convenience only, never the actual guard."""

    backup_info = get_backup_info(admin_id)
    if not _backup_is_fresh(backup_info):
        return (
            f"Please export and download a data export from the last "
            f"{_DANGER_ZONE_BACKUP_WINDOW_HOURS} hours first."
        )

    if not form.get("confirm_downloaded"):
        return "Please confirm you have downloaded and verified your data export."

    typed_username = form.get("confirm_username", "").strip()
    if typed_username != session.get("username"):
        return "The username you typed doesn't match your account. Please try again."

    current_password = form.get("current_password", "")
    if not _verify_current_password(current_password):
        return "Incorrect password."

    return None


@setting_bp.route("/backup/archive", methods=["POST"])
@login_required
@rate_limited(limit=2, window_seconds=3600)
def backup_archive():
    """Deactivates this library's account (Settings > Data & Backup's
    Danger Zone). Data is left completely untouched - only admins.status
    changes, via rpc_archive_tenant() (ADR-76) - login is refused
    afterward (routes/auth.py's login()), but nothing is deleted."""

    admin_id = session["admin_id"]

    error = _danger_zone_confirmation_error(admin_id, request.form)
    if error:
        flash(error, "danger")
        return redirect(url_for("setting.data_backup"))

    supabase = get_supabase_client()
    try:
        supabase.rpc("rpc_archive_tenant", {}).execute()
    except APIError:
        flash("Something went wrong. Please try again.", "danger")
        return redirect(url_for("setting.data_backup"))

    current_app.logger.info("Tenant archived: admin_id=%s", admin_id)

    session.clear()
    flash(
        "Your library account has been archived. Contact support if you "
        "need it reactivated.",
        "success",
    )
    return redirect("/")


@setting_bp.route("/backup/delete", methods=["POST"])
@login_required
@rate_limited(limit=2, window_seconds=3600)
def backup_delete():
    """Permanently deletes every row this library owns, across every
    table, in one atomic transaction (rpc_delete_tenant_data(), ADR-76) -
    including the admins row itself. Irreversible; the confirmation gate
    in _danger_zone_confirmation_error() is the only thing standing between
    a stray click and a full account wipe, so it is re-checked here even
    though the template also disables the button client-side."""

    admin_id = session["admin_id"]

    error = _danger_zone_confirmation_error(admin_id, request.form)
    if error:
        flash(error, "danger")
        return redirect(url_for("setting.data_backup"))

    supabase = get_supabase_client()
    try:
        supabase.rpc("rpc_delete_tenant_data", {}).execute()
    except APIError:
        flash("Something went wrong. Please try again.", "danger")
        return redirect(url_for("setting.data_backup"))

    current_app.logger.info("Tenant data permanently deleted: admin_id=%s", admin_id)

    session.clear()
    flash("Your library account and all its data have been permanently deleted.", "success")
    return redirect("/")


# ==========================================================
# Security Settings
# ==========================================================

@setting_bp.route("/security", methods=["GET", "POST"])
@login_required
def security_settings():

    admin_id = session["admin_id"]

    if request.method == "POST":

        form_type = request.form.get("form_type")

        if form_type == "password":
            current_password = request.form.get("current_password", "")
            new_password = request.form.get("new_password", "")
            confirm_password = request.form.get("confirm_password", "")

            if not _verify_current_password(current_password):
                flash("Current password is incorrect.", "danger")
                return redirect(url_for("setting.security_settings"))

            supabase = get_supabase_client()

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


_UPLOAD_CONTENT_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
}


def _save_upload(file, admin_id, field_name):
    """Upload a branding image to Supabase Storage (ADR-57) and return its
    full public URL to store in `library_settings`.

    Raises UploadStorageUnavailable if Storage is unreachable so the caller
    can save the rest of the form instead of 500ing (same degradation as
    when local disk was read-only). See TD-73."""

    data = file.read()
    file.stream.seek(0)

    extension = secure_filename(file.filename).rsplit(".", 1)[-1].lower()
    if extension not in _UPLOAD_CONTENT_TYPES:
        extension = "png"
    object_path = f"admin_{admin_id}/{field_name}_{secrets.token_hex(8)}.{extension}"

    try:
        return upload_branding_image(
            object_path, data, _UPLOAD_CONTENT_TYPES[extension]
        )
    except Exception as exc:
        raise UploadStorageUnavailable(str(exc)) from exc
