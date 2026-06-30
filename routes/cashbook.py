from flask import Blueprint, render_template

cashbook_bp = Blueprint(
    "cashbook",
    __name__,
    url_prefix="/cashbook"
)


@cashbook_bp.route("/")
def index():
    return render_template("cashbook/index.html")
