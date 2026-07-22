import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

from flask import Flask, abort, render_template, request, session

from config import DevelopmentConfig, ProductionConfig
from database.db import initialize_database
from utils.security import csrf_token, validate_csrf

from routes.auth import auth_bp
from routes.dashboard import dashboard_bp
from routes.enquiries import enquiry_bp
from routes.student import student_bp
from routes.membership import membership_bp
from routes.payment import payment_bp
from routes.cashbook import cashbook_bp
from routes.report import report_bp
from routes.setting import setting_bp
from routes.notification import notification_bp, get_notification_summary
from routes.membership_analytics import membership_analytics_bp
from routes.membership_distribution import membership_distribution_bp
from routes.business_intelligence import business_intelligence_bp
from database.notification_settings_queries import get_notification_settings_cached

DEFAULT_NAV_NOTIFICATION_PREFS = {
    "dash_show_badge_count": True,
    "dash_show_expiry_today": True,
    "dash_show_expiry_tomorrow": True,
    "dash_show_overdue": True,
}

def _configure_logging(app):
    if app.testing:
        return
    log_directory = Path(app.instance_path)
    log_directory.mkdir(parents=True, exist_ok=True)
    log_path = log_directory / "smart-library.log"
    if any(
        isinstance(handler, RotatingFileHandler)
        and Path(handler.baseFilename) == log_path
        for handler in app.logger.handlers
    ):
        return
    handler = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=5)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    app.logger.setLevel(app.config["LOG_LEVEL"])
    app.logger.addHandler(handler)


def create_app(test_config=None):
    app = Flask(__name__)
    environment = os.environ.get("APP_ENV", "production").lower()
    app.config.from_object(DevelopmentConfig if environment == "development" else ProductionConfig)
    if test_config:
        app.config.update(test_config)
    if not app.config.get("SECRET_KEY") and not app.testing:
        raise RuntimeError("SECRET_KEY must be set before starting the application.")
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = "test-secret-key"

    initialize_database()
    _configure_logging(app)

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(enquiry_bp)
    app.register_blueprint(student_bp)
    app.register_blueprint(membership_bp)
    app.register_blueprint(payment_bp)
    app.register_blueprint(cashbook_bp)
    app.register_blueprint(report_bp)
    app.register_blueprint(setting_bp)
    app.register_blueprint(notification_bp)
    app.register_blueprint(membership_analytics_bp)
    app.register_blueprint(membership_distribution_bp)
    app.register_blueprint(business_intelligence_bp)

    @app.before_request
    def enforce_request_security():
        csrf_token()
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and not validate_csrf():
            abort(400, "Your form has expired. Please refresh the page and try again.")

    @app.after_request
    def set_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        if request.is_secure:
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response

    @app.context_processor
    def inject_security_values():
        return {"csrf_token": csrf_token}

    @app.errorhandler(400)
    def bad_request(error):
        return render_template("errors/error.html", code=400, message=getattr(error, "description", "Invalid request.")), 400

    @app.errorhandler(404)
    def not_found(error):
        return render_template("errors/error.html", code=404, message="The page you requested was not found."), 404

    @app.errorhandler(405)
    def method_not_allowed(error):
        return render_template("errors/error.html", code=405, message="This action requires a valid form submission."), 405

    @app.errorhandler(413)
    def file_too_large(error):
        return render_template("errors/error.html", code=413, message="The uploaded file is too large."), 413

    @app.errorhandler(500)
    def internal_error(error):
        app.logger.exception("Unhandled application error")
        return render_template("errors/error.html", code=500, message="Something went wrong. Please try again."), 500
    @app.context_processor
    def inject_notification_summary():
        if "admin_id" not in session:
            return {
                "nav_notifications": None,
                "nav_notification_prefs": DEFAULT_NAV_NOTIFICATION_PREFS,
            }

        settings = get_notification_settings_cached(session["admin_id"])
        prefs = (
            {
                "dash_show_badge_count": bool(settings["dash_show_badge_count"]),
                "dash_show_expiry_today": bool(settings["dash_show_expiry_today"]),
                "dash_show_expiry_tomorrow": bool(settings["dash_show_expiry_tomorrow"]),
                "dash_show_overdue": bool(settings["dash_show_overdue"]),
            }
            if settings else DEFAULT_NAV_NOTIFICATION_PREFS
        )

        return {
            "nav_notifications": get_notification_summary(session["admin_id"]),
            "nav_notification_prefs": prefs,
        }

    return app


if __name__ == "__main__":
    create_app().run()
