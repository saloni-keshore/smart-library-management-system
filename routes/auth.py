import hashlib
import re
import time

from flask import (
    Blueprint,
    current_app,
    render_template,
    request,
    redirect,
    flash,
    session,
    url_for
)
from werkzeug.security import (
    check_password_hash,
    generate_password_hash
)
from postgrest.exceptions import APIError

from database.supabase_client import build_tenant_client, get_supabase_client
from utils.security import rate_limited
from utils.normalization import normalize_name, normalize_phone

auth_bp = Blueprint(
    "auth",
    __name__
)

# Also used by routes/setting.py's Library Profile validation.
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Stored lowercase (ADR-86/TD-118): login matches lower(username), so a
# username only needs to be typed the same letters, any case.
USERNAME_PATTERN = re.compile(r"^[a-z0-9_.]{3,30}$")


def validate_password(password):
    """
    Returns an error message string if password is invalid, else None.
    Rules: min 8 chars, at least 1 letter, at least 1 digit.
    """
    if len(password) < 8:
        return "Password must be at least 8 characters long."
    if not any(c.isalpha() for c in password):
        return "Password must contain at least one letter."
    if not any(c.isdigit() for c in password):
        return "Password must contain at least one number."
    return None


def validate_registration_fields(full_name, username, mobile, email=""):
    """Shared by register() and Google onboarding
    (routes/google_auth.py's complete()). Expects already-normalized
    values (normalize_name, strip().lower(), normalize_phone, strip()).
    Returns an error message string, or None."""
    if not full_name:
        return "Please enter your full name."
    if not USERNAME_PATTERN.match(username):
        return (
            "Username must be 3-30 characters: lowercase letters, numbers, "
            "underscore (_) or dot (.)."
        )
    if not mobile.isdigit() or len(mobile) != 10:
        return "Please enter a valid 10-digit mobile number."
    if email and not EMAIL_PATTERN.match(email):
        return "Please enter a valid email address, or leave it blank."
    return None


def start_admin_session(admin):
    """Log an admin in - shared by password login and Google sign-in.
    `admin` needs admin_id, username and (ADR-85) session_version, which
    app.py's attach_tenant_supabase_client puts into every tenant JWT as
    the `sv` claim so a later logout can revoke this session."""
    session.clear()
    session["admin_id"] = admin["admin_id"]
    session["username"] = admin["username"]
    session["sv"] = int(admin.get("session_version") or 0)
    session["sv_checked_at"] = int(time.time())
    session.permanent = True


def _login_client_key():
    """Opaque per-client key for rpc_login_lookup()'s throttle (ADR-86):
    a hash, so raw client IPs are never stored in the database."""
    return hashlib.sha256((request.remote_addr or "unknown").encode()).hexdigest()


