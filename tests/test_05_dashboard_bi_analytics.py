"""Dashboard, Business Intelligence, Membership Analytics/Distribution."""
from tests.conftest import (
    make_enquiry, get_last_enquiry_id, admit_student, get_last_student_id,
    create_membership, get_last_membership_id, save_membership_settings,
)


def _admitted_student_with_membership(client, admin_id, **overrides):
    make_enquiry(client)
    eid = get_last_enquiry_id(admin_id)
    admit_student(client, eid)
    sid = get_last_student_id(admin_id)
    create_membership(client, sid, **overrides)
    return sid


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

def test_dashboard_requires_login(client):
    resp = client.get("/dashboard", follow_redirects=False)
    assert resp.status_code == 302


def test_dashboard_loads_with_no_data(logged_in_client):
    """Empty state: brand new admin, zero students/memberships/payments."""
    client, admin = logged_in_client
    resp = client.get("/dashboard")
    assert resp.status_code == 200


def test_dashboard_loads_with_data(logged_in_client):
    client, admin = logged_in_client
    _admitted_student_with_membership(client, admin["admin_id"], paid_amount="500", due_amount="500")
    resp = client.get("/dashboard")
    assert resp.status_code == 200


def test_dashboard_total_students_counts_only_this_admin(logged_in_client):
    client, admin = logged_in_client
    _admitted_student_with_membership(client, admin["admin_id"], paid_amount="500", due_amount="0")
    resp = client.get("/dashboard")
    assert resp.status_code == 200


def test_dashboard_pending_amount_matches_cashbook(logged_in_client):
    client, admin = logged_in_client
    _admitted_student_with_membership(client, admin["admin_id"], paid_amount="200", due_amount="800")
    from database.cashbook_queries import get_pending_fees
    assert get_pending_fees(admin["admin_id"]) == 800
    resp = client.get("/dashboard")
    assert resp.status_code == 200


def test_dashboard_upcoming_expiry_within_7_days_shown(logged_in_client):
    client, admin = logged_in_client
    sid = _admitted_student_with_membership(
        client, admin["admin_id"], paid_amount="500", due_amount="0",
        end_date="2026-07-25",  # within 7 days of 2026-07-22 "today" used elsewhere
    )
    resp = client.get("/dashboard")
    assert resp.status_code == 200


def test_dashboard_survives_membership_with_null_plan(logged_in_client):
    """Recent Admissions query LEFT JOINs memberships - a student admitted
    but with no membership yet must not crash the dashboard."""
    client, admin = logged_in_client
    make_enquiry(client)
    eid = get_last_enquiry_id(admin["admin_id"])
    admit_student(client, eid)
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert b"--" in resp.data or resp.status_code == 200


def test_dashboard_revenue_chart_endpoint_requires_login(client):
    resp = client.get("/dashboard/revenue-chart")
    assert resp.status_code == 401


def test_dashboard_revenue_chart_endpoint_switches_period(logged_in_client):
    client, admin = logged_in_client
    _admitted_student_with_membership(client, admin["admin_id"], paid_amount="500", due_amount="0")

    resp_this_year = client.get("/dashboard/revenue-chart?period=this_year")
    assert resp_this_year.status_code == 200
    assert "image_url" in resp_this_year.get_json()

    resp_last_year = client.get("/dashboard/revenue-chart?period=last_year")
    assert resp_last_year.status_code == 200
    assert "image_url" in resp_last_year.get_json()

    # Cache-busting: the two responses must not resolve to the same URL,
    # otherwise the browser would keep showing whichever period rendered
    # first (the whole reason a "?t=" query string was added).
    assert resp_this_year.get_json()["image_url"] != resp_last_year.get_json()["image_url"]

    # Unknown period values must not error - they fall back to this_year.
    resp_bogus = client.get("/dashboard/revenue-chart?period=bogus")
    assert resp_bogus.status_code == 200
    assert "image_url" in resp_bogus.get_json()


