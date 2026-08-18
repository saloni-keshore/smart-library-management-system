"""Turns panda/insights.py's raw numbers into the user-facing "Today's AI
Insights" cards shown inside the Panda panel and counted on the floating
button's notification badge.

Each check below is intentionally simple and rule-based (no model, no
forecasting) - exactly the three example insights requested for this phase:
revenue trend, memberships expiring soon, and shift under-utilization. A
check that finds nothing worth flagging contributes no card; there is no
"everything is fine" filler card, so an admin with a healthy library sees
an empty, quiet list rather than manufactured positivity.

Adding a fourth insight later means adding one more `_check_*` function
here and appending it to `get_notifications()` - it does not touch
routes.py, services.py, or the frontend, which only ever render whatever
list this module returns.
"""

from panda import insights

REVENUE_DROP_THRESHOLD_PCT = -5
UNDERUTILIZED_THRESHOLD_PCT = 50


def _check_revenue_trend(admin_id):
    trend = insights.get_revenue_trend(admin_id)

    if trend["growth_pct"] > REVENUE_DROP_THRESHOLD_PCT:
        return None

    return {
        "id": "revenue_trend",
        "type": "revenue",
        "severity": "warning",
        "icon": "bi-graph-down-arrow",
        "title": "Revenue is lower this month",
        "message": (
            f"This month's income is {abs(trend['growth_pct'])}% lower than "
            f"last month (₹{trend['current_month']:,.0f} vs "
            f"₹{trend['previous_month']:,.0f})."
        ),
    }


def _check_expiring_memberships(admin_id):
    counts = insights.get_expiring_memberships(admin_id)

    if counts["total"] == 0:
        return None

    severity = "critical" if counts["expired"] or counts["today"] else "warning"

    return {
        "id": "expiring_memberships",
        "type": "membership",
        "severity": severity,
        "icon": "bi-person-vcard",
        "title": "Memberships expire soon",
        "message": (
            f"{counts['total']} membership(s) are expired or expiring within "
            "3 days - review them before they lapse."
        ),
    }


def _check_shift_utilization(admin_id):
    summary = insights.get_shift_utilization(admin_id)

    underutilized = [
        shift for shift in summary["shifts"]
        if shift["capacity"] > 0 and shift["utilization_pct"] < UNDERUTILIZED_THRESHOLD_PCT
    ]
    if not underutilized:
        return None

    worst = min(underutilized, key=lambda shift: shift["utilization_pct"])

    return {
        "id": "shift_utilization",
        "type": "occupancy",
        "severity": "info",
        "icon": "bi-door-open",
        "title": f"{worst['name']} seats are underutilized",
        "message": (
            f"Only {worst['utilization_pct']}% of {worst['name'].lower()} seats "
            f"are occupied ({worst['occupied']}/{worst['capacity']})."
        ),
    }


_CHECKS = (_check_revenue_trend, _check_expiring_memberships, _check_shift_utilization)


def get_notifications(admin_id):
    """Every currently-true insight for this admin, most in the order the
    checks are defined above. Never raises on a library with no data yet -
    each underlying insights.py call already returns neutral/zero values
    for an empty library, which simply produces no cards."""

    cards = []
    for check in _CHECKS:
        card = check(admin_id)
        if card is not None:
            cards.append(card)
    return cards
