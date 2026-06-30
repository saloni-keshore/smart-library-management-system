from flask import Blueprint, render_template

setting_bp = Blueprint(
    "setting",
    __name__,
    url_prefix="/settings"
)


@setting_bp.route("/")
def index():
    return render_template("settings/index.html")
