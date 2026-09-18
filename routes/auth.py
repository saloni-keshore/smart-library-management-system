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

from database.supabase_client import get_supabase_client
from utils.security import clear_rate_limit, rate_limited
from utils.normalization import normalize_name, normalize_phone

auth_bp = Blueprint(
    "auth",
    __name__
)


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


@auth_bp.route("/", methods=["GET", "POST"])
@rate_limited()
def login():

    supabase = get_supabase_client()

    if request.method == "POST":

        login_id = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        try:
            response = supabase.rpc("rpc_login_lookup", {"p_identifier": login_id}).execute()
            admin = response.data[0] if response.data else None
        except APIError:
            admin = None

        if admin and admin.get("status") == "archived":
            flash(
                "This account has been archived and can no longer be accessed. "
                "Contact support if you need it reactivated.",
                "danger"
            )
            return render_template("auth/login.html", show_signup=True)

        if admin and check_password_hash(admin["password"], password):
            session.clear()
            session["admin_id"] = admin["admin_id"]
            session["username"] = admin["username"]
            session.permanent = True
            clear_rate_limit("login")

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

    session.clear()

    flash("Logged out successfully.", "success")

    return redirect("/")


@auth_bp.route("/register", methods=["GET", "POST"])
def register():

    supabase = get_supabase_client()

    if request.method == "POST":

        full_name = normalize_name(request.form.get("full_name", ""))
        username = request.form.get("username", "").strip()
        mobile = normalize_phone(request.form.get("mobile", ""))
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        # Mobile validation
        if not mobile.isdigit() or len(mobile) != 10:
            flash("Please enter a valid 10-digit mobile number.", "danger")
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


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
@rate_limited(limit=3, window_seconds=900)
def forgot_password():

    if not current_app.config["ENABLE_SELF_SERVICE_PASSWORD_RESET"] and not current_app.testing:
        flash("Password reset is disabled. Contact your library administrator.", "danger")
        return redirect(url_for("auth.login"))

    if request.method == "POST":

        full_name = request.form.get("full_name", "").strip()
        mobile = request.form.get("mobile", "").strip()
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")

        # Mobile format check
        if not mobile.isdigit() or len(mobile) != 10:
            flash("Please enter a valid 10-digit mobile number.", "danger")
            return redirect("/forgot-password")

        # Password match
        if new_password != confirm_password:
            flash("Passwords do not match.", "danger")
            return redirect("/forgot-password")

        # Password strength
        error = validate_password(new_password)
        if error:
            flash(error, "danger")
            return redirect("/forgot-password")

        supabase = get_supabase_client()

        # mobile is UNIQUE, so this returns at most one row; full name is
        # then compared case-insensitively in Python. Require BOTH full
        # name AND mobile to match — prevents reset with just a known
        # phone number. Goes through a SECURITY DEFINER RPC, not a direct
        # table read, since the anon-role pre-login client has no admins
        # SELECT policy (ADR-75).
        try:
            response = supabase.rpc("rpc_forgot_password_lookup", {"p_mobile": mobile}).execute()
            admin = response.data[0] if response.data else None
        except APIError:
            admin = None
        if admin and admin["full_name"].lower() != full_name.lower():
            admin = None

        if not admin:
            flash(
                "No account found with that name and mobile number.",
                "danger"
            )
            return redirect("/forgot-password")

        hashed_password = generate_password_hash(new_password)

        try:
            supabase.rpc("rpc_reset_password", {
                "p_admin_id": admin["admin_id"],
                "p_new_password_hash": hashed_password,
            }).execute()
        except APIError:
            flash("Something went wrong. Please try again.", "danger")
            return redirect("/forgot-password")

        clear_rate_limit("forgot_password")

        flash("Password changed successfully. Please login.", "success")

        return redirect(url_for("auth.login"))

    return render_template("auth/forgot_password.html")
