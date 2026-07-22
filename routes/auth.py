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
from database.db import get_connection
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

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) AS total FROM admins")

    admin_count = cursor.fetchone()["total"]

    conn.close()

    show_signup = (admin_count == 0)

    if request.method == "POST":

        login_id = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT * FROM admins
            WHERE username = ?
                OR mobile = ?
            """,
            (login_id, login_id)
        )

        admin = cursor.fetchone()

        conn.close()

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

    conn = get_connection()
    admin_count = conn.execute("SELECT COUNT(*) AS total FROM admins").fetchone()["total"]
    conn.close()
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

        conn = get_connection()
        cursor = conn.cursor()

        # Username exists check
        cursor.execute(
            "SELECT admin_id FROM admins WHERE username = ?",
            (username,)
        )

        if cursor.fetchone():
            conn.close()
            flash("Username already exists.", "danger")
            return redirect("/register")

        # Mobile exists check
        cursor.execute(
            "SELECT admin_id FROM admins WHERE mobile = ?",
            (mobile,)
        )

        if cursor.fetchone():
            conn.close()
            flash("Mobile number is already registered.", "danger")
            return redirect("/register")

        hashed_password = generate_password_hash(password)

        cursor.execute(
            """
            INSERT INTO admins (full_name, username, mobile, email, password, role)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (full_name, username, mobile, email, hashed_password, "Admin")
        )

        conn.commit()
        conn.close()
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

        conn = get_connection()
        cursor = conn.cursor()

        # Require BOTH full name AND mobile to match — prevents reset with
        # just a known phone number.
        cursor.execute(
            """
            SELECT * FROM admins
            WHERE mobile = ?
            AND LOWER(full_name) = LOWER(?)
            """,
            (mobile, full_name)
        )

        admin = cursor.fetchone()

        if not admin:
            conn.close()
            flash(
                "No account found with that name and mobile number.",
                "danger"
            )
            return redirect("/forgot-password")

        hashed_password = generate_password_hash(new_password)

        cursor.execute(
            """
            UPDATE admins
            SET password = ?
            WHERE admin_id = ?
            """,
            (hashed_password, admin["admin_id"])
        )

        conn.commit()
        conn.close()
        clear_rate_limit("forgot_password")

        flash("Password changed successfully. Please login.", "success")

        return redirect(url_for("auth.login"))

    return render_template("auth/forgot_password.html")
