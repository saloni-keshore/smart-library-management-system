"""
Data access for the Business Intelligence module.

This module does not duplicate Cashbook's SQL. It imports the existing,
admin-isolated aggregate functions from cashbook_queries (monthly income,
monthly expense, category totals, pending fees, recent transactions) and
adds only the analysis that doesn't exist anywhere yet: growth math, health
classification, the composite health score, and membership-side counts.

Every new query here still follows the same admin_id-scoped, dict/list
returning convention used across cashbook_queries.py and the rest of the
database layer.
"""

import calendar
from datetime import date, timedelta

from database.cashbook_queries import (
    get_monthly_income,
    get_monthly_expense,
    get_pending_fees,
    get_total_fee_revenue,
    get_income_category_totals,
    get_expense_category_totals,
    get_recent_transactions,
)
from database.membership_queries import (
    get_memberships_for_admin, get_admin_students, get_effective_status,
)
from database.payment_queries import get_payments_for_admin
from database.settings_queries import get_library_settings


# ---------------------------------------------------------------------------
# Shared month helpers
# ---------------------------------------------------------------------------

def last_n_months(n=6):
    """Last n month keys ('YYYY-MM'), oldest first, ending at the current month."""

    today = date.today()
    year, month = today.year, today.month

    months = []
    for i in range(n - 1, -1, -1):
        m = month - i
        y = year
        while m <= 0:
            m += 12
            y -= 1
        months.append(f"{y:04d}-{m:02d}")

    return months


# ---------------------------------------------------------------------------
# Membership-side counts (no equivalent exists yet in any queries module)
# ---------------------------------------------------------------------------

def get_monthly_new_memberships(admin_id):
    """New memberships per month, keyed by joining month. Reads Supabase
    `students`/`memberships` (ADR-23) via
    database.membership_queries.get_memberships_for_admin() instead of the
    SQLite mirror."""

    memberships = get_memberships_for_admin(admin_id)

    totals = {}
    for m in memberships:
        if not m["joining_date"]:
            continue
        month = m["joining_date"][:7]
        totals[month] = totals.get(month, 0) + 1

    return dict(sorted(totals.items()))


def get_membership_retention(admin_id):
    """Total vs currently-active memberships, used as a retention signal.
    Reads Supabase `students`/`memberships` (ADR-23)."""

    memberships = get_memberships_for_admin(admin_id)
    today = date.today().isoformat()

    active = sum(
        1 for m in memberships
        if m["membership_status"] == "Active" and m["end_date"] and m["end_date"] >= today
    )

    return {"total": len(memberships), "active": active}


def get_upcoming_expiries(admin_id, days=7):
    """Count of active memberships expiring within the next `days` days.
    Reads Supabase `students`/`memberships` (ADR-23)."""

    memberships = get_memberships_for_admin(admin_id)
    today = date.today().isoformat()
    cutoff = (date.today() + timedelta(days=days)).isoformat()

    return sum(
        1 for m in memberships
        if m["membership_status"] == "Active"
        and m["end_date"] and today <= m["end_date"] <= cutoff
    )


# ---------------------------------------------------------------------------
# Revenue growth + health classification
# ---------------------------------------------------------------------------

def get_revenue_growth(admin_id):
    """Current vs previous month revenue and the growth % between them."""

    income = get_monthly_income(admin_id)
    previous_month, current_month = last_n_months(2)

    current = income.get(current_month, 0)
    previous = income.get(previous_month, 0)

    if previous > 0:
        growth_pct = round((current - previous) / previous * 100, 1)
    elif current > 0:
        growth_pct = 100.0
    else:
        growth_pct = 0.0

    return {
        "current_month": current,
        "previous_month": previous,
        "growth_pct": growth_pct,
    }


def classify_revenue_health(growth_pct):
    """Healthy: growing 5%+. Warning: roughly flat. Critical: shrinking 5%+."""

    if growth_pct >= 5:
        return "Healthy"
    if growth_pct <= -5:
        return "Critical"
    return "Warning"