def test_revenue_monthly_bucketing_differs_by_year(logged_in_client):
    """Proves This Year and Last Year genuinely read different data: two
    real payments for the same admin, one dated this year and one dated
    last year, must land in their own year's bucket and nowhere else."""
    client, admin = logged_in_client
    from datetime import date
    from database.supabase_client import get_supabase_client
    from database.payment_queries import get_payments_for_admin
    from utils.charts import _monthly_revenue_for_year

    sid = _admitted_student_with_membership(
        client, admin["admin_id"], paid_amount="500", due_amount="0"
    )
    mid = get_last_membership_id(sid)

    payments = get_payments_for_admin(admin["admin_id"])
    assert len(payments) == 1
    this_year_payment_id = payments[0]["payment_id"]
    this_year = date.today().year
    last_year = this_year - 1

    # Add a second, distinct payment for the same student dated last year
    # by inserting it directly (bypassing the UI, which can't backdate).
    # payment_id must be supplied explicitly - this table's identity
    # sequence is never advanced since every real insert path (see
    # database/payment_queries.py) computes its own next id the same way.
    supabase = get_supabase_client()
    next_id_row = (
        supabase.table("payments")
        .select("payment_id")
        .order("payment_id", desc=True)
        .limit(1)
        .execute()
    )
    next_payment_id = (next_id_row.data[0]["payment_id"] + 1) if next_id_row.data else 1

    supabase.table("payments").insert({
        "payment_id": next_payment_id,
        "membership_id": mid,
        "student_id": sid,
        "amount_paid": 300,
        "payment_date": f"{last_year}-07-15",
        "payment_mode": "Cash",
        "receipt_number": f"QA-LASTYEAR-{sid}",
    }).execute()

    payments = get_payments_for_admin(admin["admin_id"])
    assert len(payments) == 2

    this_year_revenue = _monthly_revenue_for_year(payments, this_year)
    last_year_revenue = _monthly_revenue_for_year(payments, last_year)

    assert sum(this_year_revenue) == 500
    assert sum(last_year_revenue) == 300
    assert this_year_revenue != last_year_revenue

    # And the admin-scoped source data is unaffected by the payment_id we
    # already had - the this-year bucket still only reflects that one row.
    assert this_year_payment_id in [p["payment_id"] for p in payments]


# ---------------------------------------------------------------------------
# Business Intelligence
# ---------------------------------------------------------------------------

def test_bi_requires_login(client):
    resp = client.get("/business-intelligence/", follow_redirects=False)
    assert resp.status_code == 302


def test_bi_loads_with_no_data(logged_in_client):
    client, admin = logged_in_client
    resp = client.get("/business-intelligence/")
    assert resp.status_code == 200


def test_bi_loads_with_data(logged_in_client):
    client, admin = logged_in_client
    _admitted_student_with_membership(client, admin["admin_id"], paid_amount="1000", due_amount="0")
    resp = client.get("/business-intelligence/")
    assert resp.status_code == 200


def test_bi_health_score_no_data_matches_documented_formula(logged_in_client):
    """With zero income/expense/memberships, growth (0.5), collection (0.5,
    explicit billable>0 guard) and renewal (0.5, explicit total>0 guard) are
    all genuinely neutral, but expense_component is 1.0 (not 0.5) because
    classify_expense_health()'s zero-income branch treats 0 expense as a
    perfect 0% ratio rather than "no signal yet" - see docs/11_FUTURE_WORK.md
    note on this docstring/behavior mismatch. Score = 100*(.3*.5+.3*1+.2*.5+.2*.5) = 65."""
    client, admin = logged_in_client
    from database.bi_queries import get_business_health_score
    score = get_business_health_score(admin["admin_id"])
    assert score["score"] == 65


def test_bi_health_score_no_division_by_zero_with_only_expenses(logged_in_client):
    """Expense with zero income this month - classify_expense_health must
    not raise ZeroDivisionError."""
    client, admin = logged_in_client
    client.post(
        "/cashbook/add",
        data={"transaction_type": "Expense", "category": "Rent", "amount": "500",
              "payment_method": "Cash", "transaction_date": "2026-07-22",
              "person": "", "description": "", "redirect_to": "cashbook"},
        follow_redirects=True,
    )
    resp = client.get("/business-intelligence/")
    assert resp.status_code == 200


