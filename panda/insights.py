"""Read-only data aggregation for Panda's insights and chat replies.

Every function here is a thin, honest wrapper around data this app already
computes elsewhere - deliberately reused rather than re-queried, so a
number Panda shows always agrees with the page that owns it:

- Revenue trend reuses `database/bi_queries.py`'s `get_revenue_growth()`,
  the same figure Business Intelligence's health score is built from.
- Expiring memberships reuses `routes/notification.py`'s
  `get_notification_summary()`, the same bucketing the navbar bell uses.
- Shift utilization reuses `database/bi_queries.py`'s
  `get_occupancy_summary()`, the same figure Occupancy Analytics shows.
- Admissions trend reuses `database/bi_queries.py`'s
  `get_monthly_new_memberships()`, the same monthly counts Dashboard's
  admissions-related figures are built from.
- Purpose performance reuses `database/bi_queries.py`'s
  `get_purpose_breakdown()`, the same per-purpose counts/revenue Purpose
  Analytics shows - there is no "batch"/"course" concept anywhere in this
  schema, so this is the closest real data to that kind of question
  (panda/intents.py's reply says so explicitly).

`get_top_risk_students()` (added for Part 2, "Analyze") is the one function
here that isn't a pure wrapper - `database/ai_center_queries.py`'s
`compute_student_risk_batch()` scores the admin's own roster in one batched
pass to build a top-N view (originally a per-student loop over
`compute_student_risk()`; switched 2026-08-24 after that loop measured 30+
seconds for a 17-student roster - TD-60). It reuses that function's scoring
verbatim (no new risk logic, same underlying `_score_student_risk()`
either way) rather than duplicating it, matching this module's existing
reuse convention.

`panda/notifications.py` turns these raw numbers into user-facing insight
cards; this module never formats a message and never decides a threshold -
keeping that split means a future forecasting model (panda/forecasting.py)
can slot in here as an additional data source without notifications.py
having to change how it decides what's worth surfacing.

`get_revenue_explanation()` (added for Part 3, "Explain") follows the same
reuse discipline but composes three existing signals instead of wrapping
one: this month vs last month's new-admissions count
(`get_monthly_new_memberships()`, already wrapped above as
`get_admissions_trend()`), unrenewed expired memberships (the same
`get_notification_summary()` counts `get_expiring_memberships()` already
wraps), and fees billed but not yet collected
(`database/cashbook_queries.get_pending_fees()`). No new SQL/aggregation is
introduced - there is no monthly income-category breakdown anywhere in this
codebase (`get_income_category_totals()` is all-time only), so this can say
*that* admissions/renewals/collection moved, never *which* Cashbook income
category did (see TD-61 in docs/11_FUTURE_WORK.md).

`get_recommended_actions()` (added for Part 4, "Recommend") is a pure
wrapper around `database/bi_queries.py`'s `get_action_items()` - the same
ranked action list already shown on Business Intelligence's Overview page
(expiring memberships, pending fees, expense ratio, retention, revenue
growth). No new recommendation logic exists here; Panda surfaces the
identical real signal->action pairs that page already computes, including
its "No urgent issues detected" filler when nothing is currently flagged.

`get_revenue_forecast()`/`get_seat_demand_forecast()`/`get_churn_forecast()`
(added for Part 5, "Forecast") are pure wrappers around
`panda/forecasting.py`'s three real functions - simple linear trend
extrapolation over this admin's own historical data, not ML/LLM (see that
module's docstring, ADR-51). Each returns `None`, passed straight through
untouched, when there isn't enough real historical variation to forecast
honestly - `panda/intents.py` is responsible for turning that into an
honest reply, the same "never fabricate an answer this module didn't
actually return" boundary every other function here already holds.

`get_retention_summary()`/`get_cash_collection_summary()`/
`get_expense_breakdown()`/`get_expense_health()` (added 2026-08-20, ADR-52)
extend Part 1's keyword coverage laterally to two new topics - student
retention and cash management - not a sixth part of the Ask->Analyze->
Explain->Recommend->Forecast progression, which stays closed (PF-8). Each
is a pure wrapper, same reuse discipline as every function above:
`get_retention_summary()` wraps `database/bi_queries.py`'s own
`get_membership_retention()` (already computed there for the Action
Center/health score, just never exposed to Panda directly before now);
`get_cash_collection_summary()` wraps `get_revenue_collection_summary()`;
`get_expense_breakdown()` wraps `get_top_expense_categories()` (all-time,
not monthly - see TD-61 for why no monthly breakdown exists);
`get_expense_health()` wraps `classify_expense_health()`. No new query was
written for either topic. `get_risk_scoring_coverage()` is the one
non-wrapper addition - it re-reads this admin's roster size so
`panda/intents.py`'s retention reply can honestly say "(scored the first
100 of N students)" when `get_top_risk_students()`'s existing
`MAX_STUDENTS_SCORED_FOR_CHAT` cap (TD-60) is actually hit, rather than
silently inheriting that limitation unremarked. Deliberately out of scope
for this addition: an aggregate "why" tally across every at-risk student
(e.g. "60% of at-risk students are at risk because of late payment") -
`get_top_risk_students()`'s `reasons` are strictly per-student, and
building a cross-student aggregate would be new analysis logic, not reuse
(the same line ADR-49/TD-61 already drew for revenue's category
breakdown) - see ADR-52.

`get_cash_balance()`/`get_profit_loss_summary()` (added 2026-08-25, closing
the pre-pilot audit's top-ranked finding, ADR-55) are the same "pure
wrapper" reuse every function above already follows -
`database.cashbook_queries.get_cash_balance()` (Cash-payment-method income
minus Cash-payment-method expense, all-time) and `.get_total_income()`/
`.get_total_expense()`/`.get_monthly_profit()` already existed, already
correct, and were already used elsewhere in the app (Cashbook's own
reports) - simply never reachable from Panda before now. No new calculation
was written for either. The two are deliberately kept as separate
functions/intents, never merged into one reply: cash balance is
Cash-payment-method transactions only ("what's physically in the drawer"),
profit/loss spans every payment method - a real library can have a
positive cash balance and a negative overall profit at the same time, and
conflating them in one reply would misinform an owner relying on this
number to make a decision. See ADR-55.
"""

