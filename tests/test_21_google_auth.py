"""Google sign-in / recovery (ADR-84), logout revocation (ADR-85) and the
database login throttle (ADR-86).

Requires database/supabase_google_auth_migration.sql on the test project.

Only the Google <-> Supabase Auth code exchange is faked (no browser, no
Google account in CI). Everything after it is real: the access token the
fake exchange hands back is a Supabase-style user JWT (sub + Google
provider metadata) signed with the test project's JWT secret, so
rpc_google_login_lookup()/rpc_register_admin_google() run against the real
database and read the identity from auth.uid() exactly as in production.
"""
import os
import random
import string
import time
import uuid
from types import SimpleNamespace

import jwt
import pytest
from postgrest.exceptions import APIError

import routes.google_auth as google_auth
import utils.security as security
from database.supabase_client import (
    build_tenant_client,
    build_user_token_client,
    get_service_role_client,
)
from tests.conftest import _rand_mobile, get_admin_by_username


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_login_throttle():
    get_service_role_client().table("login_failures").delete().neq("id", -1).execute()


def _mint_user_token(auth_user_id, email, providers=("google",)):
    """A Supabase Auth-style access token, as a real Google sign-in would
    produce (role authenticated, sub = auth user id, provider metadata)."""
    now = int(time.time())
    return jwt.encode(
        {
            "sub": auth_user_id,
            "role": "authenticated",
            "aud": "authenticated",
            "email": email,
            "app_metadata": {"provider": providers[0] if providers else "email",
                             "providers": list(providers)},
            "iat": now,
            "exp": now + 3600,
        },
        os.environ["SUPABASE_JWT_SECRET"],
        algorithm="HS256",
    )


def _fake_google(monkeypatch, auth_user_id, email, name="Google Person"):
    """Make /auth/google/start skip the redirect to Google and
    /auth/google/callback's code exchange return this Google user."""
    token = _mint_user_token(auth_user_id, email)

    class _Auth:
        def sign_in_with_oauth(self, credentials):
            return SimpleNamespace(url="/auth/google/callback?code=fake-code")

        def exchange_code_for_session(self, params):
            assert params["auth_code"] == "fake-code"
            return SimpleNamespace(
                user=SimpleNamespace(
                    id=auth_user_id,
                    email=email,
                    app_metadata={"provider": "google", "providers": ["google"]},
                    user_metadata={"full_name": name},
                ),
                session=SimpleNamespace(access_token=token, expires_at=int(time.time()) + 3600),
            )

    monkeypatch.setattr(google_auth, "build_pkce_auth_client", lambda: SimpleNamespace(auth=_Auth()))
    return token


def _google_flow(client, intent):
    start = client.get(f"/auth/google/start?intent={intent}", follow_redirects=False)
    assert start.status_code == 302
    return client.get(start.headers["Location"], follow_redirects=False)


def _link_in_db(admin_id, auth_user_id, email):
    get_service_role_client().table("admins").update(
        {"auth_user_id": auth_user_id, "google_email": email}
    ).eq("admin_id", admin_id).execute()


def _rand(n=6):
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


# ---------------------------------------------------------------------------
# Google sign-in
# ---------------------------------------------------------------------------

def test_google_login_with_linked_account(client, new_admin, monkeypatch):
    uid = str(uuid.uuid4())
    _link_in_db(new_admin["admin_id"], uid, "linked@example.com")
    _fake_google(monkeypatch, uid, "linked@example.com")

    resp = _google_flow(client, "login")
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/dashboard")
    assert client.get("/dashboard").status_code == 200


