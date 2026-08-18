"""
Data access + scoring for the AI Center (Phase 1 - Student Risk Analysis).

This is a rule-based retention-risk score, not a trained model. There is no
labeled "did this student churn" outcome anywhere in the schema and no
attendance/visit log to draw a real signal from (see docs/11_FUTURE_WORK.md
TD-49), so training a classifier would be fitting noise. Instead, a score is
computed from three signals that already exist and are individually
meaningful on their own - pending payment age, renewal/expiry timing, and
membership plan length - each weighted and blended the same way
get_business_health_score() blends its own components in bi_queries.py.

Every reason shown to the admin is the literal rule that fired, at the exact
weight that produced the score - there is no separate "explanation" layer to
keep in sync, and no black box. `purpose` (free text) is deliberately left
out of the score for now: there's no verified evidence a given purpose
category correlates with churn in this data, and fabricating a weight for it
would be a guess dressed up as insight (see docs/DECISIONS.md).

As of ADR-40, the three signal weights and the two risk-level thresholds are
admin-configurable (Settings, `database/ai_center_settings_queries.py`) -
this module has no hardcoded weight/threshold constants of its own anymore.
`compute_student_risk()` reads `get_effective_settings(admin_id)` once per
call and threads the result through every signal function, so changing a
weight in Settings changes scoring immediately, with no code change and no
redeploy.

Follows the same admin_id-scoped, dict/list-returning convention as
database/bi_queries.py and database/payment_queries.py.
"""

from datetime import date

from postgrest.exceptions import APIError

from database.ai_center_settings_queries import get_effective_settings
from database.membership_queries import get_admin_students, get_days_left, get_memberships_for_admin
from database.supabase_client import get_supabase_client


# A signal below this fraction doesn't surface as a reason - it's not
# meaningfully contributing to the score, just noise in the list. Internal
# sensitivity, not one of the admin-configurable weights/thresholds.
REASON_THRESHOLD = 0.15


def get_risk_level(score, high_risk_max, low_risk_min):
    """Buckets a 0-100 retention score into High/Medium/Low, using this
    admin's own configured thresholds (AI Center Settings, ADR-40)."""

    if score < high_risk_max:
        return "High"
    if score > low_risk_min:
        return "Low"
    return "Medium"


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------

def get_student_detail(admin_id, student_id):
    """One student's full identity row, scoped to this admin - the tenant
    check every other function here relies on: a student_id that doesn't
    belong to admin_id simply returns None, same as a real 404."""

    supabase = get_supabase_client()

    try:
        response = (
            supabase.table("students")
            .select("student_id, full_name, mobile, purpose, shift, join_date, status")
            .eq("admin_id", admin_id)
            .eq("student_id", student_id)
            .limit(1)
            .execute()
        )
        return response.data[0] if response.data else None
    except APIError:
        return None


def search_students(admin_id, query, limit=15):
    """Students whose name or mobile contains `query` (case-insensitive,
    partial match), for the autocomplete search box. Filters this admin's
    own roster (get_admin_students()) in Python rather than a PostgREST
    ilike call, the same fetch-then-filter shape the rest of this codebase
    uses since the client has no server-side JOIN to lean on anyway.

    Each match is enriched with `plan_name` (that student's latest
    membership's plan, or None if they've never had one) so the
    autocomplete dropdown can show it without a second round trip per
    suggestion. `limit` exists only to keep the dropdown a sane size - two
    students sharing a name is common enough that every genuine match
    should still fit well under it, so this is never a "hide duplicates"
    mechanism.
    """

    query = (query or "").strip().lower()
    if not query:
        return []

    students = get_admin_students(admin_id)
    matches = [
        s for s in students
        if query in (s.get("full_name") or "").lower()
        or query in (s.get("mobile") or "")
    ][:limit]

    if matches:
        memberships = get_memberships_for_admin(admin_id)
        latest_plan_by_student = {}
        for m in memberships:
            sid = m["student_id"]
            if sid not in latest_plan_by_student or m["membership_id"] > latest_plan_by_student[sid][0]:
                latest_plan_by_student[sid] = (m["membership_id"], m.get("plan_name"))
        for s in matches:
            s["plan_name"] = latest_plan_by_student.get(s["student_id"], (None, None))[1]

    return matches


