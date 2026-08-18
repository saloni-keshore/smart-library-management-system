"""Read-only data aggregation for Panda's "Today's AI Insights" panel.

Every function here is a thin, honest wrapper around data this app already
computes elsewhere - deliberately reused rather than re-queried, so a
number Panda shows always agrees with the page that owns it:

- Revenue trend reuses `database/bi_queries.py`'s `get_revenue_growth()`,
  the same figure Business Intelligence's health score is built from.
- Expiring memberships reuses `routes/notification.py`'s
  `get_notification_summary()`, the same bucketing the navbar bell uses.
- Shift utilization reuses `database/bi_queries.py`'s
  `get_occupancy_summary()`, the same figure Occupancy Analytics shows.

`panda/notifications.py` turns these raw numbers into user-facing insight
cards; this module never formats a message and never decides a threshold -
keeping that split means a future forecasting model (panda/forecasting.py)
can slot in here as an additional data source without notifications.py
having to change how it decides what's worth surfacing.
"""

from database.bi_queries import get_revenue_growth, get_occupancy_summary
from routes.notification import get_notification_summary


def get_revenue_trend(admin_id):
    """This month vs last month's income - see
    `database/bi_queries.py.get_revenue_growth()` for the underlying
    calculation (Cashbook income, not just fee revenue)."""

    return get_revenue_growth(admin_id)


def get_expiring_memberships(admin_id):
    """Memberships expired or expiring within the navbar bell's own 3-day
    window - see `routes/notification.py.get_notification_summary()`."""

    return get_notification_summary(admin_id)["counts"]


def get_shift_utilization(admin_id):
    """Per-shift occupancy (capacity vs occupied) - see
    `database/bi_queries.py.get_occupancy_summary()`."""

    return get_occupancy_summary(admin_id)