def classify_expense_health(admin_id):
    """Classifies this month's expense-to-income ratio.

    Healthy: spending under half of revenue. Warning: 50-75%.
    Critical: over 75%, or any expense with zero revenue to cover it.
    """

    income = get_monthly_income(admin_id)
    expense = get_monthly_expense(admin_id)
    current_month = last_n_months(1)[0]

    current_income = income.get(current_month, 0)
    current_expense = expense.get(current_month, 0)

    if current_income > 0:
        ratio = current_expense / current_income
    else:
        ratio = 1.0 if current_expense > 0 else 0.0

    if ratio <= 0.5:
        status = "Healthy"
    elif ratio <= 0.75:
        status = "Warning"
    else:
        status = "Critical"

    return {
        "ratio_pct": round(ratio * 100, 1),
        "status": status,
        "current_income": current_income,
        "current_expense": current_expense,
    }


# ---------------------------------------------------------------------------
# Business Health Score
#
# Weighted blend of four signals, each normalized to 0-1:
#   30% revenue growth      (-20% growth -> 0, +20% growth -> 1)
#   30% expense discipline  (0% of revenue spent -> 1, 100%+ -> 0)
#   20% fee collection      (share of billed fee revenue not left pending)
#   20% membership renewal  (active memberships / total memberships)
# A library with no data yet gets neutral 0.5 on components it has no
# signal for, rather than being punished with a 0.
# ---------------------------------------------------------------------------

def get_business_health_score(admin_id):

    growth = get_revenue_growth(admin_id)
    expense = classify_expense_health(admin_id)
    retention = get_membership_retention(admin_id)
    pending = get_pending_fees(admin_id)
    total_fee_revenue = get_total_fee_revenue(admin_id)

    growth_component = max(0.0, min(1.0, (growth["growth_pct"] + 20) / 40))
    expense_component = max(0.0, min(1.0, 1 - (expense["ratio_pct"] / 100)))

    # Billable = fees actually collected + fees still pending. Deliberately
    # uses fee revenue (Payments/Memberships), not get_total_income()'s
    # all-Cashbook total - non-fee income (donations, library fines, book
    # sales) isn't billed against a membership, so blending it in would
    # dilute the pending share and overstate collection health.
    billable = pending + total_fee_revenue
    collection_component = (
        max(0.0, min(1.0, 1 - pending / billable)) if billable > 0 else 0.5
    )

    renewal_component = (
        retention["active"] / retention["total"] if retention["total"] > 0 else 0.5
    )

    score = round(100 * (
        0.30 * growth_component +
        0.30 * expense_component +
        0.20 * collection_component +
        0.20 * renewal_component
    ))
    score = max(0, min(100, score))

    if score >= 80:
        status = "Excellent"
    elif score >= 60:
        status = "Good"
    elif score >= 40:
        status = "Average"
    else:
        status = "Needs Attention"

    return {"score": score, "status": status}


# ---------------------------------------------------------------------------
# Top revenue sources / expense categories
# ---------------------------------------------------------------------------

def _rank_categories(totals, limit=5):

    total_sum = sum(totals.values())
    ranked = []

    for i, (category, amount) in enumerate(totals.items(), start=1):
        if i > limit:
            break
        ranked.append({
            "rank": i,
            "category": category,
            "amount": amount,
            "percentage": round(amount / total_sum * 100, 1) if total_sum else 0,
        })

    return ranked


def get_top_revenue_sources(admin_id, limit=5):
    return _rank_categories(get_income_category_totals(admin_id), limit)


def get_top_expense_categories(admin_id, limit=5):
    return _rank_categories(get_expense_category_totals(admin_id), limit)


# ---------------------------------------------------------------------------
# Action Center
# ---------------------------------------------------------------------------

