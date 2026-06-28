from flask import Flask

# Import Blueprints
from routes.auth import auth_bp
from routes.dashboard import dashboard_bp


def create_app():
    app = Flask(__name__)

    app.config["SECRET_KEY"] = "smart_library_secret"

    # Register Blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)