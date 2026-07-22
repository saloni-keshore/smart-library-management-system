import os
from flask import Flask, session

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

def create_app():
    app = Flask(__name__)

    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "smart_library_secret")

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


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