def get_action_items(admin_id):
    """Actionable recommendations derived from signals already computed above."""

    items = []

    growth = get_revenue_growth(admin_id)
    expense = classify_expense_health(admin_id)
    retention = get_membership_retention(admin_id)
    pending = get_pending_fees(admin_id)
    expiring_soon = get_upcoming_expiries(admin_id, days=7)

    if expiring_soon > 0:
        items.append({
            "type": "warning",
            "icon": "bi-calendar-x",
            "title": f"{expiring_soon} membership{'s' if expiring_soon != 1 else ''} expiring within 7 days",
            "description": "Reach out now to renew before they lapse.",
        })

    if pending > 0:
        items.append({
            "type": "warning",
            "icon": "bi-cash-coin",
            "title": f"₹{pending:,.0f} in pending fees",
            "description": "Follow up with members carrying outstanding balances.",
        })

    if expense["status"] in ("Warning", "Critical"):
        items.append({
            "type": "danger" if expense["status"] == "Critical" else "warning",
            "icon": "bi-graph-down-arrow",
            "title": f"Expenses at {expense['ratio_pct']:.0f}% of revenue",
            "description": "Review high-spend categories and cut avoidable costs.",
        })

    if retention["total"] > 0:
        renewal_rate = retention["active"] / retention["total"] * 100
        if renewal_rate < 60:
            items.append({
                "type": "danger",
                "icon": "bi-person-dash",
                "title": f"Only {renewal_rate:.0f}% of memberships are active",
                "description": "Retention is low - consider a renewal campaign.",
            })

    if growth["growth_pct"] <= -5:
        items.append({
            "type": "danger",
            "icon": "bi-arrow-down-right",
            "title": f"Revenue dropped {abs(growth['growth_pct']):.1f}% this month",
            "description": "Investigate the cause before it compounds next month.",
        })
    elif growth["growth_pct"] >= 5:
        items.append({
            "type": "success",
            "icon": "bi-arrow-up-right",
            "title": f"Revenue grew {growth['growth_pct']:.1f}% this month",
            "description": "Momentum is positive - current strategies are working.",
        })

    if not items:
        items.append({
            "type": "success",
            "icon": "bi-check-circle",
            "title": "No urgent issues detected",
            "description": "The library's finances and memberships look stable.",
        })

    return items


# ---------------------------------------------------------------------------
# Business Timeline
# ---------------------------------------------------------------------------

def get_business_timeline(admin_id, limit=8):
    """Recent financial activity, reusing Cashbook's own recency query."""

    rows = get_recent_transactions(admin_id, limit=limit)

    return [
        {
            "type": row["type"],
            "category": row["category"],
            "person": row["person"],
            "amount": row["amount"],
            "entry_date": row["entry_date"],
            "description": row["description"],
        }
        for row in rows
    ]


# ---------------------------------------------------------------------------
# Purpose Analytics (students + revenue grouped by each student's `purpose`)
# ---------------------------------------------------------------------------

NO_PURPOSE_LABEL = "Not Specified"


def _purpose_of(student):
    purpose = (student.get("purpose") or "").strip()
    return purpose or NO_PURPOSE_LABEL


def get_purpose_breakdown(admin_id):
    """Per-purpose student count and total revenue, sorted by student count
    (desc, ties broken by revenue).

    `purpose` lives on `students` (free text, e.g. "UPSC"/"Study"), revenue
    lives on `payments` - Supabase's client has no server-side JOIN, so this
    merges the two in Python via student_id, the same shape
    get_memberships_for_admin()/get_payments_for_admin() already use for
    their own Students joins. Reuses those two existing, admin-isolated
    queries directly rather than re-querying Supabase, and every Purpose
    Analytics consumer (KPIs, all four charts, the summary table) is built
    from this single breakdown so the underlying reads only happen once per
    request.

    Counts every student regardless of `students.status` (Active/Inactive),
    matching the Students list page - not Dashboard's Active-only total.
    """

    students = get_admin_students(admin_id)
    payments = get_payments_for_admin(admin_id)

    purpose_by_student = {s["student_id"]: _purpose_of(s) for s in students}

    students_count = {}
    for s in students:
        purpose = purpose_by_student[s["student_id"]]
        students_count[purpose] = students_count.get(purpose, 0) + 1

    revenue_by_purpose = {}
    for p in payments:
        purpose = purpose_by_student.get(p["student_id"], NO_PURPOSE_LABEL)
        revenue_by_purpose[purpose] = revenue_by_purpose.get(purpose, 0) + (p["amount_paid"] or 0)

    purposes = set(students_count) | set(revenue_by_purpose)
    rows = [
        {
            "purpose": purpose,
            "students": students_count.get(purpose, 0),
            "revenue": revenue_by_purpose.get(purpose, 0),
        }
        for purpose in purposes
    ]
    rows.sort(key=lambda r: (r["students"], r["revenue"]), reverse=True)

    return rows


