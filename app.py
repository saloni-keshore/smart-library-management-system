from flask import Flask

# Import Blueprints
from routes.auth import auth_bp
from routes.dashboard import dashboard_bp
from routes.enquiries import enquiry_bp
from routes.student import student_bp
from routes.membership import membership_bp
from routes.payment import payment_bp

def create_app():
    app = Flask(__name__)

    app.config["SECRET_KEY"] = "smart_library_secret"

    # Register Blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(enquiry_bp)
    app.register_blueprint(student_bp)
    app.register_blueprint(membership_bp)
    app.register_blueprint(payment_bp)
    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)