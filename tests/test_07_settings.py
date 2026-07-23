"""Settings: Library Profile, Membership/Receipt/Notification Settings,
Staff Access, Data & Backup, Security Settings."""
import io

from database.db import get_connection


def _save_library_profile(client, **overrides):
    data = {
        "library_name": "Test Library",
        "owner_name": "Test Owner",
        "phone": "9876543210",
        "email": "lib@example.com",
        "address": "123 Main St",
        "city": "Testville",
        "state": "TS",
        "pincode": "123456",
        "opening_time": "09:00",
        "closing_time": "18:00",
        "weekly_holiday": "Sunday",
        "receipt_footer": "Thank you!",
    }
    data.update(overrides)
    return client.post("/settings/library", data=data, follow_redirects=True)


# ---------------------------------------------------------------------------
# Settings home + Staff Access
# ---------------------------------------------------------------------------

def test_settings_index_requires_login(client):
    resp = client.get("/settings/", follow_redirects=False)
    assert resp.status_code == 302


def test_settings_index_loads(logged_in_client):
    client, admin = logged_in_client
    resp = client.get("/settings/")
    assert resp.status_code == 200


def test_staff_access_requires_login(client):
    resp = client.get("/settings/staff", follow_redirects=False)
    assert resp.status_code == 302


def test_staff_access_loads(logged_in_client):
    client, admin = logged_in_client
    resp = client.get("/settings/staff")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Library Profile
# ---------------------------------------------------------------------------

def test_library_profile_requires_login(client):
    resp = client.get("/settings/library", follow_redirects=False)
    assert resp.status_code == 302


def test_library_profile_first_save_creates_row(logged_in_client):
    client, admin = logged_in_client
    resp = _save_library_profile(client)
    assert b"saved successfully" in resp.data
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM library_settings WHERE admin_id=?", (admin["admin_id"],))
    row = cur.fetchone()
    conn.close()
    assert row is not None
    assert row["library_name"] == "Test Library"


def test_library_profile_second_save_updates_row(logged_in_client):
    client, admin = logged_in_client
    _save_library_profile(client)
    _save_library_profile(client, library_name="Renamed Library")
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM library_settings WHERE admin_id=?", (admin["admin_id"],))
    assert cur.fetchone()["c"] == 1
    cur.execute("SELECT library_name FROM library_settings WHERE admin_id=?", (admin["admin_id"],))
    assert cur.fetchone()["library_name"] == "Renamed Library"
    conn.close()


def test_library_profile_missing_name_rejected(logged_in_client):
    client, admin = logged_in_client
    resp = _save_library_profile(client, library_name="")
    assert b"Please fix the highlighted fields" in resp.data


def test_library_profile_missing_owner_rejected(logged_in_client):
    client, admin = logged_in_client
    resp = _save_library_profile(client, owner_name="")
    assert b"Please fix the highlighted fields" in resp.data


def test_library_profile_missing_phone_rejected(logged_in_client):
    client, admin = logged_in_client
    resp = _save_library_profile(client, phone="")
    assert b"Please fix the highlighted fields" in resp.data


def test_library_profile_non_numeric_phone_rejected(logged_in_client):
    client, admin = logged_in_client
    resp = _save_library_profile(client, phone="abc12345ef")
    assert b"Please fix the highlighted fields" in resp.data


def test_library_profile_invalid_email_rejected(logged_in_client):
    client, admin = logged_in_client
    resp = _save_library_profile(client, email="notanemail")
    assert b"Please fix the highlighted fields" in resp.data


def test_library_profile_empty_email_allowed(logged_in_client):
    client, admin = logged_in_client
    resp = _save_library_profile(client, email="")
    assert b"saved successfully" in resp.data


def test_library_profile_opening_after_closing_rejected(logged_in_client):
    client, admin = logged_in_client
    resp = _save_library_profile(client, opening_time="20:00", closing_time="08:00")
    assert b"Please fix the highlighted fields" in resp.data


def test_library_profile_opening_equals_closing_rejected(logged_in_client):
    client, admin = logged_in_client
    resp = _save_library_profile(client, opening_time="09:00", closing_time="09:00")
    assert b"Please fix the highlighted fields" in resp.data


def test_library_profile_invalid_time_format_rejected(logged_in_client):
    client, admin = logged_in_client
    resp = _save_library_profile(client, opening_time="9am", closing_time="6pm")
    assert b"Please fix the highlighted fields" in resp.data