# ---------------------------------------------------------------------------
# Revenue Analytics (student/membership fee revenue - Payments-scoped, the
# same narrower-than-Cashbook definition get_total_fee_revenue() and
# get_purpose_breakdown() already use - see ADR-11 in docs/DECISIONS.md)
# ---------------------------------------------------------------------------

def get_revenue_time_windows(admin_id):
    """Fee revenue collected in total, and narrowed to today / this
    calendar week (Monday-based) / this calendar month / this calendar
    year - all read off `payments.payment_date`, the same field
    get_today_fee_collection() already keys off."""

    payments = get_payments_for_admin(admin_id)
    today = date.today()
    week_start = (today - timedelta(days=today.weekday())).isoformat()
    month_prefix = today.strftime("%Y-%m")
    year_prefix = today.strftime("%Y")
    today_iso = today.isoformat()

    windows = {"total": 0, "today": 0, "week": 0, "month": 0, "year": 0}

    for p in payments:
        amount = p["amount_paid"] or 0
        windows["total"] += amount

        payment_date = p["payment_date"]
        if not payment_date:
            continue
        if payment_date == today_iso:
            windows["today"] += amount
        if payment_date >= week_start:
            windows["week"] += amount
        if payment_date.startswith(month_prefix):
            windows["month"] += amount
        if payment_date.startswith(year_prefix):
            windows["year"] += amount

    return windows


def get_monthly_fee_revenue(admin_id):
    """Fee revenue per calendar month (`payments.payment_date`), for the
    Revenue Trend / Monthly Revenue charts - deliberately Payments-scoped,
    not get_monthly_income()'s all-Cashbook-income total (ADR-11)."""

    payments = get_payments_for_admin(admin_id)

    totals = {}
    for p in payments:
        if not p["payment_date"]:
            continue
        month = p["payment_date"][:7]
        totals[month] = totals.get(month, 0) + (p["amount_paid"] or 0)

    return dict(sorted(totals.items()))


def get_revenue_by_plan(admin_id):
    """Fee revenue grouped by each payment's membership plan
    (`memberships.plan_name`), merged in Python the same way
    get_purpose_breakdown() merges purpose - Supabase has no server-side
    JOIN in the client this codebase uses."""

    memberships = get_memberships_for_admin(admin_id)
    payments = get_payments_for_admin(admin_id)
    plan_by_membership = {m["membership_id"]: m["plan_name"] for m in memberships}

    totals = {}
    for p in payments:
        plan = plan_by_membership.get(p["membership_id"], "Unknown")
        totals[plan] = totals.get(plan, 0) + (p["amount_paid"] or 0)

    return dict(sorted(totals.items(), key=lambda kv: kv[1], reverse=True))


def get_revenue_by_payment_mode(admin_id):
    """Fee revenue grouped by `payments.payment_mode` (already normalized
    UPPERCASE by utils.normalization.normalize_category at write time)."""

    payments = get_payments_for_admin(admin_id)

    totals = {}
    for p in payments:
        mode = p.get("payment_mode") or "UNKNOWN"
        totals[mode] = totals.get(mode, 0) + (p["amount_paid"] or 0)

    return dict(sorted(totals.items(), key=lambda kv: kv[1], reverse=True))


