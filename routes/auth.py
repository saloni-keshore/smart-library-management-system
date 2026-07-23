import sqlite3

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

from database.db import get_connection
from database.supabase_client import get_supabase_client
from utils.security import clear_rate_limit, rate_limited

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

    admin_count = (
        supabase.table("admins")
        .select("admin_id", count="exact", head=True)
        .execute()
        .count
    )

    show_signup = (admin_count == 0)

    if request.method == "POST":

        login_id = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        try:
            response = supabase.table("admins").select("*").eq("username", login_id).execute()
            if not response.data:
                response = supabase.table("admins").select("*").eq("mobile", login_id).execute()
            admin = response.data[0] if response.data else None
        except APIError:
            admin = None

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

    return render_template("auth/login.html", show_signup=show_signup)


@auth_bp.route("/logout")
def logout():

    session.clear()

    flash("Logged out successfully.", "success")

    return redirect("/")


@auth_bp.route("/register", methods=["GET", "POST"])
def register():

    supabase = get_supabase_client()
    admin_count = (
        supabase.table("admins")
        .select("admin_id", count="exact", head=True)
        .execute()
        .count
    )
    if admin_count and not current_app.testing:
        flash("Administrator registration is available only during initial setup.", "danger")
        return redirect(url_for("auth.login"))

    if request.method == "POST":

        full_name = request.form.get("full_name", "").strip()
        username = request.form.get("username", "").strip()
        mobile = request.form.get("mobile", "").strip()
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

        try:
            # Username exists check
            response = supabase.table("admins").select("admin_id").eq("username", username).execute()
            if response.data:
                flash("Username already exists.", "danger")
                return redirect("/register")

            # Mobile exists check
            response = supabase.table("admins").select("admin_id").eq("mobile", mobile).execute()
            if response.data:
                flash("Mobile number is already registered.", "danger")
                return redirect("/register")

            hashed_password = generate_password_hash(password)

            insert_response = supabase.table("admins").insert({
                "full_name": full_name,
                "username": username,
                "mobile": mobile,
                "email": email,
                "password": hashed_password,
                "role": "Admin",
            }).execute()
        except APIError:
            flash("Something went wrong. Please try again.", "danger")
            return redirect("/register")

        new_admin_id = insert_response.data[0]["admin_id"]

        # Bridge (TD-35): enquiries/students/audit_log/library_settings/
        # membership_settings/backup_log/security_settings all still enforce a
        # SQLite foreign key back to admins.admin_id (database/db.py sets
        # PRAGMA foreign_keys = ON on every connection), so a brand-new admin
        # who only exists in Supabase would fail every one of those inserts
        # the moment they're used. Mirror the row into SQLite too, under the
        # same admin_id, until those modules are migrated to Supabase.
        try:
            sqlite_conn = get_connection()
            sqlite_conn.execute(
                """
                INSERT INTO admins (admin_id, full_name, username, mobile, email, password, role)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (new_admin_id, full_name, username, mobile, email, hashed_password, "Admin")
            )
            sqlite_conn.commit()
            sqlite_conn.close()
        except sqlite3.Error:
            supabase.table("admins").delete().eq("admin_id", new_admin_id).execute()
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
        # phone number.
        try:
            response = supabase.table("admins").select("*").eq("mobile", mobile).execute()
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
            supabase.table("admins").update(
                {"password": hashed_password}
            ).eq("admin_id", admin["admin_id"]).execute()
        except APIError:
            flash("Something went wrong. Please try again.", "danger")
            return redirect("/forgot-password")

        clear_rate_limit("forgot_password")

        flash("Password changed successfully. Please login.", "success")

        return redirect(url_for("auth.login"))

    return render_template("auth/forgot_password.html")
