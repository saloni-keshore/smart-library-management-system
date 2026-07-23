import sys
import os
import random
import string

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app  # noqa: E402
from database.db import get_connection  # noqa: E402
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
    """enquiries.add() mirror-inserts into SQLite under the same enquiry_id
    (TD-36), so this SQLite lookup still returns the right id post-migration."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT enquiry_id FROM enquiries WHERE admin_id=? ORDER BY enquiry_id DESC LIMIT 1",
        (admin_id,),
    )
    row = cur.fetchone()
    conn.close()
    return row["enquiry_id"] if row else None


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
    """students.admission() mirror-inserts into SQLite under the same
    student_id, so this SQLite lookup still returns the right id post-
    migration."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT student_id FROM students WHERE admin_id=? ORDER BY student_id DESC LIMIT 1",
        (admin_id,),
    )
    row = cur.fetchone()
    conn.close()
    return row["student_id"] if row else None


def get_student_by_id(student_id):
    """students now lives in Supabase (routes/student.py) — replaces a
    SQLite lookup for asserting the result of an admission/edit."""
    supabase = get_supabase_client()
    response = supabase.table("students").select("*").eq("student_id", student_id).execute()
    return response.data[0] if response.data else None


def create_membership(client, student_id, **overrides):
    data = {
        "plan_name": "Monthly",
        "joining_date": "2026-07-22",
        "duration": "30",
        "end_date": "2026-08-21",
        "remarks": "auto-created by QA suite",
        "payment_mode": "Cash",
        "paid_amount": "500",
        "due_amount": "0",
    }
    data.update(overrides)
    resp = client.post(f"/memberships/create/{student_id}", data=data, follow_redirects=True)
    return resp


def get_last_membership_id(student_id):
    """memberships.create()/renew() mirror-insert into SQLite under the same
    membership_id, so this SQLite lookup still returns the right id post-
    migration."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT membership_id FROM memberships WHERE student_id=? ORDER BY membership_id DESC LIMIT 1",
        (student_id,),
    )
    row = cur.fetchone()
    conn.close()
    return row["membership_id"] if row else None


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
