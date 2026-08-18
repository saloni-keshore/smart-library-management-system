import sys
import os
import random
import string

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app  # noqa: E402
from database.supabase_client import get_supabase_client  # noqa: E402


@pytest.fixture(scope="session")
def app():
    return create_app({
        "TESTING": True,
        "WTF_CSRF_ENABLED": False,
        "ENABLE_SELF_SERVICE_PASSWORD_RESET": True,
    })


@pytest.fixture()
def client(app):
    return app.test_client()


def _rand(n=6):
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def _rand_mobile():
    return "9" + "".join(random.choices(string.digits, k=9))


def get_admin_by_username(username):
    """admins now lives in Supabase (routes/auth.py) — replaces a SQLite lookup."""
    supabase = get_supabase_client()
    response = supabase.table("admins").select("*").eq("username", username).execute()
    return response.data[0] if response.data else None


@pytest.fixture()
def new_admin(client):
    """Registers a fresh, isolated admin account and returns its creds/id."""
    suffix = _rand()
    creds = {
        "full_name": f"QA Tester {suffix}",
        "username": f"qa_{suffix}",
        "mobile": _rand_mobile(),
        "email": f"qa_{suffix}@example.com",
        "password": "TestPass123",
        "confirm_password": "TestPass123",
    }
    resp = client.post("/register", data=creds, follow_redirects=True)
    assert resp.status_code == 200

    admin = get_admin_by_username(creds["username"])
    assert admin is not None, "registration did not create an admin row"

    creds["admin_id"] = admin["admin_id"]
    return creds


