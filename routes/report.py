from flask import Blueprint, render_template

report_bp = Blueprint(
    "report",
    __name__,
    url_prefix="/reports"
)


@report_bp.route("/")
def index():
    return render_template("reports/index.html")
