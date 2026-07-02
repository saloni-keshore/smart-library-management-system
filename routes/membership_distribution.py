from flask import Blueprint, render_template, session, redirect
from database.db import get_connection

membership_distribution_bp = Blueprint(
    "membership_distribution",
    __name__,
    url_prefix="/membership-distribution"
)


@membership_distribution_bp.route("/")
def index():

    if "admin_id" not in session:
        return redirect("/")

    admin_id = session["admin_id"]

    conn = get_connection()
    cursor = conn.cursor()

    # We will add queries step by step

    conn.close()

    return render_template(
        "memberships/distribution.html"
    )