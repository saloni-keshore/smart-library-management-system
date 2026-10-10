"""Auth: login, logout, register, forgot-password."""
import re
import time

import pytest

import app as app_module
from app import create_app
from database.supabase_client import get_service_role_client
from tests.conftest import _rand, _rand_mobile, get_admin_by_username


@pytest.fixture(autouse=True)
def _reset_login_throttle():
    """rpc_login_lookup() counts failures in login_failures (ADR-86), and
    these tests deliberately fail logins against the shared `sona` account
    - start each test with a clean slate so the throttle never trips on
    tests that aren't about it."""
    try:
        get_service_role_client().table("login_failures").delete().neq("id", -1).execute()
    except Exception:
        pass  # migration not applied yet - nothing to clear


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
    assert get_admin_by_username("sona") is not None


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


def test_login_username_is_case_insensitive(client):
    """TD-118/ADR-86: a phone keyboard auto-capitalising "Sona" (or caps
    lock) must not break login - rpc_login_lookup() matches lower(username)."""
    for typed in ("SONA", "Sona"):
        resp = client.post(
            "/", data={"username": typed, "password": "mylove143"}, follow_redirects=False
        )
        assert resp.status_code == 302, typed
        assert resp.headers["Location"].endswith("/dashboard")
        client.get("/logout")


def test_login_page_redirects_when_already_logged_in(client):
    client.post("/", data={"username": "sona", "password": "mylove143"})
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/dashboard")


# ---------------------------------------------------------------------------
# Remember Me / idle timeout (ADR-87)
# ---------------------------------------------------------------------------

def _session_set_cookie(resp):
    return next(
        h for h in resp.headers.getlist("Set-Cookie")
        if h.startswith("smart_library_session=")
    )


def _login(client, admin, **extra):
    return client.post(
        "/",
        data={"username": admin["username"], "password": admin["password"], **extra},
        follow_redirects=False,
    )


def test_login_page_remember_me_checkbox_is_submitted(client):
    resp = client.get("/")
    assert b'name="remember_me"' in resp.data


def test_login_with_remember_me_sets_persistent_cookie(client, new_admin):
    resp = _login(client, new_admin, remember_me="1")
    assert resp.status_code == 302
    assert "Expires=" in _session_set_cookie(resp)
    assert client.application.permanent_session_lifetime.days == 7
    with client.session_transaction() as sess:
        assert sess["remember"] is True
        assert sess.permanent is True


def test_login_without_remember_me_sets_browser_session_cookie(client, new_admin):
    resp = _login(client, new_admin)
    assert resp.status_code == 302
    assert "Expires=" not in _session_set_cookie(resp)
    with client.session_transaction() as sess:
        assert sess["remember"] is False
        assert sess.permanent is False
        # No security_settings row yet -> the 60 minute default.
        assert sess["idle_timeout"] == 60 * 60


def test_login_reads_admin_session_timeout_setting(client, new_admin):
    _login(client, new_admin)
    client.post("/settings/security", data={"session_timeout_minutes": "15"})
    client.get("/logout")
    _login(client, new_admin)
    with client.session_transaction() as sess:
        assert sess["idle_timeout"] == 15 * 60