def test_google_login_unknown_account_creates_library(client, monkeypatch):
    uid = str(uuid.uuid4())
    _fake_google(monkeypatch, uid, f"new_{_rand()}@example.com", name="Asha Verma")

    resp = _google_flow(client, "login")
    assert resp.headers["Location"].endswith("/auth/google/complete")

    page = client.get("/auth/google/complete")
    assert b"Asha Verma" in page.data  # pre-filled from Google

    username = f"qa_g_{_rand()}"
    resp = client.post(
        "/auth/google/complete",
        data={"full_name": "Asha Verma", "username": username.upper(), "mobile": _rand_mobile()},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/dashboard")

    admin = get_admin_by_username(username)  # stored lowercase
    assert admin is not None
    assert admin["auth_user_id"] == uid
    assert admin["has_password"] is False
    assert admin["password"].startswith("$2")  # random bcrypt, unusable


def test_google_complete_validates_fields(client, monkeypatch):
    _fake_google(monkeypatch, str(uuid.uuid4()), f"v_{_rand()}@example.com")
    _google_flow(client, "login")
    resp = client.post(
        "/auth/google/complete",
        data={"full_name": "  ", "username": "x", "mobile": "123"},
        follow_redirects=True,
    )
    assert b"enter your full name" in resp.data


def test_google_complete_requires_google_signup(client):
    resp = client.get("/auth/google/complete", follow_redirects=False)
    assert resp.status_code == 302


def test_google_login_cancelled(client):
    resp = client.get("/auth/google/callback?error=access_denied", follow_redirects=True)
    assert b"cancelled" in resp.data


def test_google_disabled_flag_blocks_start():
    from app import create_app
    app = create_app({"TESTING": True, "GOOGLE_AUTH_ENABLED": False})
    with app.test_client() as c:
        resp = c.get("/auth/google/start?intent=login", follow_redirects=True)
    assert b"not enabled" in resp.data


# ---------------------------------------------------------------------------
# Connect Google from Settings -> Security
# ---------------------------------------------------------------------------

def test_link_google_from_settings(logged_in_client, monkeypatch):
    client, admin = logged_in_client
    uid = str(uuid.uuid4())
    _fake_google(monkeypatch, uid, "mine@example.com")

    resp = _google_flow(client, "link")
    assert resp.headers["Location"].endswith("/settings/security")
    assert b"Connected as" in client.get("/settings/security").data

    row = get_admin_by_username(admin["username"])
    assert row["auth_user_id"] == uid
    assert row["google_email"] == "mine@example.com"


def test_link_google_already_used_by_other_library(logged_in_client, new_admin, monkeypatch):
    client, admin = logged_in_client
    other = _register_other_admin(client)
    uid = str(uuid.uuid4())
    _link_in_db(other["admin_id"], uid, "taken@example.com")
    _fake_google(monkeypatch, uid, "taken@example.com")

    resp = _google_flow(client, "link")
    page = client.get(resp.headers["Location"])
    assert b"already connected to another library" in page.data


def test_link_requires_login(client):
    resp = client.get("/auth/google/start?intent=link", follow_redirects=False)
    assert resp.headers["Location"].endswith("/")


def test_unlink_blocked_for_google_only_account(client, monkeypatch):
    uid = str(uuid.uuid4())
    _fake_google(monkeypatch, uid, f"only_{_rand()}@example.com")
    _google_flow(client, "login")
    client.post(
        "/auth/google/complete",
        data={"full_name": "Only Google", "username": f"qa_go_{_rand()}", "mobile": _rand_mobile()},
    )
    resp = client.post("/settings/security", data={"form_type": "unlink_google"}, follow_redirects=True)
    assert b"Set a password first" in resp.data


def _register_other_admin(client):
    suffix = _rand()
    creds = {
        "full_name": f"Other {suffix}", "username": f"qa_other_{suffix}",
        "mobile": _rand_mobile(), "email": "", "password": "TestPass123",
        "confirm_password": "TestPass123",
    }
    from app import create_app
    other_client = create_app({"TESTING": True}).test_client()
    other_client.post("/register", data=creds)
    creds["admin_id"] = get_admin_by_username(creds["username"])["admin_id"]
    return creds


# ---------------------------------------------------------------------------
# Recover with Google
# ---------------------------------------------------------------------------

def test_recover_with_google_sets_new_password_without_old(client, new_admin, monkeypatch):
    uid = str(uuid.uuid4())
    _link_in_db(new_admin["admin_id"], uid, "rec@example.com")
    _fake_google(monkeypatch, uid, "rec@example.com")

    resp = _google_flow(client, "recover")
    assert resp.headers["Location"].endswith("/settings/security")
    page = client.get("/settings/security")
    assert b"Set a New Password" in page.data
    assert b'name="current_password"' not in page.data

    resp = client.post(
        "/settings/security",
        data={"form_type": "password", "new_password": "Recovered99", "confirm_password": "Recovered99"},
        follow_redirects=True,
    )
    assert b"Password changed successfully" in resp.data

    client.get("/logout")
    bad = client.post("/", data={"username": new_admin["username"], "password": new_admin["password"]})
    assert b"Invalid username" in bad.data
    good = client.post("/", data={"username": new_admin["username"], "password": "Recovered99"})
    assert good.status_code == 302


def test_recover_window_expires(client, new_admin, monkeypatch):
    uid = str(uuid.uuid4())
    _link_in_db(new_admin["admin_id"], uid, "exp@example.com")
    _fake_google(monkeypatch, uid, "exp@example.com")
    _google_flow(client, "recover")
    with client.session_transaction() as sess:
        sess["pw_reset_until"] = int(time.time()) - 1

    resp = client.post(
        "/settings/security",
        data={"form_type": "password", "new_password": "Recovered99", "confirm_password": "Recovered99"},
        follow_redirects=True,
    )
    assert b"Current password is incorrect" in resp.data


def test_recover_with_unlinked_google_account(client, monkeypatch):
    _fake_google(monkeypatch, str(uuid.uuid4()), "nobody@example.com")
    resp = _google_flow(client, "recover")
    page = client.get(resp.headers["Location"])
    assert b"No library is connected to this Google account" in page.data


# ---------------------------------------------------------------------------
# The Google RPCs only trust a Google identity proven by the JWT
# ---------------------------------------------------------------------------

def test_google_lookup_ignores_flask_tenant_jwt(new_admin):
    """A Flask tenant JWT has no `sub`, so auth.uid() is NULL."""
    _link_in_db(new_admin["admin_id"], str(uuid.uuid4()), "t@example.com")
    data = build_tenant_client(new_admin["admin_id"]).rpc("rpc_google_login_lookup").execute().data
    assert data == []


def test_google_register_rejects_non_google_provider():
    token = _mint_user_token(str(uuid.uuid4()), "e@example.com", providers=("email",))
    with pytest.raises(APIError) as exc:
        build_user_token_client(token).rpc("rpc_register_admin_google", {
            "p_full_name": "X", "p_username": f"qa_ng_{_rand()}", "p_mobile": _rand_mobile(),
        }).execute()
    assert exc.value.message == "not_google_user"


def test_google_lookup_returns_only_own_library(new_admin):
    mine, other = str(uuid.uuid4()), str(uuid.uuid4())
    _link_in_db(new_admin["admin_id"], mine, "mine2@example.com")
    data = build_user_token_client(_mint_user_token(other, "o@example.com")) \
        .rpc("rpc_google_login_lookup").execute().data
    assert data == []
    data = build_user_token_client(_mint_user_token(mine, "mine2@example.com")) \
        .rpc("rpc_google_login_lookup").execute().data
    assert [r["admin_id"] for r in data] == [new_admin["admin_id"]]


# ---------------------------------------------------------------------------
# Logout revokes the session (ADR-85)
# ---------------------------------------------------------------------------

def test_copied_cookie_stops_working_after_logout(app, new_admin, monkeypatch):
    monkeypatch.setattr(security, "SESSION_RECHECK_SECONDS", 0)
    client = app.test_client()
    client.post("/", data={"username": new_admin["username"], "password": new_admin["password"]})
    stolen = client.get_cookie("smart_library_session").value

    client.get("/logout")

    attacker = app.test_client()
    attacker.set_cookie("smart_library_session", stolen)
    resp = attacker.get("/dashboard", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/")


def test_revoked_session_gets_no_data_even_before_recheck(new_admin):
    """RLS itself refuses a stale `sv` - the redirect is only UX."""
    supabase = get_service_role_client()
    sv = supabase.table("admins").select("session_version").eq(
        "admin_id", new_admin["admin_id"]).execute().data[0]["session_version"]
    assert build_tenant_client(new_admin["admin_id"], sv).rpc("rpc_session_valid").execute().data is True
    build_tenant_client(new_admin["admin_id"], sv).rpc("rpc_bump_session_version").execute()
    assert build_tenant_client(new_admin["admin_id"], sv).rpc("rpc_session_valid").execute().data is False
    assert build_tenant_client(new_admin["admin_id"], sv + 1).rpc("rpc_session_valid").execute().data is True


def test_session_without_version_is_ended(app, new_admin):
    """Sessions issued before ADR-85 carry no `sv` and can't be revoked,
    so they are ended once."""
    client = app.test_client()
    client.post("/", data={"username": new_admin["username"], "password": new_admin["password"]})
    with client.session_transaction() as sess:
        sess.pop("sv")
    resp = client.get("/dashboard", follow_redirects=False)
    assert resp.status_code == 302


def test_password_change_logs_out_other_devices(app, new_admin, monkeypatch):
    monkeypatch.setattr(security, "SESSION_RECHECK_SECONDS", 0)
    laptop, phone = app.test_client(), app.test_client()
    for c in (laptop, phone):
        c.post("/", data={"username": new_admin["username"], "password": new_admin["password"]})

    laptop.post("/settings/security", data={
        "form_type": "password", "current_password": new_admin["password"],
        "new_password": "Changed123", "confirm_password": "Changed123",
    })
    assert laptop.get("/dashboard").status_code == 200
    assert phone.get("/dashboard", follow_redirects=False).status_code == 302


# ---------------------------------------------------------------------------
# Login throttle (ADR-86)
# ---------------------------------------------------------------------------

def _try_login(client, username, password, ip="127.0.0.1"):
    return client.post("/", data={"username": username, "password": password},
                       environ_base={"REMOTE_ADDR": ip})


def test_throttle_blocks_after_5_failures_even_with_right_password(client, new_admin):
    for _ in range(5):
        assert b"Invalid username" in _try_login(client, new_admin["username"], "wrongpass1").data
    resp = _try_login(client, new_admin["username"], new_admin["password"])
    assert b"Too many failed attempts" in resp.data


def test_throttle_does_not_lock_out_other_admins_on_same_wifi(client, new_admin):
    other = _register_other_admin(client)
    for _ in range(5):
        _try_login(client, new_admin["username"], "wrongpass1")
    resp = _try_login(client, other["username"], other["password"])
    assert resp.status_code == 302


def test_throttle_per_account_cap_survives_changing_ip(client, new_admin):
    """A direct caller can invent client keys, so 20 failures per account
    blocks it from every IP."""
    for i in range(20):
        _try_login(client, new_admin["username"], "wrongpass1", ip=f"10.0.0.{i}")
    resp = _try_login(client, new_admin["username"], new_admin["password"], ip="10.9.9.9")
    assert b"Too many failed attempts" in resp.data


def test_successful_login_clears_failures(client, new_admin):
    for _ in range(4):
        _try_login(client, new_admin["username"], "wrongpass1")
    assert _try_login(client, new_admin["username"], new_admin["password"]).status_code == 302
    client.get("/logout")
    for _ in range(4):
        _try_login(client, new_admin["username"], "wrongpass1")
    assert _try_login(client, new_admin["username"], new_admin["password"]).status_code == 302
