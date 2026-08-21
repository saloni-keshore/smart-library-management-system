"""Panda's Part 5 ("Forecast") calculation engine (ADR-51).

Every function here is a **simple linear trend extrapolation** over this
admin's own real historical data - fit with plain-Python ordinary least
squares (`_linear_forecast()`), not a trained model. There is no
`scikit-learn`/`prophet`/`statsmodels` dependency anywhere in this project
(see `requirements.txt`, `PANDA_SPEC.md` Sec 16) and this module doesn't
change that - "forecast" here means "extend the straight line this admin's
own numbers have actually been tracing," nothing more, and every reply
built from these results says so explicitly (see
`panda/intents.py._reply_forecast()`).

Each function returns `None` when there isn't enough real historical
variation to extrapolate honestly, rather than projecting a "trend" from
1-2 data points or an all-zero window - see `MIN_MONTHS_FOR_FORECAST`.
Callers (`panda/insights.py`) must treat `None` as "can't forecast this
yet," the same "a check that finds nothing contributes nothing" convention
`panda/notifications.py` and `panda/insights.py.get_revenue_explanation()`
already follow - never substitute a fabricated number.

Historical data sources, all already-existing, admin-scoped functions -
this module adds no new database queries beyond the churn calculation
below, which reads the same `memberships` rows `database/bi_queries.py`'s
`get_monthly_occupancy_trend()` already reads:
- Revenue: `database/cashbook_queries.get_monthly_income()` (Cashbook
  income per month - the same figure `get_revenue_growth()` compares
  month-to-month for Part 1's plain revenue reply).
- Seat demand: `database/bi_queries.get_monthly_occupancy_trend()` (overall
  occupancy % per month, reconstructed from each membership's own
  joining_date/end_date range - the same function Occupancy Analytics'
  trend direction insight already uses).
- Membership churn: a new monthly lapse-rate calculation (see
  `forecast_membership_churn()`'s own docstring) - no monthly renewal/lapse
  rate exists anywhere else in this codebase to reuse, unlike the other
  two, so this is the one genuinely new aggregation Part 5 introduces.
"""

import calendar
from collections import defaultdict
from datetime import date

from database.bi_queries import get_monthly_occupancy_trend, get_upcoming_expiries, last_n_months
from database.cashbook_queries import get_monthly_income
from database.membership_queries import get_memberships_for_admin

# A trend fit through fewer than 3 real (nonzero) data points isn't a trend,
# it's a guess dressed up as one - see docs/DECISIONS.md ADR-51. Applies to
# all three forecasts below.
MIN_MONTHS_FOR_FORECAST = 3

# Calendar window every forecast is fit over - same 6-month span
# `get_occupancy_insights()` already uses for its own trend-direction check
# (database/bi_queries.py), not a new convention.
FORECAST_WINDOW_MONTHS = 6


def _linear_forecast(values, months_ahead=1):
    """Ordinary least-squares straight line through `values` (one point per
    sequential period, oldest first), projected `months_ahead` periods past
    the last one. Pure Python - no numpy/pandas dependency for something
    this small. Callers must ensure `len(values) >= 2` (division by zero
    otherwise) - in practice every caller here already enforces
    MIN_MONTHS_FOR_FORECAST (3) before reaching this point."""

    n = len(values)
    mean_x = (n - 1) / 2
    mean_y = sum(values) / n

    numerator = sum((x - mean_x) * (y - mean_y) for x, y in enumerate(values))
    denominator = sum((x - mean_x) ** 2 for x in range(n))
    slope = numerator / denominator if denominator else 0.0
    intercept = mean_y - slope * mean_x

    target_x = (n - 1) + months_ahead
    return slope * target_x + intercept


def _trend_direction(values):
    """"up"/"down"/"flat" - compares the first and last point in the
    window, the same comparison `get_occupancy_insights()` already uses for
    its own trend-direction insight (`trend[0]` vs `trend[-1]`), not a new
    convention invented for forecasting."""

    if values[-1] > values[0]:
        return "up"
    if values[-1] < values[0]:
        return "down"
    return "flat"


def forecast_revenue(admin_id, months_ahead=1):
    """Projects next month's Cashbook income from a straight-line fit over
    the last FORECAST_WINDOW_MONTHS calendar months (same source
    `get_revenue_growth()` compares month-to-month - see
    `database/cashbook_queries.get_monthly_income()`).

    Every month in the window is a real data point, including a genuine
    ₹0 month (a month with no recorded income is a real fact, not missing
    data) - what gates the "not enough data" case is having at least
    MIN_MONTHS_FOR_FORECAST *nonzero* months, so a brand-new admin whose
    whole window is ₹0 doesn't get a confidently-flat "₹0 projected" reply
    dressed up as a forecast; they get an honest "not enough data" one.

    Returns `{"projected_amount": float, "trend_direction": str,
    "months_used": int}` or `None` if fewer than MIN_MONTHS_FOR_FORECAST of
    the window's months have any recorded income."""

    months = last_n_months(FORECAST_WINDOW_MONTHS)
    income = get_monthly_income(admin_id)
    values = [income.get(month, 0) for month in months]

    if sum(1 for v in values if v > 0) < MIN_MONTHS_FOR_FORECAST:
        return None

    projected = max(0.0, _linear_forecast(values, months_ahead))

    return {
        "projected_amount": projected,
        "trend_direction": _trend_direction(values),
        "months_used": len(months),
    }


