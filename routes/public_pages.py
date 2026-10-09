from flask import Blueprint, render_template


public_pages_bp = Blueprint("public_pages", __name__)


@public_pages_bp.get("/home")
def home():
    return render_template("public/home.html")


@public_pages_bp.get("/privacy-policy")
def privacy_policy():
    return render_template("public/privacy_policy.html")


@public_pages_bp.get("/terms-of-service")
def terms_of_service():
    return render_template("public/terms_of_service.html")
