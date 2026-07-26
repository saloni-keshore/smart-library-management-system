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
    get_purpose_breakdown,
    get_revenue_time_windows,
    get_monthly_fee_revenue,
    get_revenue_by_plan,
    get_revenue_by_payment_mode,
    get_payment_mode_usage_counts,
    get_new_vs_renewal_revenue,
    get_revenue_collection_summary,
    get_avg_revenue_per_student,
    get_occupancy_summary,
    get_monthly_occupancy_trend,
    get_occupancy_by_purpose,
    get_occupancy_by_plan,
    get_purpose_shift_matrix,
    get_occupancy_insights,
    CANONICAL_SHIFTS,
    OTHER_SHIFT_LABEL,
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


# ==========================================================================
# ANALYTICS PAGES (Purpose / Revenue / Occupancy)
#
# All three are now wired to real Supabase data. Purpose Analytics
# (_purpose_analytics_data, Phase 1), Revenue Analytics
# (_revenue_analytics_data, Phase 2) and Occupancy Analytics
# (_occupancy_analytics_data, Phase 3) each call their own
# database/bi_queries.py aggregate helpers and shape the result into the
# same {kpis, *_chart, table_rows/shifts} structure their old hardcoded
# placeholder used, so their templates only needed new cards/canvases
# added for metrics the placeholder never had, not their existing ones
# changed shape. Occupancy has no seat/attendance table to read (see
# bi_queries.py's Occupancy Analytics section docstring for how capacity/
# occupancy are reconstructed from `library_settings`/`students`/
# `memberships` instead - ADR-38).
# ==========================================================================

PURPOSE_CHART_COLORS = [
    "#2563eb", "#16a34a", "#f59e0b", "#7c3aed", "#06b6d4",
    "#ec4899", "#f97316", "#64748b",
]

REVENUE_TREND_MONTHS = 12


def _purpose_analytics_data(admin_id):
    """Real Purpose Analytics data: students and revenue grouped by each
    student's `purpose`, aggregated server-side by
    database.bi_queries.get_purpose_breakdown(). Returns the same
    {kpis, *_chart, table_rows} shape the old placeholder used, so
    templates/business_intelligence/purpose_analytics.html and
    static/js/bi_purpose_analytics.js need no changes.
    """

    breakdown = get_purpose_breakdown(admin_id)
    if not breakdown:
        breakdown = [{"purpose": "No Data", "students": 0, "revenue": 0}]

    purposes = [row["purpose"] for row in breakdown]
    students = [row["students"] for row in breakdown]
    revenue = [row["revenue"] for row in breakdown]
    colors = [PURPOSE_CHART_COLORS[i % len(PURPOSE_CHART_COLORS)] for i in range(len(purposes))]

    total_students = sum(students)
    total_revenue = sum(revenue)

    top_by_students = max(breakdown, key=lambda r: r["students"])
    top_by_revenue = max(breakdown, key=lambda r: r["revenue"])

    return {
        "kpis": {
            "total_students": total_students,
            "total_revenue": total_revenue,
            "top_purpose": top_by_students["purpose"] if total_students else "N/A",
            "top_revenue_purpose": top_by_revenue["purpose"] if total_revenue else "N/A",
            "avg_revenue_per_student": round(total_revenue / total_students) if total_students else 0,
        },
        "students_chart": {
            "labels": purposes,
            "datasets": [{
                "label": "Students",
                "data": students,
                "backgroundColor": colors,
                "borderRadius": 8,
            }]
        },
        "distribution_chart": {
            "labels": purposes,
            "datasets": [{
                "data": students,
                "backgroundColor": colors,
                "borderWidth": 0,
            }]
        },
        "revenue_chart": {
            "labels": purposes,
            "datasets": [{
                "label": "Revenue",
                "data": revenue,
                "backgroundColor": colors,
                "borderRadius": 8,
            }]
        },
        "revenue_distribution_chart": {
            "labels": purposes,
            "datasets": [{
                "data": revenue,
                "backgroundColor": colors,
                "borderWidth": 0,
            }]
        },
        "table_rows": [
            {
                "purpose": row["purpose"],
                "students": row["students"],
                "student_pct": round(row["students"] * 100 / total_students, 1) if total_students else 0,
                "revenue": row["revenue"],
                "revenue_pct": round(row["revenue"] * 100 / total_revenue, 1) if total_revenue else 0,
                "avg_revenue": round(row["revenue"] / row["students"]) if row["students"] else 0,
            }
            for row in breakdown
        ],
    }