def _memberships_for_student(student_id):
    """A single student's own membership rows, oldest first. Takes only
    student_id, not admin_id - callers must have already confirmed this
    student belongs to the current admin (via get_student_detail()), the
    same trust boundary database.membership_queries.get_active_membership()
    already relies on."""

    supabase = get_supabase_client()

    try:
        response = (
            supabase.table("memberships")
            .select("*")
            .eq("student_id", student_id)
            .order("membership_id")
            .execute()
        )
        return response.data
    except APIError:
        return []


def _payments_for_student(student_id):
    """A single student's own payment rows. Same student_id-only trust
    boundary as _memberships_for_student() above."""

    supabase = get_supabase_client()

    try:
        response = (
            supabase.table("payments")
            .select("*")
            .eq("student_id", student_id)
            .order("payment_date")
            .execute()
        )
        return response.data
    except APIError:
        return []


# ---------------------------------------------------------------------------
# Signals - each returns (risk_fraction 0-1, reason or None, action or None).
# A signal that isn't contributing anything returns (0.0, None, None).
# ---------------------------------------------------------------------------

def _payment_delay_signal(latest_membership, payments):
    """Risk from an unpaid balance on the student's latest membership,
    scaled by how long it's been outstanding.

    There's no due-date column on `payments` to compare against, so "delay"
    is measured from the last payment actually made on this membership (or
    from joining_date if none has been made yet) - a proxy, not a true
    days-overdue figure. Documented as TD-51 in docs/11_FUTURE_WORK.md.
    """

    if latest_membership is None:
        return 0.0, None, None

    pending = latest_membership.get("pending_amount") or 0
    if pending <= 0:
        return 0.0, None, None

    membership_payments = [
        p for p in payments
        if p["membership_id"] == latest_membership["membership_id"] and p["payment_date"]
    ]
    if membership_payments:
        last_date = max(p["payment_date"] for p in membership_payments)
    else:
        last_date = latest_membership.get("joining_date")

    delay_days = 0
    if last_date:
        delay_days = max(0, (date.today() - date.fromisoformat(last_date)).days)

    risk = min(1.0, 0.3 + 0.7 * min(delay_days, 30) / 30)

    if delay_days <= 0:
        reason = f"New pending balance of ₹{pending:,.0f}"
    else:
        day_word = "day" if delay_days == 1 else "days"
        reason = f"₹{pending:,.0f} pending, {delay_days} {day_word} since last payment"
    action = "Follow up on the pending balance within 2 days"

    return risk, reason, action


def _renewal_signal(memberships, latest_membership):
    """Risk from how close the student is to lapsing with nothing booked
    after their current membership, plus a small bump if they've renewed
    late before.

    A renewal always inserts a *new* membership row (docs/DECISIONS.md), so
    "latest_membership" is already the newest thing the student has booked -
    if its end_date is approaching or past, nothing later exists yet.
    """

    if latest_membership is None:
        return 0.0, None, None

    days_left = get_days_left(latest_membership.get("end_date"))
    if days_left is None:
        return 0.0, None, None

    if days_left < 0:
        overdue = abs(days_left)
        day_word = "day" if overdue == 1 else "days"
        risk = 1.0
        reason = f"Membership expired {overdue} {day_word} ago with no renewal booked"
        action = "Reach out immediately - this student has already lapsed"
    elif days_left <= 7:
        day_word = "day" if days_left == 1 else "days"
        risk = 0.6
        reason = f"Membership expires in {days_left} {day_word} with no renewal booked yet"
        action = "Send a renewal reminder and offer to help book the next plan"
    elif days_left <= 30:
        risk = 0.3
        reason = f"Membership expires in {days_left} days"
        action = "Plan a renewal follow-up before the expiry date"
    else:
        risk, reason, action = 0.0, None, None

    if len(memberships) >= 2:
        ordered = sorted(memberships, key=lambda m: m["membership_id"])
        has_late_renewal = any(
            prev.get("end_date") and nxt.get("joining_date") and nxt["joining_date"] > prev["end_date"]
            for prev, nxt in zip(ordered, ordered[1:])
        )
        if has_late_renewal:
            risk = min(1.0, risk + 0.2)
            if reason:
                reason += "; has renewed late before"
            else:
                reason = "Has a history of renewing late"
                action = "Set an earlier reminder this time to avoid another late renewal"

    return risk, reason, action


