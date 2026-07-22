"""Auth: login, logout, register, forgot-password."""
import re

from database.db import get_connection


# ---------------------------------------------------------------------------
# Login - positive
# ---------------------------------------------------------------------------

def test_login_with_real_provided_credentials(client):
    resp = client.post(
        "/", data={"username": "sona", "password": "mylove143"}, follow_redirects=False
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/dashboard")


def test_login_with_mobile_number_instead_of_username(client):
    resp = client.post(
        "/", data={"username": "7974732289", "password": "mylove143"}, follow_redirects=False
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/dashboard")


def test_dashboard_requires_login(client):
    resp = client.get("/dashboard", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"] in ("/", "http://localhost/")


def test_logout_clears_session(client):
    client.post("/", data={"username": "sona", "password": "mylove143"})
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    client.get("/logout")
    resp = client.get("/dashboard", follow_redirects=False)
    assert resp.status_code == 302


# ---------------------------------------------------------------------------
# Login - negative
# ---------------------------------------------------------------------------

def test_login_wrong_password(client):
    resp = client.post("/", data={"username": "sona", "password": "wrongpass1"})
    assert resp.status_code == 200
    assert b"Invalid username" in resp.data


def test_login_nonexistent_user(client):
    resp = client.post("/", data={"username": "doesnotexist999", "password": "whatever1"})
    assert resp.status_code == 200
    assert b"Invalid username" in resp.data


def test_login_empty_username(client):
    resp = client.post("/", data={"username": "", "password": "mylove143"})
    assert resp.status_code == 200
    assert b"Invalid username" in resp.data


def test_login_empty_password(client):
    resp = client.post("/", data={"username": "sona", "password": ""})
    assert resp.status_code == 200
    assert b"Invalid username" in resp.data


def test_login_both_empty(client):
    resp = client.post("/", data={"username": "", "password": ""})
    assert resp.status_code == 200


def test_login_sql_injection_attempt(client):
    resp = client.post(
        "/", data={"username": "' OR '1'='1", "password": "' OR '1'='1"}
    )
    assert resp.status_code == 200
    assert b"Invalid username" in resp.data


def test_login_sql_injection_drop_table(client):
    resp = client.post(
        "/",
        data={"username": "sona'; DROP TABLE admins;--", "password": "x"},
    )
    assert resp.status_code == 200
    # verify table still exists / admin still present
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM admins WHERE username='sona'")
    assert cur.fetchone()["c"] == 1
    conn.close()


def test_login_username_with_only_whitespace(client):
    resp = client.post("/", data={"username": "   ", "password": "mylove143"})
    assert resp.status_code == 200
    assert b"Invalid username" in resp.data


def test_login_very_long_username(client):
    resp = client.post("/", data={"username": "a" * 5000, "password": "x" * 5000})
    assert resp.status_code == 200


def test_login_unicode_emoji_username(client):
    resp = client.post("/", data={"username": "😀🎉👍", "password": "mylove143"})
    assert resp.status_code == 200


def test_login_missing_form_fields_entirely(client):
    resp = client.post("/", data={})
    assert resp.status_code == 200


def test_login_case_sensitivity(client):
    resp = client.post("/", data={"username": "SONA", "password": "mylove143"})
    assert resp.status_code == 200
    # username lookup is case-sensitive SQL '=' compare; expect failure
    assert b"Invalid username" in resp.data


# ---------------------------------------------------------------------------
# Register - positive/negative/edge
# ---------------------------------------------------------------------------

def test_register_success(client):
    resp = client.post(
        "/register",
        data={
            "full_name": "New QA Admin",
            "username": "qa_register_ok",
            "mobile": "9812345670",
            "email": "qa_ok@example.com",
            "password": "GoodPass1",
            "confirm_password": "GoodPass1",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT role FROM admins WHERE username='qa_register_ok'")
    row = cur.fetchone()
    conn.close()
    assert row is not None


def test_register_duplicate_username(client):
    payload = {
        "full_name": "Dup User",
        "username": "qa_dup_user",
        "mobile": "9812345671",
        "email": "dup1@example.com",
        "password": "GoodPass1",
        "confirm_password": "GoodPass1",
    }
    client.post("/register", data=payload, follow_redirects=True)
    payload2 = dict(payload, mobile="9812345672", email="dup2@example.com")
    resp = client.post("/register", data=payload2, follow_redirects=True)
    assert b"already exists" in resp.data


def test_register_duplicate_mobile(client):
    payload = {
        "full_name": "Dup Mobile A",
        "username": "qa_dupmobile_a",
        "mobile": "9812345680",
        "email": "dupmobA@example.com",
        "password": "GoodPass1",
        "confirm_password": "GoodPass1",
    }
    client.post("/register", data=payload, follow_redirects=True)
    payload2 = dict(payload, username="qa_dupmobile_b", email="dupmobB@example.com")
    resp = client.post("/register", data=payload2, follow_redirects=True)
    assert b"already registered" in resp.data


def test_register_mobile_too_short(client):
    resp = client.post(
        "/register",
        data={
            "full_name": "Short Mobile",
            "username": "qa_shortmobile",
            "mobile": "123",
            "email": "sm@example.com",
            "password": "GoodPass1",
            "confirm_password": "GoodPass1",
        },
        follow_redirects=True,
    )
    assert b"valid 10-digit mobile" in resp.data


def test_register_mobile_non_numeric(client):
    resp = client.post(
        "/register",
        data={
            "full_name": "Bad Mobile",
            "username": "qa_badmobile",
            "mobile": "98abc12345",
            "email": "bm@example.com",
            "password": "GoodPass1",
            "confirm_password": "GoodPass1",
        },
        follow_redirects=True,
    )
    assert b"valid 10-digit mobile" in resp.data


def test_register_mobile_11_digits(client):
    resp = client.post(
        "/register",
        data={
            "full_name": "Long Mobile",
            "username": "qa_longmobile",
            "mobile": "981234567890",
            "email": "lm@example.com",
            "password": "GoodPass1",
            "confirm_password": "GoodPass1",
        },
        follow_redirects=True,
    )
    assert b"valid 10-digit mobile" in resp.data


def test_register_passwords_mismatch(client):
    resp = client.post(
        "/register",
        data={
            "full_name": "Mismatch",
            "username": "qa_mismatch",
            "mobile": "9812345699",
            "email": "mm@example.com",
            "password": "GoodPass1",
            "confirm_password": "GoodPass2",
        },
        follow_redirects=True,
    )
    assert b"do not match" in resp.data


def test_register_password_too_short(client):
    resp = client.post(
        "/register",
        data={
            "full_name": "Short Pw",
            "username": "qa_shortpw",
            "mobile": "9812345601",
            "email": "sp@example.com",
            "password": "Ab1",
            "confirm_password": "Ab1",
        },
        follow_redirects=True,
    )
    assert b"at least 8 characters" in resp.data


def test_register_password_no_digit(client):
    resp = client.post(
        "/register",
        data={
            "full_name": "No Digit",
            "username": "qa_nodigit",
            "mobile": "9812345602",
            "email": "nd@example.com",
            "password": "NoDigitsHere",
            "confirm_password": "NoDigitsHere",
        },
        follow_redirects=True,
    )
    assert b"at least one number" in resp.data


def test_register_password_no_letter(client):
    resp = client.post(
        "/register",
        data={
            "full_name": "No Letter",
            "username": "qa_noletter",
            "mobile": "9812345603",
            "email": "nl@example.com",
            "password": "12345678",
            "confirm_password": "12345678",
        },
        follow_redirects=True,
    )
    assert b"at least one letter" in resp.data


def test_register_empty_full_name(client):
    resp = client.post(
        "/register",
        data={
            "full_name": "",
            "username": "qa_emptyname",
            "mobile": "9812345604",
            "email": "en@example.com",
            "password": "GoodPass1",
            "confirm_password": "GoodPass1",
        },
        follow_redirects=True,
    )
    # No server-side validation exists for empty full_name; row is created regardless
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT full_name FROM admins WHERE username='qa_emptyname'")
    row = cur.fetchone()
    conn.close()
    assert row is not None
    assert row["full_name"] == ""


def test_register_empty_username(client):
    resp = client.post(
        "/register",
        data={
            "full_name": "Empty User",
            "username": "",
            "mobile": "9812345605",
            "email": "eu@example.com",
            "password": "GoodPass1",
            "confirm_password": "GoodPass1",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200


def test_register_sql_injection_username(client):
    resp = client.post(
        "/register",
        data={
            "full_name": "Injector",
            "username": "qa_inj'; DROP TABLE admins;--",
            "mobile": "9812345606",
            "email": "inj@example.com",
            "password": "GoodPass1",
            "confirm_password": "GoodPass1",
        },
        follow_redirects=True,
    )
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM admins")
    assert cur.fetchone()["c"] > 0
    conn.close()


def test_register_unicode_and_emoji_name(client):
    resp = client.post(
        "/register",
        data={
            "full_name": "田中さん 😀",
            "username": "qa_unicode1",
            "mobile": "9812345607",
            "email": "uni@example.com",
            "password": "GoodPass1",
            "confirm_password": "GoodPass1",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT full_name FROM admins WHERE username='qa_unicode1'")
    row = cur.fetchone()
    conn.close()
    assert row is not None
    assert row["full_name"] == "田中さん 😀"


def test_register_role_hardcoded_admin_capital(client):
    """TD-13: role stored as 'Admin' (capital) while schema default is
    lowercase 'admin' - documented technical debt, verifying still true."""
    client.post(
        "/register",
        data={
            "full_name": "Role Check",
            "username": "qa_rolecheck",
            "mobile": "9812345608",
            "email": "rc@example.com",
            "password": "GoodPass1",
            "confirm_password": "GoodPass1",
        },
        follow_redirects=True,
    )
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT role FROM admins WHERE username='qa_rolecheck'")
    row = cur.fetchone()
    conn.close()
    assert row["role"] == "Admin"


# ---------------------------------------------------------------------------
# Forgot password
# ---------------------------------------------------------------------------

def _register(client, username, mobile, full_name="FP Tester", password="OrigPass1"):
    client.post(
        "/register",
        data={
            "full_name": full_name,
            "username": username,
            "mobile": mobile,
            "email": f"{username}@example.com",
            "password": password,
            "confirm_password": password,
        },
        follow_redirects=True,
    )


def test_forgot_password_success(client):
    _register(client, "qa_fp_ok", "9812345610", full_name="Forgot Pw Ok")
    resp = client.post(
        "/forgot-password",
        data={
            "full_name": "Forgot Pw Ok",
            "mobile": "9812345610",
            "new_password": "NewPass123",
            "confirm_password": "NewPass123",
        },
        follow_redirects=True,
    )
    assert b"Password changed successfully" in resp.data
    login_resp = client.post(
        "/", data={"username": "qa_fp_ok", "password": "NewPass123"}, follow_redirects=False
    )
    assert login_resp.status_code == 302


def test_forgot_password_case_insensitive_name_match(client):
    _register(client, "qa_fp_case", "9812345611", full_name="Case Match")
    resp = client.post(
        "/forgot-password",
        data={
            "full_name": "CASE match",
            "mobile": "9812345611",
            "new_password": "NewPass123",
            "confirm_password": "NewPass123",
        },
        follow_redirects=True,
    )
    assert b"Password changed successfully" in resp.data


def test_forgot_password_wrong_name(client):
    _register(client, "qa_fp_wrongname", "9812345612", full_name="Real Name")
    resp = client.post(
        "/forgot-password",
        data={
            "full_name": "Totally Wrong Name",
            "mobile": "9812345612",
            "new_password": "NewPass123",
            "confirm_password": "NewPass123",
        },
        follow_redirects=True,
    )
    assert b"No account found" in resp.data


def test_forgot_password_mobile_only_no_name_should_not_reset(client):
    """Security: mobile alone (without matching name) must not allow reset."""
    _register(client, "qa_fp_secure", "9812345613", full_name="Secure Name")
    resp = client.post(
        "/forgot-password",
        data={
            "full_name": "",
            "mobile": "9812345613",
            "new_password": "Hacked123",
            "confirm_password": "Hacked123",
        },
        follow_redirects=True,
    )
    assert b"No account found" in resp.data
    login_resp = client.post(
        "/", data={"username": "qa_fp_secure", "password": "Hacked123"}
    )
    assert b"Invalid username" in login_resp.data


def test_forgot_password_mismatch(client):
    _register(client, "qa_fp_mismatch", "9812345614")
    resp = client.post(
        "/forgot-password",
        data={
            "full_name": "FP Tester",
            "mobile": "9812345614",
            "new_password": "NewPass123",
            "confirm_password": "Different123",
        },
        follow_redirects=True,
    )
    assert b"do not match" in resp.data


def test_forgot_password_weak_new_password(client):
    _register(client, "qa_fp_weak", "9812345615")
    resp = client.post(
        "/forgot-password",
        data={
            "full_name": "FP Tester",
            "mobile": "9812345615",
            "new_password": "weak",
            "confirm_password": "weak",
        },
        follow_redirects=True,
    )
    assert b"at least 8 characters" in resp.data


def test_forgot_password_invalid_mobile_format(client):
    resp = client.post(
        "/forgot-password",
        data={
            "full_name": "Whoever",
            "mobile": "notanumber",
            "new_password": "NewPass123",
            "confirm_password": "NewPass123",
        },
        follow_redirects=True,
    )
    assert b"valid 10-digit mobile" in resp.data


def test_forgot_password_nonexistent_account(client):
    resp = client.post(
        "/forgot-password",
        data={
            "full_name": "Ghost User",
            "mobile": "9999912345",
            "new_password": "NewPass123",
            "confirm_password": "NewPass123",
        },
        follow_redirects=True,
    )
    assert b"No account found" in resp.data


def test_forgot_password_empty_everything(client):
    resp = client.post("/forgot-password", data={}, follow_redirects=True)
    assert resp.status_code == 200
    assert b"valid 10-digit mobile" in resp.data