def forecast_seat_demand(admin_id):
    """Projects next month's overall occupancy % from a straight-line fit
    over the last FORECAST_WINDOW_MONTHS calendar months of
    `database/bi_queries.get_monthly_occupancy_trend()` - real history,
    reconstructed from each membership's own joining_date/end_date range
    (there is no seat/attendance log, see that function's own docstring),
    not a live snapshot repeated backwards.

    Same "need real nonzero variation, not just a padded-zero window" gate
    as `forecast_revenue()`. Clamped to [0, 100] - occupancy can't
    meaningfully forecast outside that range even if the fitted line would.

    Returns `{"projected_occupancy_pct": float, "trend_direction": str,
    "months_used": int}` or `None` if fewer than MIN_MONTHS_FOR_FORECAST of
    the window's months show any real occupancy."""

    months = last_n_months(FORECAST_WINDOW_MONTHS)
    values = get_monthly_occupancy_trend(admin_id, months)

    if sum(1 for v in values if v > 0) < MIN_MONTHS_FOR_FORECAST:
        return None

    projected = max(0.0, min(100.0, _linear_forecast(values)))

    return {
        "projected_occupancy_pct": round(projected, 1),
        "trend_direction": _trend_direction(values),
        "months_used": len(months),
    }


def forecast_membership_churn(admin_id):
    """Projects how many of the memberships expiring in the next 30 days
    are likely to lapse without a renewal, from this admin's own recent
    monthly lapse-rate history.

    No monthly renewal/lapse rate exists anywhere else in this codebase, so
    unlike the other two forecasts this computes one directly from
    `memberships` rows: for each of the last FORECAST_WINDOW_MONTHS
    calendar months, a membership counts as "expiring that month" if its
    `end_date` falls inside it, and as "lapsed" if that student has no
    *other* membership with a `joining_date` after that `end_date` - the
    exact same "did this student renew" test
    `database/ai_center_queries.py`'s `_renewal_signal()` already uses to
    detect a late renewal (ADR-39), reused here for consistency rather than
    reinvented. A month with zero memberships expiring contributes no rate
    (not a 0% one - "nothing was up for renewal" and "everyone renewed"
    are different facts, and conflating them would understate churn risk).

    The projected rate (from a straight-line fit over whichever months did
    have an expiring cohort) is applied to `get_upcoming_expiries(days=30)`
    - the real, already-existing count of memberships actually expiring
    soon right now - to produce a projected lapse count grounded in this
    admin's real current cohort, not a purely hypothetical rate.

    Returns `{"projected_churn_rate_pct": float, "upcoming_expiring": int,
    "projected_lapses": int, "trend_direction": str, "months_used": int}`
    or `None` if fewer than MIN_MONTHS_FOR_FORECAST of the window's months
    had any membership expiring at all."""

    memberships = get_memberships_for_admin(admin_id)
    months = last_n_months(FORECAST_WINDOW_MONTHS)

    joining_dates_by_student = defaultdict(list)
    for m in memberships:
        if m["joining_date"]:
            joining_dates_by_student[m["student_id"]].append(m["joining_date"])

    rates = []
    for month in months:
        year, mon = (int(part) for part in month.split("-"))
        month_start = date(year, mon, 1).isoformat()
        month_end = date(year, mon, calendar.monthrange(year, mon)[1]).isoformat()

        expiring = [
            m for m in memberships
            if m["end_date"] and month_start <= m["end_date"] <= month_end
        ]
        if not expiring:
            continue

        lapsed = sum(
            1 for m in expiring
            if not any(jd > m["end_date"] for jd in joining_dates_by_student[m["student_id"]])
        )
        rates.append(lapsed / len(expiring))

    if len(rates) < MIN_MONTHS_FOR_FORECAST:
        return None

    projected_rate = max(0.0, min(1.0, _linear_forecast(rates)))
    upcoming_expiring = get_upcoming_expiries(admin_id, days=30)

    return {
        "projected_churn_rate_pct": round(projected_rate * 100, 1),
        "upcoming_expiring": upcoming_expiring,
        "projected_lapses": round(projected_rate * upcoming_expiring),
        "trend_direction": _trend_direction(rates),
        "months_used": len(rates),
    }