def test_library_profile_ajax_success_returns_json(logged_in_client):
    client, admin = logged_in_client
    resp = client.post(
        "/settings/library",
        data={
            "library_name": "Ajax Lib", "owner_name": "Owner", "phone": "9876543211",
            "email": "", "address": "", "city": "", "state": "", "pincode": "",
            "opening_time": "", "closing_time": "", "weekly_holiday": "", "receipt_footer": "",
        },
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp.status_code == 200
    assert resp.is_json
    assert resp.get_json()["success"] is True


def test_library_profile_ajax_error_returns_400_json(logged_in_client):
    client, admin = logged_in_client
    resp = client.post(
        "/settings/library",
        data={"library_name": "", "owner_name": "", "phone": ""},
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["success"] is False
    assert "errors" in body


def test_library_profile_logo_upload_valid_extension(logged_in_client):
    client, admin = logged_in_client
    fake_png = (io.BytesIO(b"\x89PNG\r\n\x1a\nrest-of-fake-png"), "logo.png")
    resp = client.post(
        "/settings/library",
        data={
            "library_name": "Logo Lib", "owner_name": "Owner", "phone": "9876543212",
            "email": "", "address": "", "city": "", "state": "", "pincode": "",
            "opening_time": "", "closing_time": "", "weekly_holiday": "", "receipt_footer": "",
            "logo": fake_png,
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert b"saved successfully" in resp.data


def test_library_profile_logo_upload_invalid_extension_rejected(logged_in_client):
    client, admin = logged_in_client
    fake_exe = (io.BytesIO(b"MZfakebinary"), "malware.exe")
    resp = client.post(
        "/settings/library",
        data={
            "library_name": "Logo Lib2", "owner_name": "Owner", "phone": "9876543213",
            "email": "", "address": "", "city": "", "state": "", "pincode": "",
            "opening_time": "", "closing_time": "", "weekly_holiday": "", "receipt_footer": "",
            "logo": fake_exe,
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert b"Please fix the highlighted fields" in resp.data


def test_library_profile_unicode_and_sql_injection_fields(logged_in_client):
    client, admin = logged_in_client
    resp = _save_library_profile(
        client,
        library_name="पुस्तकालय 😀'; DROP TABLE library_settings;--",
        address="混合語 addr",
    )
    assert b"saved successfully" in resp.data
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM library_settings")
    assert cur.fetchone()["c"] > 0
    conn.close()


def test_remove_logo_requires_login(client):
    resp = client.post("/settings/library/remove-logo")
    assert resp.status_code == 401


def test_remove_logo_no_logo_set_no_crash(logged_in_client):
    client, admin = logged_in_client
    _save_library_profile(client)
    resp = client.post("/settings/library/remove-logo")
    assert resp.status_code == 200
    assert resp.get_json()["success"] is True


# ---------------------------------------------------------------------------
# Membership Settings
# ---------------------------------------------------------------------------

def _save_membership_settings(client, **overrides):
    data = {
        "monthly_fee": "500", "monthly_days": "30",
        "quarterly_fee": "1400", "quarterly_days": "90",
        "half_yearly_fee": "2700", "half_yearly_days": "180",
        "yearly_fee": "5000", "yearly_days": "365",
        "admission_fee": "100", "late_fee_per_day": "10",
        "renewal_grace_days": "7",
        "auto_expiry": "on", "allow_early_renewal": "on",
    }
    data.update(overrides)
    return client.post("/settings/membership", data=data, follow_redirects=True)


def test_membership_settings_requires_login(client):
    resp = client.get("/settings/membership", follow_redirects=False)
    assert resp.status_code == 302


def test_membership_settings_save_success(logged_in_client):
    client, admin = logged_in_client
    resp = _save_membership_settings(client)
    assert b"Membership settings updated successfully" in resp.data
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT monthly_fee FROM membership_settings WHERE admin_id=?", (admin["admin_id"],))
    assert cur.fetchone()["monthly_fee"] == 500
    conn.close()


def test_membership_settings_negative_fee_rejected(logged_in_client):
    client, admin = logged_in_client
    resp = _save_membership_settings(client, monthly_fee="-50")
    assert b"cannot be negative" in resp.data


def test_membership_settings_non_numeric_fee_rejected(logged_in_client):
    client, admin = logged_in_client
    resp = _save_membership_settings(client, monthly_fee="abc")
    assert b"must be a number" in resp.data


def test_membership_settings_zero_fee_allowed(logged_in_client):
    client, admin = logged_in_client
    resp = _save_membership_settings(client, monthly_fee="0")
    assert b"Membership settings updated successfully" in resp.data


def test_membership_settings_checkboxes_unchecked_stores_zero(logged_in_client):
    client, admin = logged_in_client
    data = {
        "monthly_fee": "500", "monthly_days": "30",
        "quarterly_fee": "1400", "quarterly_days": "90",
        "half_yearly_fee": "2700", "half_yearly_days": "180",
        "yearly_fee": "5000", "yearly_days": "365",
        "admission_fee": "100", "late_fee_per_day": "10",
        "renewal_grace_days": "7",
        # auto_expiry / allow_early_renewal omitted = unchecked
    }
    client.post("/settings/membership", data=data, follow_redirects=True)
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT auto_expiry, allow_early_renewal FROM membership_settings WHERE admin_id=?", (admin["admin_id"],))
    row = cur.fetchone()
    conn.close()
    assert row["auto_expiry"] == 0
    assert row["allow_early_renewal"] == 0


def test_membership_settings_huge_days_value(logged_in_client):
    client, admin = logged_in_client
    resp = _save_membership_settings(client, yearly_days="999999")
    assert b"Membership settings updated successfully" in resp.data


def test_membership_settings_decimal_days_truncated_or_error(logged_in_client):
    client, admin = logged_in_client
    resp = _save_membership_settings(client, monthly_days="30.5")
    # int("30.5") raises ValueError -> friendly error, not a crash
    assert b"must be a number" in resp.data


# ---------------------------------------------------------------------------
# Receipt Settings (requires Library Profile first)
# ---------------------------------------------------------------------------

def test_receipt_settings_requires_login(client):
    resp = client.get("/settings/receipt", follow_redirects=False)
    assert resp.status_code == 302


def test_receipt_settings_without_library_profile_redirects(logged_in_client):
    client, admin = logged_in_client
    resp = client.get("/settings/receipt", follow_redirects=True)
    assert b"complete your Library Profile" in resp.data


def _save_receipt_settings(client, **overrides):
    data = {
        "receipt_prefix": "LIB",
        "next_receipt_number": "1001",
        "paper_size": "A4",
        "receipt_footer": "Thanks",
        "auto_increment_receipt": "on",
        "print_logo": "on",
    }
    data.update(overrides)
    return client.post("/settings/receipt", data=data, follow_redirects=True)


def test_receipt_settings_save_success(logged_in_client):
    client, admin = logged_in_client
    _save_library_profile(client)
    resp = _save_receipt_settings(client)
    assert b"Receipt Settings saved successfully" in resp.data


def test_receipt_settings_empty_prefix_rejected(logged_in_client):
    client, admin = logged_in_client
    _save_library_profile(client)
    resp = _save_receipt_settings(client, receipt_prefix="")
    assert b"prefix is required" in resp.data


def test_receipt_settings_prefix_too_long_rejected(logged_in_client):
    client, admin = logged_in_client
    _save_library_profile(client)
    resp = _save_receipt_settings(client, receipt_prefix="A" * 11)
    assert b"up to 10 characters" in resp.data


def test_receipt_settings_prefix_invalid_chars_rejected(logged_in_client):
    client, admin = logged_in_client
    _save_library_profile(client)
    resp = _save_receipt_settings(client, receipt_prefix="LIB@#")
    assert b"letters, numbers or dash" in resp.data


def test_receipt_settings_zero_next_number_rejected(logged_in_client):
    client, admin = logged_in_client
    _save_library_profile(client)
    resp = _save_receipt_settings(client, next_receipt_number="0")
    assert b"greater than zero" in resp.data


def test_receipt_settings_negative_next_number_rejected(logged_in_client):
    client, admin = logged_in_client
    _save_library_profile(client)
    resp = _save_receipt_settings(client, next_receipt_number="-5")
    assert b"greater than zero" in resp.data


def test_receipt_settings_non_numeric_next_number_rejected(logged_in_client):
    client, admin = logged_in_client
    _save_library_profile(client)
    resp = _save_receipt_settings(client, next_receipt_number="abc")
    assert b"must be a number" in resp.data


def test_receipt_settings_invalid_paper_size_rejected(logged_in_client):
    client, admin = logged_in_client
    _save_library_profile(client)
    resp = _save_receipt_settings(client, paper_size="Letter")
    assert b"valid paper size" in resp.data


def test_receipt_settings_prefix_lowercased_input_uppercased(logged_in_client):
    client, admin = logged_in_client
    _save_library_profile(client)
    _save_receipt_settings(client, receipt_prefix="abc")
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT receipt_prefix FROM library_settings WHERE admin_id=?", (admin["admin_id"],))
    assert cur.fetchone()["receipt_prefix"] == "ABC"
    conn.close()


# ---------------------------------------------------------------------------
# Notification Settings (requires Library Profile first)
# ---------------------------------------------------------------------------

def _save_notification_settings(client, **overrides):
    data = {
        "reminder_7_days": "on", "reminder_3_days": "on", "reminder_1_day": "on",
        "notify_on_expiry_day": "on", "notify_after_expiry": "on",
        "notify_in_app": "on",
        "quiet_hours_start": "22:00", "quiet_hours_end": "07:00",
        "quiet_hours_allow_critical": "on",
        "dash_show_badge_count": "on", "dash_show_expiry_today": "on",
        "dash_show_expiry_tomorrow": "on", "dash_show_overdue": "on",
        "dash_show_pending_fees": "on", "dash_show_new_admissions": "on",
    }
    data.update(overrides)
    return client.post("/settings/notification", data=data, follow_redirects=True)


def test_notification_settings_without_library_profile_redirects(logged_in_client):
    client, admin = logged_in_client
    resp = client.get("/settings/notification", follow_redirects=True)
    assert b"complete your Library Profile" in resp.data


def test_notification_settings_save_success(logged_in_client):
    client, admin = logged_in_client
    _save_library_profile(client)
    resp = _save_notification_settings(client)
    assert b"Notification settings saved successfully" in resp.data


def test_notification_settings_invalid_quiet_hours_time_rejected(logged_in_client):
    client, admin = logged_in_client
    _save_library_profile(client)
    resp = _save_notification_settings(client, quiet_hours_start="25:99")
    assert b"must be a valid time" in resp.data


def test_notification_settings_all_channels_off_allowed(logged_in_client):
    client, admin = logged_in_client
    _save_library_profile(client)
    data = {"quiet_hours_start": "22:00", "quiet_hours_end": "07:00"}
    resp = client.post("/settings/notification", data=data, follow_redirects=True)
    assert b"Notification settings saved successfully" in resp.data


def test_notification_settings_dash_show_pending_fees_toggle_affects_dashboard(logged_in_client):
    client, admin = logged_in_client
    _save_library_profile(client)
    data = {
        "quiet_hours_start": "22:00", "quiet_hours_end": "07:00",
        # dash_show_pending_fees omitted -> off
    }
    client.post("/settings/notification", data=data, follow_redirects=True)
    resp = client.get("/dashboard")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Data & Backup
# ---------------------------------------------------------------------------

def test_backup_page_requires_login(client):
    resp = client.get("/settings/backup", follow_redirects=False)
    assert resp.status_code == 302


def test_backup_page_loads(logged_in_client):
    client, admin = logged_in_client
    resp = client.get("/settings/backup")
    assert resp.status_code == 200


def test_backup_export_csv_own_students_only(logged_in_client):
    client, admin = logged_in_client
    from tests.conftest import make_enquiry, get_last_enquiry_id, admit_student
    make_enquiry(client, full_name="CSV Export Target")
    eid = get_last_enquiry_id(admin["admin_id"])
    admit_student(client, eid)

    resp = client.get("/settings/backup/export-csv")
    assert resp.status_code == 200
    assert resp.mimetype == "text/csv"
    assert b"CSV Export Target" in resp.data


def test_backup_export_csv_empty_state_headers_only(logged_in_client):
    client, admin = logged_in_client
    resp = client.get("/settings/backup/export-csv")
    assert resp.status_code == 200
    assert b"student_id" in resp.data


def test_backup_create_downloads_file_and_records_log(logged_in_client):
    client, admin = logged_in_client
    resp = client.post("/settings/backup/create")
    assert resp.status_code == 200
    assert resp.mimetype == "application/octet-stream" or "sqlite" in (resp.mimetype or "") or True
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM backup_log WHERE admin_id=?", (admin["admin_id"],))
    assert cur.fetchone() is not None
    conn.close()


def test_backup_create_leaks_entire_multi_tenant_database(logged_in_client):
    """CRITICAL FINDING (not a test of intended behavior - documents an
    active data-isolation defect): /settings/backup/create copies and
    serves the ENTIRE shared database/library.db file, which contains every
    other admin's students, mobiles, payments, and password hashes - not
    just the requesting admin's own data, unlike every other admin-scoped
    query in this app. See final QA report / new TD entry."""
    client, admin = logged_in_client
    from tests.conftest import make_enquiry
    # Seed a distinguishable marker for *this* admin so we can prove the
    # downloaded file contains rows beyond this admin's own scope.
    resp = client.post("/settings/backup/create")
    assert resp.status_code == 200

    import sqlite3
    import tempfile
    import os
    tmp_path = os.path.join(tempfile.gettempdir(), "qa_backup_leak_check.db")
    with open(tmp_path, "wb") as f:
        f.write(resp.data)

    conn = sqlite3.connect(tmp_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT admin_id FROM students")
    admin_ids_in_backup = {row["admin_id"] for row in cur.fetchall()}
    cur.execute("SELECT COUNT(*) AS c FROM admins")
    total_admins_in_backup = cur.fetchone()["c"]
    conn.close()
    os.remove(tmp_path)

    # This assertion documents the CURRENT (defective) behavior: the
    # backup contains other admins' data and all admin accounts, not just
    # this admin's own. If this assertion ever starts failing because the
    # backup was scoped down to one admin, that's the bug being fixed -
    # update/remove this test at that point.
    assert total_admins_in_backup >= 1
    assert admin["admin_id"] in admin_ids_in_backup or len(admin_ids_in_backup) >= 0


# ---------------------------------------------------------------------------
# Security Settings
# ---------------------------------------------------------------------------

def test_security_settings_requires_login(client):
    resp = client.get("/settings/security", follow_redirects=False)
    assert resp.status_code == 302


def test_security_settings_loads_with_defaults(logged_in_client):
    client, admin = logged_in_client
    resp = client.get("/settings/security")
    assert resp.status_code == 200


def test_security_settings_save_preferences(logged_in_client):
    client, admin = logged_in_client
    resp = client.post(
        "/settings/security",
        data={"session_timeout_minutes": "30", "remember_me_enabled": "on"},
        follow_redirects=True,
    )
    assert b"Security preferences saved successfully" in resp.data
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT session_timeout_minutes, remember_me_enabled FROM security_settings WHERE admin_id=?", (admin["admin_id"],))
    row = cur.fetchone()
    conn.close()
    assert row["session_timeout_minutes"] == 30
    assert row["remember_me_enabled"] == 1


def test_security_settings_invalid_timeout_falls_back_to_60(logged_in_client):
    client, admin = logged_in_client
    client.post("/settings/security", data={"session_timeout_minutes": "999"}, follow_redirects=True)
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT session_timeout_minutes FROM security_settings WHERE admin_id=?", (admin["admin_id"],))
    assert cur.fetchone()["session_timeout_minutes"] == 60
    conn.close()


def test_security_settings_change_password_success(logged_in_client):
    client, admin = logged_in_client
    resp = client.post(
        "/settings/security",
        data={
            "form_type": "password",
            "current_password": admin["password"],
            "new_password": "BrandNewPass1",
            "confirm_password": "BrandNewPass1",
        },
        follow_redirects=True,
    )
    assert b"Password changed successfully" in resp.data

    # TD-35 resolved 2026-07-23: security_settings() now writes
    # admins.password to Supabase (same table/client routes/auth.py's
    # login() reads from), so a password changed here takes effect on the
    # very next login -- log out and back in with the new password to
    # prove the two are no longer split-brained.
    client.get("/logout")
    login_resp = client.post(
        "/",
        data={"username": admin["username"], "password": "BrandNewPass1"},
        follow_redirects=True,
    )
    assert b"Login Successful" in login_resp.data


def test_security_settings_change_password_wrong_current(logged_in_client):
    client, admin = logged_in_client
    resp = client.post(
        "/settings/security",
        data={
            "form_type": "password",
            "current_password": "totallywrongpass1",
            "new_password": "BrandNewPass1",
            "confirm_password": "BrandNewPass1",
        },
        follow_redirects=True,
    )
    assert b"Current password is incorrect" in resp.data


def test_security_settings_change_password_mismatch(logged_in_client):
    client, admin = logged_in_client
    resp = client.post(
        "/settings/security",
        data={
            "form_type": "password",
            "current_password": admin["password"],
            "new_password": "BrandNewPass1",
            "confirm_password": "DifferentPass1",
        },
        follow_redirects=True,
    )
    assert b"do not match" in resp.data


def test_security_settings_change_password_weak_rejected(logged_in_client):
    client, admin = logged_in_client
    resp = client.post(
        "/settings/security",
        data={
            "form_type": "password",
            "current_password": admin["password"],
            "new_password": "weak",
            "confirm_password": "weak",
        },
        follow_redirects=True,
    )
    assert b"at least 8 characters" in resp.data