def get_payment_mode_usage_counts(admin_id):
    """Transaction *count* per payment mode - distinct from
    get_revenue_by_payment_mode()'s amount total, used for the "most-used
    payment mode" insight (most transactions, not necessarily most ₹)."""

    payments = get_payments_for_admin(admin_id)

    counts = {}
    for p in payments:
        mode = p.get("payment_mode") or "UNKNOWN"
        counts[mode] = counts.get(mode, 0) + 1

    return dict(sorted(counts.items(), key=lambda kv: kv[1], reverse=True))


def get_new_vs_renewal_revenue(admin_id):
    """Fee revenue split between each student's first membership ("New
    Admission") and every subsequent one ("Renewal").

    Determined from `memberships.membership_id` ordering per student, not
    the best-effort Cashbook `source` label (routes/membership.py's
    create()/renew() tag their automatic Cashbook entries "Admission"/
    "Renewal", but that write can silently fail - see
    cashbook_queries.insert_income_entry()'s docstring) - so this split
    stays correct even when a Cashbook mirror write was dropped.
    """

    memberships = get_memberships_for_admin(admin_id)
    payments = get_payments_for_admin(admin_id)

    first_membership_by_student = {}
    for m in memberships:
        sid = m["student_id"]
        mid = m["membership_id"]
        if sid not in first_membership_by_student or mid < first_membership_by_student[sid]:
            first_membership_by_student[sid] = mid

    result = {"new_admissions": 0, "renewal": 0}
    for p in payments:
        amount = p["amount_paid"] or 0
        if first_membership_by_student.get(p["student_id"]) == p["membership_id"]:
            result["new_admissions"] += amount
        else:
            result["renewal"] += amount

    return result


def get_revenue_collection_summary(admin_id):
    """Expected (billed) vs Collected vs Pending fee revenue, and the
    Collection % between them - summed straight off `memberships.total_fee`
    /`paid_amount`/`pending_amount`, which routes/membership.py's create()/
    renew() and routes/payment.py's collect() keep in the invariant
    total_fee == paid_amount + pending_amount for every row.
    """

    memberships = get_memberships_for_admin(admin_id)

    expected = sum(m["total_fee"] or 0 for m in memberships)
    collected = sum(m["paid_amount"] or 0 for m in memberships)
    pending = sum(m["pending_amount"] or 0 for m in memberships)
    collection_pct = round(collected / expected * 100, 1) if expected > 0 else 0.0

    return {
        "expected": expected,
        "collected": collected,
        "pending": pending,
        "collection_pct": collection_pct,
    }


def get_avg_revenue_per_student(admin_id):
    """Total fee revenue / total student count - same definition
    _purpose_analytics_data() computes inline for Purpose Analytics,
    exposed here so Revenue Analytics doesn't recompute it differently."""

    students = get_admin_students(admin_id)
    total_revenue = get_total_fee_revenue(admin_id)
    return round(total_revenue / len(students)) if students else 0


# ---------------------------------------------------------------------------
# Occupancy Analytics (Business Intelligence Phase 3, ADR-38)
#
# There is no seat/attendance table anywhere in the schema - "occupancy" is
# reconstructed from two real, already-existing signals instead of a
# hardcoded guess: `students.shift` (which shift a student is enrolled in)
# and each admin's own configured seat capacity per shift
# (`library_settings.morning_capacity`/`afternoon_capacity`/
# `evening_capacity`, added by this phase - Settings > Library Profile,
# see docs/DECISIONS.md ADR-38). "Occupied" means a student with a
# currently effectively-active membership (get_active_memberships()) - a
# student whose membership has expired no longer holds a seat, unlike
# Purpose Analytics, which deliberately counts every student ever admitted.
# ---------------------------------------------------------------------------

