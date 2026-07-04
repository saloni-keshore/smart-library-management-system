from flask import Blueprint, redirect, url_for

report_bp = Blueprint(
    "report",
    __name__,
    url_prefix="/reports"
)


@report_bp.route("/")
def index():
    # Reports has been replaced by the Business Intelligence Center.
    return redirect(url_for("business_intelligence.index"))