from database.ai_center_queries import compute_student_risk_batch
from database.bi_queries import (
    classify_expense_health,
    get_action_items,
    get_membership_retention,
    get_monthly_new_memberships,
    get_occupancy_summary,
    get_purpose_breakdown,
    get_revenue_collection_summary,
    get_revenue_growth,
    get_top_expense_categories,
    last_n_months,
)
from database.cashbook_queries import (
    get_cash_balance as _get_cash_balance,
    get_monthly_profit,
    get_pending_fees,
    get_total_expense,
    get_total_income,
)
from database.membership_queries import get_admin_students
from panda import forecasting
from routes.notification import get_notification_summary

# compute_student_risk() is 3 Supabase round trips per student (see its own
# docstring in database/ai_center_queries.py) - capping how many of this
# admin's students get scored for a single chat reply keeps a library with
# a large roster from turning one chat message into hundreds of sequential
# network calls (the same category of risk TD-44 already documents for
# receipt numbering). See TD-60 in docs/11_FUTURE_WORK.md.
MAX_STUDENTS_SCORED_FOR_CHAT = 100
TOP_RISK_STUDENTS_LIMIT = 3


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


def get_admissions_trend(admin_id):
    """New memberships per month, keyed by joining month - see
    `database/bi_queries.py.get_monthly_new_memberships()`."""

    return get_monthly_new_memberships(admin_id)


def get_student_count(admin_id):
    """This admin's total roster size (added 2026-08-24 to answer "how many
    students do I have" honestly - a total headcount, not the same fact as
    get_admissions_trend()'s per-month new-admission counts). Reuses
    `database/membership_queries.get_admin_students()`, already the source
    of truth for this admin's roster everywhere else in this module (e.g.
    get_top_risk_students(), get_risk_scoring_coverage()) - no new query."""

    return len(get_admin_students(admin_id))


