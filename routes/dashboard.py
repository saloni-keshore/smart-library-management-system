from datetime import date, timedelta

from flask import (
    Blueprint,
    render_template,
    session,
    redirect,
    request,
    jsonify
)
from postgrest.exceptions import APIError

from database.supabase_client import get_supabase_client
from utils.chart_data import build_revenue_chart_data, build_membership_chart_data
from database.cashbook_categories import (
    MANUAL_INCOME_CATEGORIES,
    MANUAL_EXPENSE_CATEGORIES,
    PAYMENT_METHODS
)
from database.cashbook_queries import (
    get_pending_fees,
    get_total_fee_revenue,
    get_today_fee_collection
)
from database.notification_settings_queries import get_notification_settings_cached
from database.membership_queries import (
    get_membership_counts, get_memberships_for_admin, get_admin_students, get_days_left
)


dashboard_bp = Blueprint(
    "dashboard",
    __name__
)


@dashboard_bp.route("/dashboard")
def dashboard():

    if "admin_id" not in session:
        return redirect("/")

    admin_id = session["admin_id"]

    supabase = get_supabase_client()

    # Total Students - Supabase `students` (ADR-19) instead of the SQLite
    # mirror.
    try:
        total_students = (
            supabase.table("students")
            .select("student_id", count="exact", head=True)
            .eq("admin_id", admin_id)
            .eq("status", "Active")
            .execute()
        ).count or 0
    except APIError:
        total_students = 0

    # Total Enquiries - Supabase `enquiries` (ADR-18) instead of the SQLite
    # mirror.
    try:
        total_enquiries = (
            supabase.table("enquiries")
            .select("enquiry_id", count="exact", head=True)
            .eq("admin_id", admin_id)
            .execute()
        ).count or 0
    except APIError:
        total_enquiries = 0

    # Active/Expired Memberships - shared with Membership Distribution's
    # identical counts (see database/membership_queries.py). Reads Supabase
    # `students`/`memberships` (ADR-23).
    membership_counts = get_membership_counts(admin_id)
    active_memberships = membership_counts["active"]
    expired_memberships = membership_counts["expired"]

    # Total Revenue (same source of truth as Membership Distribution's
    # "Revenue Collected" - see database/cashbook_queries.py)
    total_revenue = get_total_fee_revenue(admin_id)

    # Pending Amount (same source of truth as Cashbook's "Pending Fees" and
    # Membership Distribution's "Pending Payments")
    pending_amount = get_pending_fees(admin_id)

    # Today's Collection (same fee-revenue family as Total Revenue/Pending
    # Fees above - see database/cashbook_queries.py)
    today_collection = get_today_fee_collection(admin_id)

    # This admin's memberships (each row already carries full_name/mobile),
    # reused below for both Upcoming Expiries and Recent Admissions instead
    # of two separate SQL round-trips - Supabase `students`/`memberships`
    # (ADR-23).
    memberships = get_memberships_for_admin(admin_id)

    # Upcoming Expiries (next 7 days, nearest first)
    today_str = date.today().isoformat()
    cutoff_str = (date.today() + timedelta(days=7)).isoformat()

    expiring = sorted(
        (
            m for m in memberships
            if m["membership_status"] == "Active"
            and m["end_date"] and today_str <= m["end_date"] <= cutoff_str
        ),
        key=lambda m: m["end_date"]
    )

    expiries = [
        {
            "library_id": "LIB{:04d}".format(m["student_id"]),
            "student_name": m["full_name"],
            "end_date": m["end_date"],
            "days_left": get_days_left(m["end_date"])
        }
        for m in expiring[:5]
    ]
    expiries_total = len(expiring)

    # Recent Admissions (latest 5, newest first) - Supabase `students`
    # (ADR-19), each merged with its own latest membership from the list
    # already fetched above (same "keep the highest membership_id per
    # student" shape routes/student.py's index() uses, ADR-19).
    all_students = get_admin_students(admin_id)

    latest_membership_by_student = {}
    for m in memberships:
        current = latest_membership_by_student.get(m["student_id"])
        if current is None or m["membership_id"] > current["membership_id"]:
            latest_membership_by_student[m["student_id"]] = m

    admission_rows = sorted(
        all_students,
        key=lambda s: (s["join_date"] or "", s["student_id"]),
        reverse=True
    )[:5]

    admissions = [
        {
            "library_id": "LIB{:04d}".format(s["student_id"]),
            "student_name": s["full_name"],
            "plan": latest_membership_by_student.get(s["student_id"], {}).get("plan_name", "--") or "--",
            "admission_date": s["join_date"]
        }
        for s in admission_rows
    ]

    notification_settings = get_notification_settings_cached(admin_id)
    dash_show_pending_fees = (
        bool(notification_settings["dash_show_pending_fees"])
        if notification_settings else True
    )

    return render_template(
        "dashboard/index.html",
        total_students=total_students,
        total_enquiries=total_enquiries,
        active_memberships=active_memberships,
        expired_memberships=expired_memberships,
        total_revenue=total_revenue,
        pending_amount=pending_amount,
        today_collection=today_collection,
        expiries=expiries,
        expiries_total=expiries_total,
        upcoming_renewals=expiries_total,
        admissions=admissions,
        manual_income_categories=MANUAL_INCOME_CATEGORIES,
        manual_expense_categories=MANUAL_EXPENSE_CATEGORIES,
        payment_methods=PAYMENT_METHODS,
        dash_show_pending_fees=dash_show_pending_fees,
        revenue_chart_data=build_revenue_chart_data(admin_id, "this_year"),
        membership_chart_data=build_membership_chart_data(admin_id)
    )


@dashboard_bp.route("/dashboard/revenue-chart")
def revenue_chart():

    if "admin_id" not in session:
        return jsonify({}), 401

    admin_id = session["admin_id"]

    period = request.args.get("period", "this_year")
    if period not in ("this_year", "last_year"):
        period = "this_year"

    return jsonify(build_revenue_chart_data(admin_id, period))
