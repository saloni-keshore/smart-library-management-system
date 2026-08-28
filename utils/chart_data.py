"""Chart.js-ready ``{labels, datasets}`` builders for the Dashboard and
Membership Distribution pages.

These replace the old server-side matplotlib PNGs in ``utils/charts.py``
(removed so the app installs no matplotlib/numpy and fits a serverless,
read-only-filesystem host). The rendering now happens client-side with
Chart.js, exactly like the Business Intelligence and Cashbook pages
(``routes/business_intelligence.py`` ``_build_*_chart`` + ``static/js``).

Every function here is pure: it takes already-fetched rows (or an
admin_id plus a query function) and returns a plain dict, with no I/O of
its own beyond the query helpers it is handed.
"""

from datetime import date

from database.membership_queries import get_memberships_for_admin
from database.payment_queries import get_payments_for_admin
from utils.normalization import normalize_category

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

REVENUE_LINE_COLOR = "#2563eb"
REVENUE_FILL_COLOR = "rgba(37, 99, 235, 0.12)"

# Same palette the old matplotlib donut used (keys are normalize_category'd,
# i.e. upper-case). PLAN_CHART_FALLBACK_COLOR covers any non-standard plan.
PLAN_CHART_COLORS = {
    "MONTHLY": "#2563eb",
    "QUARTERLY": "#06b6d4",
    "HALF-YEARLY": "#f59e0b",
    "YEARLY": "#7c3aed",
}
PLAN_CHART_FALLBACK_COLOR = "#94a3b8"


def plan_color(label):
    """Colour for a plan label in any casing ('Monthly', 'monthly', ...)."""
    return PLAN_CHART_COLORS.get(normalize_category(label), PLAN_CHART_FALLBACK_COLOR)


def _monthly_revenue_for_year(payments, year):
    """Sums each payment's amount_paid into its calendar month, restricted
    to `year` - split out so the this_year vs last_year bucketing can be
    unit-tested without Supabase or a chart library. (Moved verbatim from
    the removed utils/charts.py.)"""

    year_str = str(year)
    revenue = [0] * 12

    for p in payments:
        payment_date = p["payment_date"]
        if not payment_date or not payment_date.startswith(year_str):
            continue
        month_index = int(payment_date[5:7]) - 1
        revenue[month_index] += p["amount_paid"] or 0

    return revenue


def build_revenue_chart_data(admin_id, period="this_year"):
    """Chart.js ``{labels, datasets}`` for the Dashboard's Revenue Overview
    line chart, from Supabase `payments` (ADR-25) grouped by calendar month
    for the selected year (`period`: "this_year" or "last_year")."""

    payments = get_payments_for_admin(admin_id)
    target_year = date.today().year - 1 if period == "last_year" else date.today().year
    revenue = _monthly_revenue_for_year(payments, target_year)

    return {
        "labels": list(MONTHS),
        "datasets": [
            {
                "label": "Revenue",
                "data": revenue,
                "borderColor": REVENUE_LINE_COLOR,
                "backgroundColor": REVENUE_FILL_COLOR,
                "tension": 0.4,
                "fill": True,
                "pointRadius": 3,
                "pointBackgroundColor": "#ffffff",
                "pointBorderColor": REVENUE_LINE_COLOR,
                "pointBorderWidth": 2,
            }
        ],
    }


def _plan_counts(memberships):
    """{plan_label: count} keyed by normalize_category'd plan name,
    ranked highest-count first."""
    counts = {}
    for m in memberships:
        plan = normalize_category(m["plan_name"])
        counts[plan] = counts.get(plan, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: kv[1], reverse=True))


def build_membership_chart_data(admin_id):
    """Chart.js ``{labels, datasets}`` for the Dashboard's Membership
    Distribution doughnut, from Supabase `students`/`memberships` (ADR-23).
    Empty ``labels`` means "no membership data yet" - the JS renders an
    empty state for that."""

    counts = _plan_counts(get_memberships_for_admin(admin_id))
    labels = list(counts.keys())

    return {
        "labels": labels,
        "datasets": [
            {
                "data": [counts[label] for label in labels],
                "backgroundColor": [plan_color(label) for label in labels],
                "borderColor": "#ffffff",
                "borderWidth": 2,
            }
        ],
    }


def build_plan_distribution_chart_data(plan_counts):
    """Chart.js ``{labels, datasets}`` for the Membership Distribution
    page's larger doughnut. Takes the ``plan_counts`` dict that
    ``routes/membership_distribution.py`` already computes (Title-Case
    keys in PLAN_ORDER); zero-count plans are dropped from the doughnut."""

    labels = [plan for plan, count in plan_counts.items() if count]

    return {
        "labels": labels,
        "datasets": [
            {
                "data": [plan_counts[label] for label in labels],
                "backgroundColor": [plan_color(label) for label in labels],
                "borderColor": "#ffffff",
                "borderWidth": 2,
            }
        ],
    }
