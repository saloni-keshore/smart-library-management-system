from flask import Blueprint, render_template, session, redirect

membership_analytics_bp = Blueprint(
    "membership_analytics",
    __name__,
    url_prefix="/membership-analytics"
)

@membership_analytics_bp.route("/")
def index():

    if "admin_id" not in session:
        return redirect("/")

    return render_template(
        "membership/analytics.html"
    )