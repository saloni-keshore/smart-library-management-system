from flask import (
    Blueprint,
    render_template,
    session,
    redirect
)

from database.db import get_connection


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
    expired) in a single query and bucket the results by category, so the
    navbar dropdown and the full notifications page share one source of
    truth and one query per page load.
    """

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            s.student_id,
            s.full_name,
            s.mobile,
            s.shift,
            s.purpose,
            s.join_date,
            s.status AS student_status,

            m.membership_id,
            m.plan_name,
            m.joining_date,
            m.end_date,
            m.pending_amount,
            m.membership_status,

            CAST(
                julianday(m.end_date) -
                julianday(DATE('now'))
            AS INTEGER) AS days_left

        FROM memberships m

        JOIN students s
            ON s.student_id = m.student_id

        WHERE
            s.admin_id = ?
            AND m.membership_status = 'Active'
            AND m.end_date <= DATE('now', '+3 day')

        ORDER BY m.end_date ASC
    """, (admin_id,))

    rows = cursor.fetchall()
    conn.close()

    buckets = {"today": [], "tomorrow": [], "three_days": [], "expired": []}

    for row in rows:
        days_left = row["days_left"]

        if days_left < 0:
            buckets["expired"].append(row)
        elif days_left == 0:
            buckets["today"].append(row)
        elif days_left == 1:
            buckets["tomorrow"].append(row)
        elif days_left <= 3:
            buckets["three_days"].append(row)

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
