"""Placeholder for Panda's future predictive features (Phase 2+).

Nothing in this file is wired into any route, service, or the frontend -
every function is an intentional stub so the eventual real implementation
has an agreed name and signature to fill in, instead of being invented
from scratch alongside whatever model/approach is chosen later. Calling
any of these today raises NotImplementedError; nothing in this codebase
calls them yet.
"""


def forecast_revenue(admin_id, months_ahead=1):
    """Planned: project future Cashbook income from historical trend
    (see database/bi_queries.py's get_revenue_growth/get_monthly_income
    for the historical data this would train or extrapolate from)."""

    raise NotImplementedError("Revenue forecasting is not implemented yet (Phase 2).")


def forecast_membership_churn(admin_id):
    """Planned: estimate which active members are likely to not renew,
    building on the rule-based retention scoring already in
    database/ai_center_queries.py's compute_student_risk() - but a model
    trained on historical renewal outcomes rather than fixed weights."""

    raise NotImplementedError("Membership churn forecasting is not implemented yet (Phase 2).")


def forecast_seat_demand(admin_id):
    """Planned: project future per-shift occupancy from historical trend
    (see database/bi_queries.py's get_monthly_occupancy_trend for the
    historical data this would train or extrapolate from)."""

    raise NotImplementedError("Seat demand forecasting is not implemented yet (Phase 2).")