@pytest.fixture()
def logged_in_client(client, new_admin):
    resp = client.post(
        "/",
        data={"username": new_admin["username"], "password": new_admin["password"]},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    return client, new_admin


def make_enquiry(client, **overrides):
    data = {
        "full_name": "Test Enquirer",
        "mobile": _rand_mobile(),
        "purpose": "Study",
        "preferred_shift": "Morning",
        "followup_date": "2026-08-01",
        "remarks": "auto-created by QA suite",
    }
    data.update(overrides)
    resp = client.post("/enquiries/add", data=data, follow_redirects=True)
    return resp, data


def get_last_enquiry_id(admin_id):
    """enquiries now lives in Supabase only (routes/enquiries.py, ADR-30) -
    no SQLite mirror left to read."""
    supabase = get_supabase_client()
    response = (
        supabase.table("enquiries")
        .select("enquiry_id")
        .eq("admin_id", admin_id)
        .order("enquiry_id", desc=True)
        .limit(1)
        .execute()
    )
    return response.data[0]["enquiry_id"] if response.data else None


def get_enquiry_by_id(enquiry_id):
    """enquiries now lives in Supabase (routes/enquiries.py) — replaces a
    SQLite lookup for asserting the result of an add/edit/delete."""
    supabase = get_supabase_client()
    response = supabase.table("enquiries").select("*").eq("enquiry_id", enquiry_id).execute()
    return response.data[0] if response.data else None


def admit_student(client, enquiry_id, **overrides):
    data = {
        "address": "123 Test Street",
        "id_proof": "AADHAR-1234",
        "join_date": "2026-07-22",
    }
    data.update(overrides)
    resp = client.post(f"/students/admission/{enquiry_id}", data=data, follow_redirects=True)
    return resp


def get_last_student_id(admin_id):
    """students now lives in Supabase only (routes/student.py, ADR-29) - no
    SQLite mirror left to read."""
    supabase = get_supabase_client()
    response = (
        supabase.table("students")
        .select("student_id")
        .eq("admin_id", admin_id)
        .order("student_id", desc=True)
        .limit(1)
        .execute()
    )
    return response.data[0]["student_id"] if response.data else None


def get_student_by_id(student_id):
    """students now lives in Supabase (routes/student.py) — replaces a
    SQLite lookup for asserting the result of an admission/edit."""
    supabase = get_supabase_client()
    response = supabase.table("students").select("*").eq("student_id", student_id).execute()
    return response.data[0] if response.data else None


def create_membership(client, student_id, **overrides):
    """Defaults to the "Custom" plan so callers' paid_amount/due_amount
    directly control total_fee (routes/membership.py trusts a manually
    entered total_fee only for Custom - standard plans derive it from
    that admin's membership_settings, which most tests never seed).
    due_amount is folded into total_fee here rather than posted as-is,
    since the route no longer reads a due_amount field at all."""
    data = {
        "plan_name": "Custom",
        "joining_date": "2026-07-22",
        "duration": "30",
        "end_date": "2026-08-21",
        "remarks": "auto-created by QA suite",
        "payment_mode": "Cash",
        "paid_amount": "500",
        "due_amount": "0",
    }
    data.update(overrides)
    due_amount = data.pop("due_amount", "0")
    if "total_fee" not in data:
        try:
            data["total_fee"] = str(float(data["paid_amount"]) + float(due_amount))
        except (TypeError, ValueError):
            # paid_amount/due_amount isn't numeric - let the route's own
            # parsing surface the real "Invalid amount entered" error
            # rather than crashing test setup here.
            data["total_fee"] = due_amount
    resp = client.post(f"/memberships/create/{student_id}", data=data, follow_redirects=True)
    return resp


def save_membership_settings(client, **overrides):
    """POSTs Settings > Membership Settings so plan_pricing/admission_fee
    are non-default for this admin - required before create_membership()/
    the /memberships/renew POST is called with a standard plan_name
    (Monthly/Quarterly/Half-Yearly/Yearly), since those derive total_fee
    from this data server-side rather than trusting client input."""
    data = {
        "monthly_fee": "500", "monthly_days": "30",
        "quarterly_fee": "1400", "quarterly_days": "90",
        "half_yearly_fee": "2700", "half_yearly_days": "180",
        "yearly_fee": "5000", "yearly_days": "365",
        "admission_fee": "100", "late_fee_per_day": "10",
        "renewal_grace_days": "7",
        "auto_expiry": "on", "allow_early_renewal": "on",
    }
    data.update(overrides)
    return client.post("/settings/membership", data=data, follow_redirects=True)


def get_last_membership_id(student_id):
    """memberships now lives in Supabase only (routes/membership.py,
    ADR-29) - no SQLite mirror left to read."""
    supabase = get_supabase_client()
    response = (
        supabase.table("memberships")
        .select("membership_id")
        .eq("student_id", student_id)
        .order("membership_id", desc=True)
        .limit(1)
        .execute()
    )
    return response.data[0]["membership_id"] if response.data else None


def get_membership_by_id(membership_id):
    """memberships now lives in Supabase (routes/membership.py) — replaces a
    SQLite lookup for asserting the result of a create/renew."""
    supabase = get_supabase_client()
    response = supabase.table("memberships").select("*").eq("membership_id", membership_id).execute()
    return response.data[0] if response.data else None


def get_cashbook_entries(admin_id, **filters):
    """cashbook now lives in Supabase (routes/cashbook.py, ADR-22) — replaces
    a SQLite lookup for asserting ledger state after an add/edit. `filters`
    are applied as equality filters (e.g. category="Admission Fee")."""
    supabase = get_supabase_client()
    query = supabase.table("cashbook").select("*").eq("admin_id", admin_id)
    for key, value in filters.items():
        query = query.eq(key, value)
    return query.execute().data


def get_last_cashbook_entry(admin_id):
    entries = get_cashbook_entries(admin_id)
    return max(entries, key=lambda e: e["entry_id"]) if entries else None


def get_cashbook_entry_by_id(entry_id):
    supabase = get_supabase_client()
    response = supabase.table("cashbook").select("*").eq("entry_id", entry_id).execute()
    return response.data[0] if response.data else None


def get_audit_log_entries(admin_id, **filters):
    """audit_log now lives in Supabase (database/audit_queries.py, ADR-22)
    — replaces a SQLite lookup for asserting an audit trail row was made."""
    supabase = get_supabase_client()
    query = supabase.table("audit_log").select("*").eq("admin_id", admin_id)
    for key, value in filters.items():
        query = query.eq(key, value)
    return query.execute().data
