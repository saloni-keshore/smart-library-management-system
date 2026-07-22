import calendar

from flask import Blueprint, render_template, session, redirect

from database.cashbook_queries import get_monthly_income, get_monthly_expense
from database.bi_queries import (
    last_n_months,
    get_monthly_new_memberships,
    get_business_health_score,
    get_revenue_growth,
    classify_revenue_health,
    classify_expense_health,
    get_top_revenue_sources,
    get_top_expense_categories,
    get_action_items,
    get_business_timeline,
)

business_intelligence_bp = Blueprint(
    "business_intelligence",
    __name__,
    url_prefix="/business-intelligence"
)

TREND_MONTHS = 6


def _month_label(month_key):
    year, month = month_key.split("-")
    return f"{calendar.month_abbr[int(month)]} {year}"


def _build_revenue_trend_chart(admin_id, months):
    """Chart.js-ready {labels, datasets} for the Revenue Trend line chart.

    Profit is derived locally from the same income/expense totals already
    fetched here, same pattern as Cashbook's _build_income_expense_chart -
    not a second call to get_monthly_profit(), which would re-run both
    queries again.
    """

    income = get_monthly_income(admin_id)
    expense = get_monthly_expense(admin_id)
    profit = {m: income.get(m, 0) - expense.get(m, 0) for m in months}

    return {
        "labels": [_month_label(m) for m in months],
        "datasets": [
            {
                "label": "Revenue",
                "data": [income.get(m, 0) for m in months],
                "borderColor": "#2563eb",
                "backgroundColor": "rgba(37, 99, 235, 0.10)",
                "tension": 0.4,
                "fill": True
            },
            {
                "label": "Expenses",
                "data": [expense.get(m, 0) for m in months],
                "borderColor": "#ef4444",
                "backgroundColor": "rgba(239, 68, 68, 0.08)",
                "tension": 0.4,
                "fill": True
            },
            {
                "label": "Profit",
                "data": [profit[m] for m in months],
                "borderColor": "#7c3aed",
                "backgroundColor": "rgba(124, 58, 237, 0.08)",
                "tension": 0.4,
                "fill": True
            }
        ]
    }


def _build_membership_growth_chart(admin_id, months):
    """Chart.js-ready {labels, datasets} for the Membership Growth area chart."""

    new_memberships = get_monthly_new_memberships(admin_id)

    return {
        "labels": [_month_label(m) for m in months],
        "datasets": [
            {
                "label": "New Memberships",
                "data": [new_memberships.get(m, 0) for m in months],
                "borderColor": "#7c3aed",
                "backgroundColor": "rgba(124, 58, 237, 0.18)",
                "tension": 0.35,
                "fill": True
            }
        ]
    }


@business_intelligence_bp.route("/")
def index():

    if "admin_id" not in session:
        return redirect("/")

    admin_id = session["admin_id"]
    months = last_n_months(TREND_MONTHS)

    health_score = get_business_health_score(admin_id)
    revenue_growth = get_revenue_growth(admin_id)
    revenue_health_status = classify_revenue_health(revenue_growth["growth_pct"])
    expense_health = classify_expense_health(admin_id)

    return render_template(
        "business_intelligence/index.html",
        health_score=health_score,
        revenue_growth=revenue_growth,
        revenue_health_status=revenue_health_status,
        expense_health=expense_health,
        action_items=get_action_items(admin_id),
        top_revenue_sources=get_top_revenue_sources(admin_id, limit=5),
        top_expense_categories=get_top_expense_categories(admin_id, limit=5),
        timeline=get_business_timeline(admin_id, limit=8),
        revenue_trend_chart=_build_revenue_trend_chart(admin_id, months),
        membership_growth_chart=_build_membership_growth_chart(admin_id, months),
    )
