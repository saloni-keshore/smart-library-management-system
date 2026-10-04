"""Sign in with Google, via Supabase Auth (ADR-84).

Supabase Auth only proves "this person controls this Google account" -
login state is still Flask's own session cookie, exactly like password
login (routes/auth.py's start_admin_session()). The flow is server-side
OAuth with PKCE:

  /auth/google/start?intent=...  -> Supabase -> Google -> Supabase ->
  /auth/google/callback?code=... -> exchange the code (server to server)
                                    for the Google user + access token

intent:
  - login:   sign in; a Google account with no library goes to complete()
  - recover: "forgot password" - sign in, then set a new password without
             the old one (routes/setting.py security_settings(),
             session["pw_reset_until"])
  - link:    connect Google to the logged-in admin (Settings -> Security)

Free: Supabase Auth's Google provider and a Google Cloud OAuth client cost
nothing at this scale - the reason this replaced the name+mobile reset
rather than an SMS OTP. Setup steps are in docs/DEPLOYMENT.md.
"""

import time

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from postgrest.exceptions import APIError
from supabase_auth.errors import AuthError

from database.supabase_client import (
    build_pkce_auth_client,
    build_user_token_client,
    get_supabase_client,
)
from routes.auth import start_admin_session, validate_registration_fields
from utils.normalization import normalize_name, normalize_phone

google_auth_bp = Blueprint("google_auth", __name__, url_prefix="/auth/google")

INTENTS = ("login", "recover", "link")

# How long after "Recover with Google" the admin may set a new password
# without typing the current one.
PASSWORD_RESET_WINDOW_SECONDS = 600


def _disabled():
    return not current_app.config.get("GOOGLE_AUTH_ENABLED", False)


def _is_google_user(user):
    providers = (getattr(user, "app_metadata", None) or {}).get("providers") or []
    provider = (getattr(user, "app_metadata", None) or {}).get("provider")
    return "google" in providers or provider == "google"


@google_auth_bp.route("/start")
def start():

    if _disabled():
        flash("Google sign-in is not enabled.", "danger")
        return redirect(url_for("auth.login"))

    intent = request.args.get("intent", "login")
    if intent not in INTENTS:
        intent = "login"

    if intent == "link" and "admin_id" not in session:
        return redirect(url_for("auth.login"))

    session["oauth_intent"] = intent

    # build_pkce_auth_client() keeps the PKCE code verifier in the Flask
    # session so callback() - a separate request - can finish the exchange.
    try:
        oauth = build_pkce_auth_client().auth.sign_in_with_oauth({
            "provider": "google",
            "options": {"redirect_to": url_for("google_auth.callback", _external=True)},
        })
    except AuthError:
        current_app.logger.exception("Could not start Google sign-in")
        flash("Google sign-in is unavailable right now. Please try again.", "danger")
        return redirect(url_for("auth.login"))

    return redirect(oauth.url)