# "Night" became a real 4th canonical shift with ADR-65's time-window slots
# (a genuinely sellable night shift, with its own library_settings.night_
# capacity). "Full Day" is a bucket a membership can occupy but is NOT a
# capacity-bearing shift - a Full Day member sits in a seat across every
# window - so it's tallied like OTHER_SHIFT_LABEL: counted in the totals,
# never against a single shift's utilization %.
CANONICAL_SHIFTS = ["Morning", "Afternoon", "Evening", "Night"]
OTHER_SHIFT_LABEL = "Other"
FULL_DAY_LABEL = "Full Day"
DEFAULT_SHIFT_CAPACITY = 50

_SHIFT_ALIASES = {
    "MORNING": "Morning", "AFTERNOON": "Afternoon",
    "EVENING": "Evening", "NIGHT": "Night",
}

# Buckets a membership's ADR-65 time_bucket snapshot may name directly.
_OCCUPANCY_BUCKETS = set(CANONICAL_SHIFTS) | {FULL_DAY_LABEL}


def _canonical_shift(value):
    """Maps a student's normalize_category()'d shift ("MORNING", ...) to
    its display label. Anything else (blank, or a free-text value like
    "FULL DAY" that predates students/edit.html's dropdown) is bucketed
    under OTHER_SHIFT_LABEL rather than mis-tallied into a canonical shift
    or crashing."""

    return _SHIFT_ALIASES.get((value or "").strip().upper(), OTHER_SHIFT_LABEL)


def _membership_bucket(m):
    """The shift a membership occupies for Occupancy Analytics: its ADR-65
    `time_bucket` snapshot when the membership was sold on a shift slot,
    otherwise the student's free-text `shift` bucketed the old way. A
    snapshot value that isn't a recognised bucket falls back to "Other"."""

    bucket = (m.get("time_bucket") or "").strip()
    if bucket in _OCCUPANCY_BUCKETS:
        return bucket
    if bucket:
        return OTHER_SHIFT_LABEL
    return _canonical_shift(m.get("shift"))


def get_shift_capacities(admin_id):
    """This admin's per-shift seat capacity (Settings > Library Profile).
    Falls back to DEFAULT_SHIFT_CAPACITY per shift when no profile has
    been saved yet, or when the live database doesn't have the
    *_capacity columns yet (database/supabase_migration.sql documents the
    ALTER TABLE an existing Supabase project needs) - get_library_settings()
    simply won't return those keys in that case, and .get() covers both."""

    settings = get_library_settings(admin_id) or {}
    return {
        "Morning": settings.get("morning_capacity") or DEFAULT_SHIFT_CAPACITY,
        "Afternoon": settings.get("afternoon_capacity") or DEFAULT_SHIFT_CAPACITY,
        "Evening": settings.get("evening_capacity") or DEFAULT_SHIFT_CAPACITY,
        "Night": settings.get("night_capacity") or DEFAULT_SHIFT_CAPACITY,
    }


def get_active_memberships(admin_id):
    """This admin's currently effectively-active memberships, one per
    student (the latest membership_id, in the rare case a student somehow
    has more than one Active row at once) - the "occupied seat" population
    every occupancy query below is built from."""

    memberships = get_memberships_for_admin(admin_id)

    active_by_student = {}
    for m in memberships:
        if get_effective_status(m["membership_status"], m["end_date"]) != "Active":
            continue
        sid = m["student_id"]
        if sid not in active_by_student or m["membership_id"] > active_by_student[sid]["membership_id"]:
            active_by_student[sid] = m

    return list(active_by_student.values())


def get_shift_occupancy(admin_id):
    """Occupied-seat count per canonical shift (+ "Full Day" + "Other"),
    from the currently active-membership population."""

    occupied = {shift: 0 for shift in CANONICAL_SHIFTS}
    occupied[FULL_DAY_LABEL] = 0
    occupied[OTHER_SHIFT_LABEL] = 0

    for m in get_active_memberships(admin_id):
        occupied[_membership_bucket(m)] += 1

    return occupied