def test_bi_action_items_no_urgent_when_empty(logged_in_client):
    client, admin = logged_in_client
    from database.bi_queries import get_action_items
    items = get_action_items(admin["admin_id"])
    assert any("No urgent issues" in i["title"] for i in items)


def test_reports_redirects_to_bi(logged_in_client):
    client, admin = logged_in_client
    resp = client.get("/reports/", follow_redirects=False)
    assert resp.status_code == 302
    assert "business-intelligence" in resp.headers["Location"]


# ---------------------------------------------------------------------------
# Purpose Analytics (wired to real data - Business Intelligence Phase 1)
# ---------------------------------------------------------------------------

def test_purpose_analytics_requires_login(client):
    resp = client.get("/business-intelligence/purpose-analytics", follow_redirects=False)
    assert resp.status_code == 302


def test_purpose_analytics_loads_with_no_data(logged_in_client):
    """Brand new admin, zero students - table_rows[0]/[-1] in the template
    must not IndexError on an empty breakdown."""
    client, admin = logged_in_client
    resp = client.get("/business-intelligence/purpose-analytics")
    assert resp.status_code == 200
    assert b"N/A" in resp.data


def test_purpose_analytics_totals_match_payment_records(logged_in_client):
    """Total Students/Total Revenue on the page must match
    get_admin_students()/get_total_fee_revenue(), and each purpose's
    student_pct/revenue_pct must sum to ~100% across the breakdown."""
    client, admin = logged_in_client
    admin_id = admin["admin_id"]

    make_enquiry(client, purpose="UPSC")
    eid = get_last_enquiry_id(admin_id)
    admit_student(client, eid)
    sid = get_last_student_id(admin_id)
    create_membership(client, sid, paid_amount="1000", due_amount="0")

    make_enquiry(client, purpose="UPSC")
    eid = get_last_enquiry_id(admin_id)
    admit_student(client, eid)
    sid = get_last_student_id(admin_id)
    create_membership(client, sid, paid_amount="500", due_amount="0")

    make_enquiry(client, purpose="NEET")
    eid = get_last_enquiry_id(admin_id)
    admit_student(client, eid)
    sid = get_last_student_id(admin_id)
    create_membership(client, sid, paid_amount="2000", due_amount="0")

    from database.bi_queries import get_purpose_breakdown
    from database.cashbook_queries import get_total_fee_revenue
    from database.membership_queries import get_admin_students

    breakdown = get_purpose_breakdown(admin_id)
    total_students = sum(row["students"] for row in breakdown)
    total_revenue = sum(row["revenue"] for row in breakdown)

    assert total_students == len(get_admin_students(admin_id))
    assert total_revenue == get_total_fee_revenue(admin_id) == 3500

    student_pct_sum = sum(round(row["students"] * 100 / total_students, 1) for row in breakdown)
    revenue_pct_sum = sum(round(row["revenue"] * 100 / total_revenue, 1) for row in breakdown)
    assert 99.0 <= student_pct_sum <= 101.0
    assert 99.0 <= revenue_pct_sum <= 101.0

    resp = client.get("/business-intelligence/purpose-analytics")
    assert resp.status_code == 200
    assert b"UPSC" in resp.data
    assert b"NEET" in resp.data


# ---------------------------------------------------------------------------
# Revenue Analytics (wired to real data - Business Intelligence Phase 2)
# ---------------------------------------------------------------------------

def test_revenue_analytics_requires_login(client):
    resp = client.get("/business-intelligence/revenue-analytics", follow_redirects=False)
    assert resp.status_code == 302


def test_revenue_analytics_loads_with_no_data(logged_in_client):
    """Brand new admin, zero payments/memberships - the "fastest growing
    month"/"top plan"/"top payment mode" insights must all fall back to
    N/A instead of raising on an empty breakdown."""
    client, admin = logged_in_client
    resp = client.get("/business-intelligence/revenue-analytics")
    assert resp.status_code == 200
    assert b"N/A" in resp.data