def test_idle_session_is_ended_before_a_tenant_client_is_built(client, new_admin, monkeypatch):
    _login(client, new_admin)
    with client.session_transaction() as sess:
        sess["last_seen"] = int(time.time()) - sess["idle_timeout"] - 5

    def _no_tenant_client(*args, **kwargs):
        raise AssertionError("tenant client built for an idle-expired session")

    monkeypatch.setattr(app_module, "build_tenant_client", _no_tenant_client)
    resp = client.get("/dashboard", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"] in ("/", "http://localhost/")
    with client.session_transaction() as sess:
        assert "admin_id" not in sess
        assert "sv" not in sess


def test_active_session_within_timeout_stays_logged_in(client, new_admin):
    _login(client, new_admin)
    with client.session_transaction() as sess:
        sess["last_seen"] = int(time.time()) - sess["idle_timeout"] + 120
    assert client.get("/dashboard").status_code == 200
    with client.session_transaction() as sess:
        assert int(time.time()) - sess["last_seen"] < 60  # idle clock restarted


def test_remembered_session_is_not_idle_limited(client, new_admin):
    _login(client, new_admin, remember_me="1")
    with client.session_transaction() as sess:
        sess["last_seen"] = int(time.time()) - 3 * 24 * 3600
    assert client.get("/dashboard").status_code == 200


def test_timeout_never_has_no_idle_limit(client, new_admin):
    _login(client, new_admin)
    with client.session_transaction() as sess:
        sess["idle_timeout"] = 0
        sess["last_seen"] = int(time.time()) - 3 * 24 * 3600
    assert client.get("/dashboard").status_code == 200


def test_session_from_before_remember_me_gets_default_idle_timeout(client, new_admin):
    _login(client, new_admin, remember_me="1")
    with client.session_transaction() as sess:
        for key in ("remember", "last_seen", "idle_timeout"):
            sess.pop(key)
    assert client.get("/dashboard").status_code == 200
    with client.session_transaction() as sess:
        assert sess["remember"] is False
        assert sess.permanent is False
        assert sess["idle_timeout"] == 60 * 60


def test_logout_still_revokes_a_remembered_session(app, new_admin):
    """ADR-85 must hold for 7-day sessions too: logging out on one device
    ends a remembered session on another."""
    remembered, other = app.test_client(), app.test_client()
    _login(remembered, new_admin, remember_me="1")
    _login(other, new_admin)
    assert remembered.get("/dashboard").status_code == 200
    other.get("/logout")
    with remembered.session_transaction() as sess:
        sess["sv_checked_at"] = 0  # force the next request to re-check
    resp = remembered.get("/dashboard", follow_redirects=False)
    assert resp.status_code == 302


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
    admin = get_admin_by_username("qa_register_ok")
    assert admin is not None


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
    """QA audit 2026-10-03: a blank full name used to be accepted. Fresh
    username/mobile each run - the old buggy behavior left rows behind."""
    username = f"qa_noname_{_rand()}"
    resp = client.post(
        "/register",
        data={
            "full_name": "   ",
            "username": username,
            "mobile": _rand_mobile(),
            "email": "en@example.com",
            "password": "GoodPass1",
            "confirm_password": "GoodPass1",
        },
        follow_redirects=True,
    )
    assert b"enter your full name" in resp.data
    assert get_admin_by_username(username) is None


@pytest.mark.parametrize("username", ["", "   ", "ab", "has space", "bad!chars"])
def test_register_invalid_username_rejected(client, username):
    """QA audit 2026-10-03: a whitespace-only username created an account."""
    mobile = _rand_mobile()
    resp = client.post(
        "/register",
        data={
            "full_name": "Empty User",
            "username": username,
            "mobile": mobile,
            "email": "eu@example.com",
            "password": "GoodPass1",
            "confirm_password": "GoodPass1",
        },
        follow_redirects=True,
    )
    assert b"Username must be 3-30 characters" in resp.data
    supabase = get_service_role_client()
    assert not supabase.table("admins").select("admin_id").eq("mobile", mobile).execute().data


def test_register_invalid_email_rejected(client):
    resp = client.post(
        "/register",
        data={
            "full_name": "Bad Email",
            "username": "qa_bademail_x",
            "mobile": "9812345609",
            "email": "not-an-email",
            "password": "GoodPass1",
            "confirm_password": "GoodPass1",
        },
        follow_redirects=True,
    )
    assert b"valid email address" in resp.data
    assert get_admin_by_username("qa_bademail_x") is None


def test_register_stores_username_lowercase_and_blocks_case_duplicate(client, new_admin):
    resp = client.post(
        "/register",
        data={
            "full_name": "Case Dup",
            "username": new_admin["username"].upper(),
            "mobile": "9812345616",
            "email": "",
            "password": "GoodPass1",
            "confirm_password": "GoodPass1",
        },
        follow_redirects=True,
    )
    assert b"Username already exists" in resp.data


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
    supabase = get_service_role_client()
    count = supabase.table("admins").select("admin_id", count="exact", head=True).execute().count
    assert count > 0


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
    admin = get_admin_by_username("qa_unicode1")
    assert admin is not None
    assert admin["full_name"] == "田中さん 😀"


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
    admin = get_admin_by_username("qa_rolecheck")
    assert admin["role"] == "Admin"


# ---------------------------------------------------------------------------
# Forgot password - Google recovery only (ADR-84)
# ---------------------------------------------------------------------------

def test_forgot_password_page_offers_google_recovery(client):
    resp = client.get("/forgot-password")
    assert resp.status_code == 200
    assert b"Recover with Google" in resp.data
    assert b"/auth/google/start?intent=recover" in resp.data


def test_forgot_password_name_and_mobile_reset_is_gone(client, new_admin):
    """QA audit 2026-10-03: anyone who knew an admin's full name + mobile
    could set a new password. The POST handler no longer exists."""
    resp = client.post(
        "/forgot-password",
        data={
            "full_name": new_admin["full_name"],
            "mobile": new_admin["mobile"],
            "new_password": "Hacked123",
            "confirm_password": "Hacked123",
        },
    )
    assert resp.status_code == 405
    login_resp = client.post(
        "/", data={"username": new_admin["username"], "password": "Hacked123"}
    )
    assert b"Invalid username" in login_resp.data


def test_forgot_password_rpcs_dropped():
    from database.supabase_client import build_anon_client
    from postgrest.exceptions import APIError
    with pytest.raises(APIError):
        build_anon_client().rpc(
            "rpc_forgot_password_lookup", {"p_mobile": "9999912345"}
        ).execute()


def test_google_buttons_hidden_when_disabled():
    disabled_app = create_app({"TESTING": True, "GOOGLE_AUTH_ENABLED": False})
    with disabled_app.test_client() as c:
        assert b"Continue with Google" not in c.get("/").data
        assert b"Recover with Google" not in c.get("/forgot-password").data
