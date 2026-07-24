from flask import (
    Blueprint,
    render_template,
    session,
    redirect
)

from database.membership_queries import get_memberships_for_admin, get_days_left


notification_bp = Blueprint(
    "notification",
    __name__,
    url_prefix="/notifications"
)


CATEGORY_META = {
    "today": {
        "label": "Expires Today",
        "icon": "🟢",
        "badge_class": "bg-success",
        "page_title": "Memberships Expiring Today"
    },
    "tomorrow": {
        "label": "Expires Tomorrow",
        "icon": "🟡",
        "badge_class": "bg-warning text-dark",
        "page_title": "Memberships Expiring Tomorrow"
    },
    "three_days": {
        "label": "Expires in 3 Days",
        "icon": "🟠",
        "badge_class": "bg-orange",
        "page_title": "Memberships Expiring in 3 Days"
    },
    "expired": {
        "label": "Expired",
        "icon": "🔴",
        "badge_class": "bg-danger",
        "page_title": "Expired Memberships"
    },
}


def get_notification_summary(admin_id):
    """
    Fetch every membership expiring within the next 3 days (or already
    expired) and bucket the results by category, so the navbar dropdown and
    the full notifications page share one source of truth. Reads Supabase
    `students`/`memberships` (ADR-23) via
    database.membership_queries.get_memberships_for_admin() instead of the
    SQLite mirror.
    """

    memberships = get_memberships_for_admin(admin_id)
    cutoff = 3

    buckets = {"today": [], "tomorrow": [], "three_days": [], "expired": []}

    for row in memberships:
        if row["membership_status"] != "Active":
            continue

        days_left = get_days_left(row["end_date"])
        if days_left is None or days_left > cutoff:
            continue

        row["days_left"] = days_left

        if days_left < 0:
            buckets["expired"].append(row)
        elif days_left == 0:
            buckets["today"].append(row)
        elif days_left == 1:
            buckets["tomorrow"].append(row)
        else:
            buckets["three_days"].append(row)

    for bucket in buckets.values():
        bucket.sort(key=lambda row: row["end_date"])

    counts = {key: len(items) for key, items in buckets.items()}
    counts["total"] = sum(counts.values())

    return {
        "buckets": buckets,
        "counts": counts,
        "meta": CATEGORY_META,
    }


@notification_bp.route("/")
@notification_bp.route("/<filter_type>")
def index(filter_type=None):

    if "admin_id" not in session:
        return redirect("/")

    admin_id = session["admin_id"]

    summary = get_notification_summary(admin_id)

    if filter_type in CATEGORY_META:
        notifications = summary["buckets"][filter_type]
        page_title = CATEGORY_META[filter_type]["page_title"]
    else:
        notifications = (
            summary["buckets"]["expired"]
            + summary["buckets"]["today"]
            + summary["buckets"]["tomorrow"]
            + summary["buckets"]["three_days"]
        )
        page_title = "All Notifications"

    return render_template(
        "notification/index.html",
        notifications=notifications,
        page_title=page_title,
        filter_type=filter_type
    )