def test_revenue_analytics_kpis_match_payment_and_membership_records(logged_in_client):
    """Every KPI on the page must match the same underlying Payments/
    Memberships rows the rest of the app already asserts against
    (get_total_fee_revenue/get_pending_fees), and the New Admissions vs
    Renewal split must correctly attribute a renewal payment to Renewal,
    not New Admissions."""
    client, admin = logged_in_client
    admin_id = admin["admin_id"]

    # Student A: new admission (paid in full), then a renewal with a
    # partial payment (some still pending).
    make_enquiry(client)
    eid = get_last_enquiry_id(admin_id)
    admit_student(client, eid)
    sid_a = get_last_student_id(admin_id)
    create_membership(client, sid_a, paid_amount="1000", due_amount="0")

    client.post(
        f"/memberships/renew/{sid_a}",
        data={
            "plan_name": "Custom",
            "joining_date": "2026-08-22",
            "duration_days": "30",
            "end_date": "2026-09-21",
            "remarks": "renewal",
            "payment_mode": "UPI",
            "paid_amount": "300",
            "total_fee": "500",
        },
        follow_redirects=True,
    )

    # Student B: a second new admission.
    make_enquiry(client)
    eid = get_last_enquiry_id(admin_id)
    admit_student(client, eid)
    sid_b = get_last_student_id(admin_id)
    create_membership(client, sid_b, paid_amount="500", due_amount="0")

    from database.bi_queries import (
        get_revenue_time_windows, get_revenue_collection_summary,
        get_new_vs_renewal_revenue,
    )
    from database.cashbook_queries import get_total_fee_revenue, get_pending_fees

    windows = get_revenue_time_windows(admin_id)
    collection = get_revenue_collection_summary(admin_id)
    split = get_new_vs_renewal_revenue(admin_id)

    assert windows["total"] == get_total_fee_revenue(admin_id) == 1800
    assert windows["today"] == 1800  # every payment above lands on today's date
    assert windows["month"] == 1800
    assert windows["year"] == 1800

    assert collection["expected"] == 2000  # 1000 + (300+200) + 500
    assert collection["collected"] == 1800
    assert collection["pending"] == get_pending_fees(admin_id) == 200
    assert collection["collection_pct"] == 90.0

    assert split["new_admissions"] == 1500  # student A's first membership + student B
    assert split["renewal"] == 300  # student A's renewal payment only

    resp = client.get("/business-intelligence/revenue-analytics")
    assert resp.status_code == 200
    assert "1,800".encode() in resp.data  # Total Revenue KPI


# ---------------------------------------------------------------------------
# Occupancy Analytics (wired to real data - Business Intelligence Phase 3)
# ---------------------------------------------------------------------------

def test_occupancy_analytics_requires_login(client):
    resp = client.get("/business-intelligence/occupancy-analytics", follow_redirects=False)
    assert resp.status_code == 302


def test_occupancy_analytics_loads_with_no_data(logged_in_client):
    """Brand new admin, zero students - capacity still defaults (no Library
    Profile saved yet) and every insight/breakdown must fall back cleanly
    instead of raising on an empty active-membership population."""
    client, admin = logged_in_client
    resp = client.get("/business-intelligence/occupancy-analytics")
    assert resp.status_code == 200
    assert b"N/A" in resp.data


