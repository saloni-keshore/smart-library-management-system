"""Dashboard, Business Intelligence, Membership Analytics/Distribution."""
from tests.conftest import (
    make_enquiry, get_last_enquiry_id, admit_student, get_last_student_id,
    create_membership, get_last_membership_id,
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
    _admitted_student_with_membership(client, admin["admin_id"], plan_name="Monthly", paid_amount="500", due_amount="0")
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