@auth_bp.route("/", methods=["GET", "POST"])
def login():

    if request.method == "GET" and "admin_id" in session:
        return redirect("/dashboard")

    supabase = get_supabase_client()

    if request.method == "POST":

        login_id = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        client_key = _login_client_key()

        try:
            response = supabase.rpc(
                "rpc_login_lookup",
                {"p_identifier": login_id, "p_password": password, "p_client_key": client_key},
            ).execute()
            row = response.data[0] if response.data else None
        except APIError as e:
            row = None
            # PGRST202 = function not found: database/supabase_google_auth_
            # migration.sql hasn't been run yet. Fall back to the old
            # two-argument signature so login never breaks mid-rollout.
            if e.code == "PGRST202":
                try:
                    response = supabase.rpc(
                        "rpc_login_lookup", {"p_identifier": login_id, "p_password": password}
                    ).execute()
                    row = response.data[0] if response.data else None
                except APIError:
                    row = None

        # The throttle lives inside rpc_login_lookup() itself, since that
        # RPC is anon-callable and a Flask-only check could be bypassed
        # (ADR-86).
        if row and row.get("throttled"):
            flash(
                "Too many failed attempts for this account. Please wait "
                "15 minutes and try again, or sign in with Google.",
                "danger"
            )
            return render_template("auth/login.html", show_signup=True)

        # rpc_login_lookup only returns a row for a wrong password when the
        # stored hash is still in the old werkzeug format (legacy_hash set)
        # - Postgres can't verify that format itself, so Python does, same
        # as before this fix. A bcrypt-format hash is verified entirely
        # inside the RPC (legacy_hash NULL): a row coming back at all means
        # the password already matched, and the raw hash was never returned.
        admin = None
        if row and row.get("legacy_hash"):
            if check_password_hash(row["legacy_hash"], password):
                admin = row
                # One-time upgrade to a Postgres-verifiable bcrypt hash, so
                # this admin's hash never needs to leave Postgres again.
                # Non-fatal on failure - login still proceeds and this is
                # simply retried on the next login.
                try:
                    build_tenant_client(admin["admin_id"]).rpc(
                        "rpc_migrate_password_hash", {"p_plain_password": password}
                    ).execute()
                    # Now that the hash is bcrypt, one more lookup lets
                    # rpc_login_lookup() verify it in Postgres and clear this
                    # account's earlier failed attempts (ADR-86) - there is
                    # deliberately no anon-callable "clear failures" RPC.
                    supabase.rpc(
                        "rpc_login_lookup",
                        {"p_identifier": login_id, "p_password": password, "p_client_key": client_key},
                    ).execute()
                except APIError:
                    pass
            else:
                try:
                    supabase.rpc(
                        "rpc_record_login_failure",
                        {"p_identifier": login_id, "p_client_key": client_key},
                    ).execute()
                except APIError:
                    pass
        elif row and row.get("admin_id"):
            admin = row

        if admin and admin.get("status") == "archived":
            flash(
                "This account has been archived and can no longer be accessed. "
                "Contact support if you need it reactivated.",
                "danger"
            )
            return render_template("auth/login.html", show_signup=True)

        if admin:
            start_admin_session(admin)

            flash("Login Successful!", "success")

            return redirect("/dashboard")

        else:

            flash("Invalid username/mobile number or password.", "danger")

    # Every library can self-register at any time (ADR-75) - tenants are
    # isolated by Row-Level Security, not by only ever allowing one admin
    # to exist in the database.
    return render_template("auth/login.html", show_signup=True)


@auth_bp.route("/logout")
def logout():

    # Revoke this session server-side before forgetting it (ADR-85): bumping
    # admins.session_version makes every outstanding tenant JWT/session
    # cookie for this admin invalid, so a copied cookie can't be replayed.
    # Best-effort - logging out must never fail.
    if "admin_id" in session:
        try:
            get_supabase_client().rpc("rpc_bump_session_version").execute()
        except APIError:
            current_app.logger.warning("Could not bump session_version on logout")

    session.clear()

    flash("Logged out successfully.", "success")

    return redirect("/")


@auth_bp.route("/register", methods=["GET", "POST"])
@rate_limited(limit=10, window_seconds=3600)
def register():

    supabase = get_supabase_client()

    if request.method == "POST":

        full_name = normalize_name(request.form.get("full_name", ""))
        username = request.form.get("username", "").strip().lower()
        mobile = normalize_phone(request.form.get("mobile", ""))
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        error = validate_registration_fields(full_name, username, mobile, email)
        if error:
            flash(error, "danger")
            return redirect("/register")

        # Password match
        if password != confirm_password:
            flash("Passwords do not match.", "danger")
            return redirect("/register")

        # Password strength
        error = validate_password(password)
        if error:
            flash(error, "danger")
            return redirect("/register")

        hashed_password = generate_password_hash(password)

        # Username/mobile uniqueness is checked and the row inserted inside
        # one SECURITY DEFINER Postgres function (rpc_register_admin) so
        # the anon-role pre-login client never needs direct admins table
        # access, and so two concurrent registrations with the same
        # username can't both pass a check-then-insert race.
        try:
            supabase.rpc("rpc_register_admin", {
                "p_full_name": full_name,
                "p_username": username,
                "p_mobile": mobile,
                "p_email": email,
                "p_password_hash": hashed_password,
            }).execute()
        except APIError as e:
            if e.message == "username_taken":
                flash("Username already exists.", "danger")
            elif e.message == "mobile_taken":
                flash("Mobile number is already registered.", "danger")
            else:
                flash("Something went wrong. Please try again.", "danger")
            return redirect("/register")

        flash("Account created successfully. Please login.", "success")

        return redirect("/")

    return render_template("auth/register.html")


@auth_bp.route("/forgot-password")
def forgot_password():
    """Account recovery is "sign in with Google" (ADR-84) - free, and Google
    verifies the identity. The old full-name + mobile reset was removed:
    anyone who knew those two public-ish details could take over an
    account (QA audit 2026-10-03)."""
    return render_template("auth/forgot_password.html")