def _revenue_analytics_data(admin_id):
    """Real Revenue Analytics data - Business Intelligence Phase 2. Every
    KPI/chart here reads Supabase `payments`/`memberships` (via
    database/bi_queries.py's revenue helpers) instead of the hardcoded
    _revenue_analytics_placeholder() this replaces. The template
    (templates/business_intelligence/revenue_analytics.html) and its JS
    (static/js/bi_revenue_analytics.js) gained new KPI cards/chart canvases
    for the metrics the placeholder never had (time-window revenue,
    collection split, payment mode, new-vs-renewal), but every chart/KPI
    that already existed kept its original id/shape.
    """

    months = last_n_months(REVENUE_TREND_MONTHS)
    month_labels = [_month_label(m) for m in months]

    windows = get_revenue_time_windows(admin_id)
    collection = get_revenue_collection_summary(admin_id)
    avg_per_student = get_avg_revenue_per_student(admin_id)

    monthly_revenue = get_monthly_fee_revenue(admin_id)
    monthly_expense = get_monthly_expense(admin_id)
    revenue_series = [monthly_revenue.get(m, 0) for m in months]
    expense_series = [monthly_expense.get(m, 0) for m in months]
    profit_series = [r - e for r, e in zip(revenue_series, expense_series)]

    plan_revenue = get_revenue_by_plan(admin_id)
    purpose_breakdown = get_purpose_breakdown(admin_id)
    purpose_revenue = {row["purpose"]: row["revenue"] for row in purpose_breakdown if row["revenue"] > 0}
    payment_mode_revenue = get_revenue_by_payment_mode(admin_id)
    payment_mode_counts = get_payment_mode_usage_counts(admin_id)
    new_vs_renewal = get_new_vs_renewal_revenue(admin_id)

    # Fastest growing month: the largest month-over-month % increase inside
    # the trend window - needs a real previous month to compare against, so
    # starts scanning from the second month.
    best_growth_month, best_growth_pct = "N/A", 0
    for i in range(1, len(months)):
        previous, current = revenue_series[i - 1], revenue_series[i]
        if previous > 0:
            pct = round((current - previous) / previous * 100, 1)
        elif current > 0:
            pct = 100.0
        else:
            continue
        if best_growth_month == "N/A" or pct > best_growth_pct:
            best_growth_month, best_growth_pct = month_labels[i], pct

    top_plan, top_plan_revenue = next(iter(plan_revenue.items()), ("N/A", 0))
    top_purpose, top_purpose_revenue = max(
        purpose_revenue.items(), key=lambda kv: kv[1], default=("N/A", 0)
    )
    top_payment_mode, top_payment_mode_count = next(iter(payment_mode_counts.items()), ("N/A", 0))

    def _pie(totals):
        labels = list(totals.keys())
        values = list(totals.values())
        colors = [PURPOSE_CHART_COLORS[i % len(PURPOSE_CHART_COLORS)] for i in range(len(labels))]
        return {"labels": labels, "datasets": [{"data": values, "backgroundColor": colors, "borderWidth": 0}]}

    return {
        "kpis": {
            "total_revenue": windows["total"],
            "today_revenue": windows["today"],
            "week_revenue": windows["week"],
            "month_revenue": windows["month"],
            "year_revenue": windows["year"],
            "avg_revenue_per_student": avg_per_student,
            "expected_revenue": collection["expected"],
            "collected_revenue": collection["collected"],
            "pending_revenue": collection["pending"],
            "collection_pct": collection["collection_pct"],
        },
        "revenue_trend_chart": {
            "labels": month_labels,
            "datasets": [
                {
                    "label": "Revenue",
                    "data": revenue_series,
                    "borderColor": "#2563eb",
                    "backgroundColor": "rgba(37, 99, 235, 0.10)",
                    "tension": 0.4,
                    "fill": True,
                },
                {
                    "label": "Profit",
                    "data": profit_series,
                    "borderColor": "#7c3aed",
                    "backgroundColor": "rgba(124, 58, 237, 0.08)",
                    "tension": 0.4,
                    "fill": True,
                },
            ]
        },
        "monthly_revenue_chart": {
            "labels": month_labels,
            "datasets": [{
                "label": "Revenue",
                "data": revenue_series,
                "backgroundColor": "#2563eb",
                "borderRadius": 8,
            }]
        },
        "membership_revenue_chart": _pie(plan_revenue),
        "purpose_revenue_chart": _pie(purpose_revenue),
        "payment_mode_chart": _pie(payment_mode_revenue),
        "new_vs_renewal_chart": {
            "labels": ["New Admissions", "Renewal"],
            "datasets": [{
                "data": [new_vs_renewal["new_admissions"], new_vs_renewal["renewal"]],
                "backgroundColor": ["#2563eb", "#16a34a"],
                "borderWidth": 0,
            }]
        },
        "insights": {
            "top_plan": top_plan,
            "top_plan_revenue": top_plan_revenue,
            "top_purpose": top_purpose,
            "top_purpose_revenue": top_purpose_revenue,
            "best_growth_month": best_growth_month,
            "best_growth_pct": best_growth_pct,
            "top_payment_mode": top_payment_mode,
            "top_payment_mode_count": top_payment_mode_count,
        },
        "table_rows": [
            {
                "month": month_labels[i],
                "revenue": revenue_series[i],
                "expense": expense_series[i],
                "profit": profit_series[i],
            }
            for i in range(len(months))
        ],
    }