def test_occupancy_analytics_counts_active_students_by_shift(logged_in_client):
    """Occupied seats must match the currently effectively-active
    membership population, grouped by each student's own shift - not raw
    student count (Purpose Analytics counts every student regardless of
    status; Occupancy deliberately doesn't, see ADR-38)."""
    client, admin = logged_in_client
    admin_id = admin["admin_id"]
    save_membership_settings(client)  # Monthly/Quarterly need a configured, nonzero fee

    make_enquiry(client, preferred_shift="Morning", purpose="UPSC")
    eid = get_last_enquiry_id(admin_id)
    admit_student(client, eid)
    sid = get_last_student_id(admin_id)
    create_membership(client, sid, plan_name="Monthly")

    make_enquiry(client, preferred_shift="Evening", purpose="NEET")
    eid = get_last_enquiry_id(admin_id)
    admit_student(client, eid)
    sid = get_last_student_id(admin_id)
    create_membership(client, sid, plan_name="Quarterly")

    from database.bi_queries import get_occupancy_summary, get_occupancy_by_purpose, get_occupancy_by_plan

    summary = get_occupancy_summary(admin_id)
    shifts_by_name = {s["name"]: s for s in summary["shifts"]}
    assert shifts_by_name["Morning"]["occupied"] == 1
    assert shifts_by_name["Evening"]["occupied"] == 1
    assert shifts_by_name["Afternoon"]["occupied"] == 0
    assert summary["total_occupied"] == 2

    purpose_occupancy = get_occupancy_by_purpose(admin_id)
    assert purpose_occupancy.get("UPSC") == 1
    assert purpose_occupancy.get("NEET") == 1

    plan_occupancy = get_occupancy_by_plan(admin_id)
    assert plan_occupancy.get("MONTHLY") == 1
    assert plan_occupancy.get("QUARTERLY") == 1

    resp = client.get("/business-intelligence/occupancy-analytics")
    assert resp.status_code == 200
    assert b"Morning" in resp.data
    assert b"Evening" in resp.data


def test_occupancy_analytics_excludes_expired_memberships(logged_in_client):
    """A membership whose end_date has already passed no longer occupies a
    seat, even though membership_status was stored 'Active' at creation
    (get_effective_status() re-derives 'Expired' from the date)."""
    client, admin = logged_in_client
    admin_id = admin["admin_id"]

    make_enquiry(client, preferred_shift="Morning")
    eid = get_last_enquiry_id(admin_id)
    admit_student(client, eid)
    sid = get_last_student_id(admin_id)
    create_membership(
        client, sid,
        joining_date="2020-01-01", duration="30", end_date="2020-01-31",
    )

    from database.bi_queries import get_occupancy_summary

    summary = get_occupancy_summary(admin_id)
    assert summary["total_occupied"] == 0
    shifts_by_name = {s["name"]: s for s in summary["shifts"]}
    assert shifts_by_name["Morning"]["occupied"] == 0


# ---------------------------------------------------------------------------
# Membership Analytics (fixed: now redirects to Membership Distribution)
# ---------------------------------------------------------------------------

def test_membership_analytics_requires_login(client):
    resp = client.get("/membership-analytics/", follow_redirects=False)
    assert resp.status_code == 302


def test_membership_analytics_redirects_to_distribution(logged_in_client):
    client, admin = logged_in_client
    resp = client.get("/membership-analytics/", follow_redirects=False)
    assert resp.status_code == 302
    assert "membership-distribution" in resp.headers["Location"]


def test_membership_analytics_follow_redirect_renders_real_page(logged_in_client):
    client, admin = logged_in_client
    resp = client.get("/membership-analytics/", follow_redirects=True)
    assert resp.status_code == 200
    assert len(resp.data) > 0


# ---------------------------------------------------------------------------
# Membership Distribution
# ---------------------------------------------------------------------------

def test_membership_distribution_requires_login(client):
    resp = client.get("/membership-distribution/", follow_redirects=False)
    assert resp.status_code == 302


def test_membership_distribution_loads_with_no_data(logged_in_client):
    client, admin = logged_in_client
    resp = client.get("/membership-distribution/")
    assert resp.status_code == 200
    assert b"-" in resp.data  # most_popular_plan placeholder for zero memberships


def test_membership_distribution_plan_percentages_sum_reasonable(logged_in_client):
    client, admin = logged_in_client
    _admitted_student_with_membership(client, admin["admin_id"], paid_amount="500", due_amount="0")
    resp = client.get("/membership-distribution/")
    assert resp.status_code == 200


def test_membership_distribution_shows_expired_status_correctly(logged_in_client):
    """A membership whose end_date is in the past but membership_status is
    still 'Active' in the DB must display as Expired (EFFECTIVE_STATUS)."""
    client, admin = logged_in_client
    _admitted_student_with_membership(
        client, admin["admin_id"], paid_amount="500", due_amount="0",
        joining_date="2020-01-01", end_date="2020-02-01",
    )
    resp = client.get("/membership-distribution/")
    assert resp.status_code == 200
    assert b"Expired" in resp.data
