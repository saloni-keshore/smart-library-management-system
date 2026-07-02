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
    @app.context_processor
    def inject_notification_summary():
        if "admin_id" not in session:
            return {"nav_notifications": None}

        return {"nav_notifications": get_notification_summary(session["admin_id"])}

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