def get_occupancy_summary(admin_id):
    """Full per-shift + overall occupancy snapshot - the single source
    every Occupancy Analytics KPI/chart/table/insight is built from, so
    capacity/occupied are only fetched and combined once per request."""

    capacities = get_shift_capacities(admin_id)
    occupied = get_shift_occupancy(admin_id)

    shifts = []
    for name in CANONICAL_SHIFTS:
        capacity = capacities[name]
        occupied_count = occupied[name]
        shifts.append({
            "name": name,
            "capacity": capacity,
            "occupied": occupied_count,
            "available": max(capacity - occupied_count, 0),
            "utilization_pct": round(occupied_count * 100 / capacity, 1) if capacity else 0.0,
        })

    total_capacity = sum(capacities.values())
    total_occupied = sum(occupied.values())  # includes "Full Day" + "Other"

    return {
        "shifts": shifts,
        "fullday_occupied": occupied[FULL_DAY_LABEL],
        "other_occupied": occupied[OTHER_SHIFT_LABEL],
        "total_capacity": total_capacity,
        "total_occupied": total_occupied,
        "total_available": max(total_capacity - total_occupied, 0),
        "occupancy_pct": round(total_occupied * 100 / total_capacity, 1) if total_capacity else 0.0,
    }


def get_occupancy_by_purpose(admin_id):
    """Occupied-seat count per purpose, from the currently
    active-membership population - sorted descending."""

    totals = {}
    for m in get_active_memberships(admin_id):
        purpose = (m.get("purpose") or "").strip() or NO_PURPOSE_LABEL
        totals[purpose] = totals.get(purpose, 0) + 1

    return dict(sorted(totals.items(), key=lambda kv: kv[1], reverse=True))


def get_occupancy_by_plan(admin_id):
    """Occupied-seat count per membership plan, from the currently
    active-membership population - sorted descending."""

    totals = {}
    for m in get_active_memberships(admin_id):
        plan = m.get("plan_name") or "Unknown"
        totals[plan] = totals.get(plan, 0) + 1

    return dict(sorted(totals.items(), key=lambda kv: kv[1], reverse=True))


def get_purpose_shift_matrix(admin_id):
    """Occupied-seat count per purpose x shift combination, from the
    currently active-membership population. `columns` only includes
    OTHER_SHIFT_LABEL when at least one active membership actually falls
    into it, so the table doesn't grow an always-empty 4th column for an
    admin whose students all use the 3 standard shifts."""

    active = get_active_memberships(admin_id)

    columns = list(CANONICAL_SHIFTS)
    if any(_membership_bucket(m) == FULL_DAY_LABEL for m in active):
        columns.append(FULL_DAY_LABEL)
    if any(_membership_bucket(m) == OTHER_SHIFT_LABEL for m in active):
        columns.append(OTHER_SHIFT_LABEL)

    matrix = {}
    for m in active:
        purpose = (m.get("purpose") or "").strip() or NO_PURPOSE_LABEL
        shift = _membership_bucket(m)
        row = matrix.setdefault(purpose, {col: 0 for col in columns})
        row[shift] += 1

    rows = [
        {"purpose": purpose, "counts": counts, "total": sum(counts.values())}
        for purpose, counts in matrix.items()
    ]
    rows.sort(key=lambda r: r["total"], reverse=True)

    return {"columns": columns, "rows": rows}