SHIFT_TIME_LABELS = {
    "Morning": "7:00 AM - 2:00 PM",
    "Afternoon": "2:00 PM - 8:00 PM",
    "Evening": "8:00 PM - 11:00 PM",
}

SHIFT_COLORS = {
    "Morning": "#2563eb",
    "Afternoon": "#f59e0b",
    "Evening": "#7c3aed",
    OTHER_SHIFT_LABEL: "#64748b",
}


def _occupancy_analytics_data(admin_id):
    """Real Occupancy Analytics data - Business Intelligence Phase 3. Every
    KPI/chart/table here reads Supabase `students`/`memberships`/
    `library_settings` (via database/bi_queries.py's occupancy helpers)
    instead of the hardcoded _occupancy_analytics_placeholder() this
    replaces. "Capacity" comes from each admin's own configured seating
    capacity (Settings > Library Profile, ADR-38), not a fabricated
    number - see bi_queries.py's Occupancy Analytics section docstring for
    what "occupied" means and how the historical trend is reconstructed.
    """

    months = last_n_months(TREND_MONTHS)
    month_labels = [_month_label(m) for m in months]

    summary = get_occupancy_summary(admin_id)
    shifts_by_name = {s["name"]: s for s in summary["shifts"]}
    shifts = [
        {**shifts_by_name[name], "time": SHIFT_TIME_LABELS[name]}
        for name in CANONICAL_SHIFTS
    ]

    trend = get_monthly_occupancy_trend(admin_id, months)
    purpose_occupancy = get_occupancy_by_purpose(admin_id)
    plan_occupancy = get_occupancy_by_plan(admin_id)
    matrix = get_purpose_shift_matrix(admin_id)
    top_purpose_rows = matrix["rows"][:8]

    distribution_labels = [s["name"] for s in shifts]
    distribution_data = [s["occupied"] for s in shifts]
    distribution_colors = [SHIFT_COLORS[s["name"]] for s in shifts]
    if summary["other_occupied"] > 0:
        distribution_labels.append(OTHER_SHIFT_LABEL)
        distribution_data.append(summary["other_occupied"])
        distribution_colors.append(SHIFT_COLORS[OTHER_SHIFT_LABEL])

    plan_labels = list(plan_occupancy.keys())
    plan_colors = [PURPOSE_CHART_COLORS[i % len(PURPOSE_CHART_COLORS)] for i in range(len(plan_labels))]

    top_plan, top_plan_count = next(iter(plan_occupancy.items()), ("N/A", 0))
    top_purpose, top_purpose_count = next(iter(purpose_occupancy.items()), ("N/A", 0))

    return {
        "kpis": {
            "total_seats": summary["total_capacity"],
            "occupied_seats": summary["total_occupied"],
            "available_seats": summary["total_available"],
            "occupancy_pct": summary["occupancy_pct"],
            "morning_occupancy_pct": shifts_by_name["Morning"]["utilization_pct"],
            "afternoon_occupancy_pct": shifts_by_name["Afternoon"]["utilization_pct"],
            "evening_occupancy_pct": shifts_by_name["Evening"]["utilization_pct"],
            "peak_shift": max(shifts, key=lambda s: s["utilization_pct"])["name"],
        },
        "shifts": shifts,
        "utilization_chart": {
            "labels": [s["name"] for s in shifts],
            "datasets": [
                {
                    "label": "Occupied",
                    "data": [s["occupied"] for s in shifts],
                    "backgroundColor": "#2563eb",
                    "borderRadius": 8,
                },
                {
                    "label": "Available",
                    "data": [s["available"] for s in shifts],
                    "backgroundColor": "#e2e8f0",
                    "borderRadius": 8,
                },
            ]
        },
        "trend_chart": {
            "labels": month_labels,
            "datasets": [{
                "label": "Occupancy Rate",
                "data": trend,
                "borderColor": "#16a34a",
                "backgroundColor": "rgba(22, 163, 74, 0.10)",
                "tension": 0.4,
                "fill": True,
            }]
        },
        "distribution_chart": {
            "labels": distribution_labels,
            "datasets": [{
                "data": distribution_data,
                "backgroundColor": distribution_colors,
                "borderWidth": 0,
            }]
        },
        "purpose_shift_chart": {
            "labels": [row["purpose"] for row in top_purpose_rows],
            "datasets": [
                {
                    "label": column,
                    "data": [row["counts"][column] for row in top_purpose_rows],
                    "backgroundColor": SHIFT_COLORS.get(column, "#94a3b8"),
                    "borderRadius": 6,
                }
                for column in matrix["columns"]
            ]
        },
        "membership_occupancy_chart": {
            "labels": plan_labels,
            "datasets": [{
                "label": "Occupied Seats",
                "data": list(plan_occupancy.values()),
                "backgroundColor": plan_colors,
                "borderRadius": 8,
            }]
        },
        "purpose_matrix": matrix,
        "breakdown": {
            "top_plan": top_plan,
            "top_plan_count": top_plan_count,
            "top_purpose": top_purpose,
            "top_purpose_count": top_purpose_count,
        },
        "insights": get_occupancy_insights(admin_id),
    }


@business_intelligence_bp.route("/purpose-analytics")
def purpose_analytics():

    if "admin_id" not in session:
        return redirect("/")

    return render_template(
        "business_intelligence/purpose_analytics.html",
        data=_purpose_analytics_data(session["admin_id"]),
    )


@business_intelligence_bp.route("/revenue-analytics")
def revenue_analytics():

    if "admin_id" not in session:
        return redirect("/")

    return render_template(
        "business_intelligence/revenue_analytics.html",
        data=_revenue_analytics_data(session["admin_id"]),
    )


@business_intelligence_bp.route("/occupancy-analytics")
def occupancy_analytics():

    if "admin_id" not in session:
        return redirect("/")

    return render_template(
        "business_intelligence/occupancy_analytics.html",
        data=_occupancy_analytics_data(session["admin_id"]),
    )