@google_auth_bp.route("/callback")
def callback():

    intent = session.pop("oauth_intent", "login")
    fallback = (
        url_for("setting.security_settings")
        if intent == "link" and "admin_id" in session
        else url_for("auth.login")
    )

    if request.args.get("error"):
        flash("Google sign-in was cancelled.", "warning")
        return redirect(fallback)

    code = request.args.get("code")
    if not code:
        flash("Google sign-in failed. Please try again.", "danger")
        return redirect(fallback)

    try:
        auth_response = build_pkce_auth_client().auth.exchange_code_for_session(
            {"auth_code": code}
        )
    except AuthError:
        current_app.logger.warning("Google code exchange failed", exc_info=True)
        flash("Google sign-in failed or expired. Please try again.", "danger")
        return redirect(fallback)

    user = auth_response.user
    auth_session = auth_response.session
    if user is None or auth_session is None or not _is_google_user(user):
        flash("Google sign-in failed. Please try again.", "danger")
        return redirect(fallback)

    if intent == "link":
        return _link(user)

    try:
        rows = (
            build_user_token_client(auth_session.access_token)
            .rpc("rpc_google_login_lookup")
            .execute()
            .data
        )
    except APIError:
        current_app.logger.exception("rpc_google_login_lookup failed")
        flash("Google sign-in failed. Please try again.", "danger")
        return redirect(url_for("auth.login"))

    admin = rows[0] if rows else None

    if admin is None:
        if intent == "recover":
            flash(
                "No library is connected to this Google account. Connect Google "
                "from Settings -> Security after logging in, or contact support.",
                "danger"
            )
            return redirect(url_for("auth.forgot_password"))

        # A new library, created by Google sign-in: ask for the few details
        # Google doesn't give us. The access token proves the Google
        # identity to rpc_register_admin_google() in complete().
        metadata = user.user_metadata or {}
        session["google_signup"] = {
            "access_token": auth_session.access_token,
            "expires_at": int(auth_session.expires_at or time.time() + 3600),
            "email": user.email or "",
            "name": metadata.get("full_name") or metadata.get("name") or "",
        }
        return redirect(url_for("google_auth.complete"))

    if admin.get("status") == "archived":
        flash(
            "This account has been archived and can no longer be accessed. "
            "Contact support if you need it reactivated.",
            "danger"
        )
        return redirect(url_for("auth.login"))

    start_admin_session(admin)

    if intent == "recover":
        session["pw_reset_until"] = int(time.time()) + PASSWORD_RESET_WINDOW_SECONDS
        flash("Signed in with Google. Set a new password below.", "success")
        return redirect(url_for("setting.security_settings"))

    flash("Login Successful!", "success")
    return redirect("/dashboard")


def _link(user):

    if "admin_id" not in session:
        return redirect(url_for("auth.login"))

    try:
        get_supabase_client().rpc(
            "rpc_link_google",
            {"p_auth_user_id": user.id, "p_email": user.email or ""},
        ).execute()
    except APIError as e:
        if e.message == "google_already_linked":
            flash("This Google account is already connected to another library.", "danger")
        else:
            current_app.logger.exception("rpc_link_google failed")
            flash("Could not connect Google. Please try again.", "danger")
        return redirect(url_for("setting.security_settings"))

    flash(f"Google account {user.email} connected. You can now sign in with Google.", "success")
    return redirect(url_for("setting.security_settings"))


@google_auth_bp.route("/complete", methods=["GET", "POST"])
def complete():
    """Create a library for a Google user who doesn't have one yet."""

    signup = session.get("google_signup")
    if not signup:
        return redirect(url_for("auth.login"))

    if signup["expires_at"] <= int(time.time()) + 30:
        session.pop("google_signup", None)
        flash("That Google sign-in has expired. Please sign in with Google again.", "warning")
        return redirect(url_for("auth.login"))

    form = {"full_name": signup["name"], "username": "", "mobile": ""}

    if request.method == "POST":

        form = {
            "full_name": normalize_name(request.form.get("full_name", "")),
            "username": request.form.get("username", "").strip().lower(),
            "mobile": normalize_phone(request.form.get("mobile", "")),
        }

        error = validate_registration_fields(
            form["full_name"], form["username"], form["mobile"]
        )

        if not error:
            try:
                rows = (
                    build_user_token_client(signup["access_token"])
                    .rpc("rpc_register_admin_google", {
                        "p_full_name": form["full_name"],
                        "p_username": form["username"],
                        "p_mobile": form["mobile"],
                    })
                    .execute()
                    .data
                )
            except APIError as e:
                rows = None
                error = {
                    "username_taken": "Username already exists.",
                    "mobile_taken": "Mobile number is already registered.",
                    "google_already_linked": (
                        "This Google account already has a library. Please sign in."
                    ),
                }.get(e.message, "Something went wrong. Please try again.")

            if rows:
                start_admin_session(rows[0])
                flash("Your library account is ready. Welcome!", "success")
                return redirect("/dashboard")

        flash(error or "Something went wrong. Please try again.", "danger")

    return render_template(
        "auth/google_complete.html",
        form=form,
        google_email=signup["email"],
    )