def get_monthly_occupancy_trend(admin_id, months):
    """Overall occupancy % for each month in `months` ('YYYY-MM', oldest
    first), reconstructed from each membership's own joining_date/end_date
    range - there is no seat/attendance log to read (see module docstring
    above), so a membership counts toward a given month if that month
    falls anywhere inside [joining_date, end_date]. Distinct students only
    per month (a student with two overlapping membership rows in the same
    month, e.g. an early renewal, is counted once). Measured against
    *today's* total seat capacity - get_shift_capacities() has no
    historical snapshot of past capacity changes, so a capacity change
    retroactively reshapes every past month's percentage too (documented
    here, not hidden - see TD-49)."""

    memberships = get_memberships_for_admin(admin_id)
    total_capacity = sum(get_shift_capacities(admin_id).values())

    trend = []
    for month in months:
        year, mon = (int(part) for part in month.split("-"))
        month_start = date(year, mon, 1).isoformat()
        month_end = date(year, mon, calendar.monthrange(year, mon)[1]).isoformat()

        occupied_students = {
            m["student_id"] for m in memberships
            if m["joining_date"] and m["end_date"]
            and m["joining_date"] <= month_end and m["end_date"] >= month_start
        }

        pct = round(len(occupied_students) * 100 / total_capacity, 1) if total_capacity else 0.0
        trend.append(pct)

    return trend


def get_occupancy_insights(admin_id):
    """Rule-based Occupancy Analytics insights (highest/lowest utilized
    shift, overall occupancy/available seats, utilization trend direction,
    shift-balancing recommendation, >90% overload warnings, <50%
    under-utilization suggestions) - same type/icon/title/description
    shape get_action_items() established for the Overview page's Action
    Center, rendered here via templates/components/bi_occupancy_insights.html
    (a separate partial, since these signals are shift-utilization only,
    unrelated to Overview's revenue/retention ones)."""

    summary = get_occupancy_summary(admin_id)
    shifts = summary["shifts"]

    insights = []

    busiest = max(shifts, key=lambda s: s["utilization_pct"])
    quietest = min(shifts, key=lambda s: s["utilization_pct"])

    insights.append({
        "type": "info",
        "icon": "bi-graph-up-arrow",
        "title": f"{busiest['name']} Shift is the most utilized",
        "description": f"{busiest['utilization_pct']}% full ({busiest['occupied']} of {busiest['capacity']} seats).",
    })
    insights.append({
        "type": "info",
        "icon": "bi-graph-down-arrow",
        "title": f"{quietest['name']} Shift is the least utilized",
        "description": f"{quietest['utilization_pct']}% full ({quietest['occupied']} of {quietest['capacity']} seats).",
    })

    for shift in shifts:
        if shift["utilization_pct"] > 90:
            insights.append({
                "type": "danger",
                "icon": "bi-exclamation-triangle-fill",
                "title": f"{shift['name']} Shift is overloaded",
                "description": f"Running at {shift['utilization_pct']}% capacity - consider adding seats or steering new admissions to a quieter shift.",
            })
        elif shift["utilization_pct"] < 50:
            insights.append({
                "type": "warning",
                "icon": "bi-lightbulb-fill",
                "title": f"{shift['name']} Shift is underutilized",
                "description": f"Only {shift['utilization_pct']}% full - promote this shift to new enquiries or rebalance seats toward busier shifts.",
            })

    insights.append({
        "type": "success" if summary["occupancy_pct"] >= 50 else "warning",
        "icon": "bi-speedometer2",
        "title": f"Overall occupancy is {summary['occupancy_pct']}%",
        "description": f"{summary['total_available']} of {summary['total_capacity']} seats are currently available.",
    })

    trend = get_monthly_occupancy_trend(admin_id, last_n_months(6))
    if trend[0] != trend[-1]:
        rising = trend[-1] > trend[0]
        insights.append({
            "type": "success" if rising else "danger",
            "icon": "bi-arrow-up-right" if rising else "bi-arrow-down-right",
            "title": f"Occupancy has {'risen' if rising else 'fallen'} over the last {len(trend)} months",
            "description": f"From {trend[0]}% to {trend[-1]}%.",
        })

    if busiest["name"] != quietest["name"] and busiest["utilization_pct"] - quietest["utilization_pct"] > 20:
        insights.append({
            "type": "info",
            "icon": "bi-arrow-left-right",
            "title": "Shifts are unevenly balanced",
            "description": f"Consider steering new admissions toward {quietest['name']} Shift to balance load with {busiest['name']} Shift.",
        })

    return insights