def _duration_signal(latest_membership):
    """Risk from plan length alone - a Monthly plan is structurally easier
    to lapse than a Yearly one, independent of how this particular student
    is behaving. Uses `duration_days` directly (continuous) rather than
    matching on `plan_name` text, so a custom/renamed plan still scores
    sensibly instead of falling into an "Unknown" bucket."""

    if latest_membership is None:
        return 0.0, None, None

    duration_days = latest_membership.get("duration_days") or 30
    risk = max(0.0, min(1.0, 1 - duration_days / 365))

    if risk <= REASON_THRESHOLD:
        return risk, None, None

    plan_name = latest_membership.get("plan_name") or "this plan"
    reason = f"Short membership plan ({plan_name}) is easier to lapse than a longer one"
    action = "Offer a discount to upgrade to a longer (quarterly or yearly) plan"
    return risk, reason, action


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def compute_student_risk(admin_id, student_id):
    """Full risk breakdown for one student: score, level, ranked reasons +
    their matched actions, and the key-info figures shown alongside them.
    Returns None if student_id doesn't belong to admin_id."""

    student = get_student_detail(admin_id, student_id)
    if student is None:
        return None

    settings = get_effective_settings(admin_id)

    memberships = _memberships_for_student(student_id)
    payments = _payments_for_student(student_id)
    latest_membership = max(memberships, key=lambda m: m["membership_id"]) if memberships else None

    payment_risk, payment_reason, payment_action = _payment_delay_signal(latest_membership, payments)
    renewal_risk, renewal_reason, renewal_action = _renewal_signal(memberships, latest_membership)
    duration_risk, duration_reason, duration_action = _duration_signal(latest_membership)

    weighted_risk = (
        settings["weight_payment_delay"] / 100 * payment_risk
        + settings["weight_renewal_history"] / 100 * renewal_risk
        + settings["weight_membership_duration"] / 100 * duration_risk
    )
    score = max(0, min(100, round(100 * (1 - weighted_risk))))
    level = get_risk_level(score, settings["high_risk_max"], settings["low_risk_min"])

    signals = [
        (payment_risk, payment_reason, payment_action),
        (renewal_risk, renewal_reason, renewal_action),
        (duration_risk, duration_reason, duration_action),
    ]
    reasons = [
        {"reason": reason, "action": action}
        for risk, reason, action in sorted(signals, key=lambda s: s[0], reverse=True)
        if risk > REASON_THRESHOLD and reason
    ]

    total_paid = sum(p["amount_paid"] or 0 for p in payments)
    last_payment_date = max(
        (p["payment_date"] for p in payments if p["payment_date"]), default=None
    )
    total_days = None
    if student.get("join_date"):
        total_days = (date.today() - date.fromisoformat(student["join_date"])).days

    return {
        "student": student,
        "latest_membership": latest_membership,
        "score": score,
        "level": level,
        "reasons": reasons,
        "key_info": {
            "total_days": total_days,
            "total_paid": total_paid,
            "pending_amount": (latest_membership or {}).get("pending_amount") or 0,
            "last_payment_date": last_payment_date,
        },
    }