def get_purpose_performance(admin_id):
    """Per-purpose student count and revenue, sorted by student count desc -
    see `database/bi_queries.py.get_purpose_breakdown()`. The first entry is
    this admin's most-popular purpose category right now."""

    return get_purpose_breakdown(admin_id)


def get_top_risk_students(admin_id, limit=TOP_RISK_STUDENTS_LIMIT):
    """This admin's top `limit` High-risk students (AI Center's own
    High/Medium/Low buckets, ADR-39/40), scored via
    `database/ai_center_queries.py.compute_student_risk_batch()` over up to
    `MAX_STUDENTS_SCORED_FOR_CHAT` of their students - a constant number of
    Supabase round trips regardless of how many students that is, not one
    per student (see that function's docstring for why this changed
    2026-08-24: the old per-student loop measured 30+ seconds for a
    17-student roster, TD-60). The cap itself is unchanged - still applied
    here, before scoring, exactly as before. Returns [] if nobody is
    currently High risk - never manufactures a result, same "a check that
    finds nothing contributes nothing" rule panda/notifications.py already
    follows."""

    students = get_admin_students(admin_id)[:MAX_STUDENTS_SCORED_FOR_CHAT]

    scored_by_student = compute_student_risk_batch(admin_id, students=students)
    scored = [result for result in scored_by_student.values() if result["level"] == "High"]

    scored.sort(key=lambda r: r["score"])
    return scored[:limit]


def get_revenue_explanation(admin_id):
    """Honest, ranked contributing factors behind this month's revenue
    change - each is a literal fact about what's different in this admin's
    own data this month, not an asserted single cause. Matches
    `database/bi_queries.py.get_action_items()`'s "independent check
    contributes a fact, or nothing" shape, and only surfaces a factor when
    it points the same direction as the actual revenue change (e.g. fewer
    admissions is only reported as a factor when revenue is actually down)
    - a signal that doesn't line up with the direction being explained
    would be misleading, not illuminating.

    Returns {"trend": <get_revenue_trend() dict>, "factors": [str, ...]} -
    `factors` is [] when growth is flat or no signal here lines up with the
    direction, same "a check that finds nothing contributes nothing" rule
    get_top_risk_students() and panda/notifications.py already follow."""

    trend = get_revenue_trend(admin_id)
    growth = trend["growth_pct"]

    # Same calendar current/previous month get_revenue_growth() itself uses
    # (last_n_months(2)) - not "the last two months with any admissions at
    # all", which would silently mislabel an older month as "this month"
    # whenever this admin had zero admissions in the actual current month.
    admissions = get_admissions_trend(admin_id)
    previous_month, current_month = last_n_months(2)
    current_admissions = admissions.get(current_month, 0)
    previous_admissions = admissions.get(previous_month, 0)

    expiring = get_expiring_memberships(admin_id)
    pending = get_pending_fees(admin_id)

    factors = []

    if growth < 0 and current_admissions < previous_admissions:
        factors.append(
            f"New admissions dropped from {previous_admissions} last month to "
            f"{current_admissions} this month."
        )
    elif growth > 0 and current_admissions > previous_admissions:
        factors.append(
            f"New admissions grew from {previous_admissions} last month to "
            f"{current_admissions} this month."
        )

    if growth < 0 and expiring["expired"] > 0:
        count = expiring["expired"]
        factors.append(
            f"{count} membership{'s' if count != 1 else ''} expired without a "
            "renewal booked yet, cutting into recurring income."
        )

    if growth < 0 and pending > 0:
        factors.append(
            f"₹{pending:,.0f} in billed fees is still pending collection, so it "
            "isn't counted in this month's income yet."
        )

    return {"trend": trend, "factors": factors}


def get_recommended_actions(admin_id):
    """This admin's real, ranked action items - see
    `database/bi_queries.py.get_action_items()` for the underlying signals
    (expiring memberships, pending fees, expense ratio, retention, revenue
    growth). Always returns at least one item - `get_action_items()` itself
    appends an honest "No urgent issues detected" entry when every other
    check comes back clean, so this never returns an empty list."""

    return get_action_items(admin_id)


