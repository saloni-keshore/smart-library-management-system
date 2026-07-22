from flask import Blueprint, url_for, session, redirect

membership_analytics_bp = Blueprint(
    "membership_analytics",
    __name__,
    url_prefix="/membership-analytics"
)


@membership_analytics_bp.route("/")
def index():
    """Membership Analytics has no implementation of its own - its template
    was a 0-byte file, so this route previously rendered a completely blank
    page (no layout/nav/sidebar - a dead end for anyone reaching it).
    Membership Distribution already covers the same data fully; redirect to
    it, the same pattern routes/report.py already uses for its own
    superseded page."""

    if "admin_id" not in session:
        return redirect("/")

    return redirect(url_for("membership_distribution.index"))