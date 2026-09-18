from flask import Blueprint, url_for, session, redirect

from utils.security import login_required

membership_analytics_bp = Blueprint(
    "membership_analytics",
    __name__,
    url_prefix="/membership-analytics"
)


@membership_analytics_bp.route("/")
@login_required
def index():
    """Membership Analytics has no implementation of its own - its template
    was a 0-byte file, so this route previously rendered a completely blank
    page (no layout/nav/sidebar - a dead end for anyone reaching it).
    Membership Distribution already covers the same data fully; redirect to
    it, the same pattern routes/report.py already uses for its own
    superseded page."""

    return redirect(url_for("membership_distribution.index"))