def get_revenue_forecast(admin_id):
    """Next month's projected Cashbook income, or `None` if this admin
    doesn't have enough real monthly history yet - see
    `panda/forecasting.py.forecast_revenue()`."""

    return forecasting.forecast_revenue(admin_id)


def get_seat_demand_forecast(admin_id):
    """Next month's projected overall occupancy %, or `None` if this admin
    doesn't have enough real monthly history yet - see
    `panda/forecasting.py.forecast_seat_demand()`."""

    return forecasting.forecast_seat_demand(admin_id)


def get_churn_forecast(admin_id):
    """Projected membership lapse count/rate among memberships expiring in
    the next 30 days, or `None` if this admin doesn't have enough real
    monthly lapse history yet - see
    `panda/forecasting.py.forecast_membership_churn()`."""

    return forecasting.forecast_membership_churn(admin_id)


def get_retention_summary(admin_id):
    """Total vs currently-active memberships - a real retention ratio, see
    `database/bi_queries.py.get_membership_retention()` (already computed
    there for the Action Center/health score, not previously exposed to
    Panda directly)."""

    return get_membership_retention(admin_id)


def get_risk_scoring_coverage(admin_id):
    """Whether `get_top_risk_students()` scored this admin's entire roster
    or hit `MAX_STUDENTS_SCORED_FOR_CHAT` (TD-60) - lets a reply say so
    honestly rather than silently looking like "no risk" when some
    students were never actually checked. Does not change
    `get_top_risk_students()`'s own cap or behavior."""

    total = len(get_admin_students(admin_id))
    return {"total": total, "capped": total > MAX_STUDENTS_SCORED_FOR_CHAT}


def get_cash_collection_summary(admin_id):
    """Expected (billed) vs collected vs pending fee revenue, and the
    collection % between them - see
    `database/bi_queries.py.get_revenue_collection_summary()`."""

    return get_revenue_collection_summary(admin_id)


def get_expense_breakdown(admin_id):
    """This admin's real expense categories, ranked by amount - see
    `database/bi_queries.py.get_top_expense_categories()`. All-time, not
    monthly - no function anywhere in this codebase computes a monthly
    expense-category breakdown (the same gap TD-61 documents for income)."""

    return get_top_expense_categories(admin_id)


def get_expense_health(admin_id):
    """This month's expense-to-income ratio classification - see
    `database/bi_queries.py.classify_expense_health()`."""

    return classify_expense_health(admin_id)


def get_cash_balance(admin_id):
    """Cash on hand right now - Cash-payment-method income minus
    Cash-payment-method expense, all-time (added 2026-08-25, ADR-55). Pure
    wrapper around `database/cashbook_queries.py.get_cash_balance()` - no
    new calculation. Deliberately distinct from `get_profit_loss_summary()`
    below - see that function's docstring and this module's own docstring
    for why the two must never be presented as the same number."""

    return _get_cash_balance(admin_id)


def get_profit_loss_summary(admin_id):
    """This admin's real profit/loss picture - all-time net (income minus
    expense, every payment method combined) plus the same figure broken out
    per month (added 2026-08-25, ADR-55). Composes three existing
    `database/cashbook_queries.py` functions verbatim -
    `get_total_income()`, `get_total_expense()`, `get_monthly_profit()` -
    `net_profit` is the only value computed here, and it's a one-line
    subtraction of two numbers those functions already returned, not a new
    aggregation. `current_month` (this run's actual current month, 'YYYY-MM')
    lets a caller label that entry as still in progress rather than a
    finished month's total. Deliberately distinct from `get_cash_balance()`
    above: this spans every payment method, not just Cash - a business can
    be cash-positive and still running at a loss overall (or vice versa),
    and a reply combining both numbers must say so explicitly rather than
    implying they're the same measurement."""

    total_income = get_total_income(admin_id)
    total_expense = get_total_expense(admin_id)

    return {
        "total_income": total_income,
        "total_expense": total_expense,
        "net_profit": total_income - total_expense,
        "monthly": get_monthly_profit(admin_id),
        "current_month": last_n_months(1)[0],
    }
