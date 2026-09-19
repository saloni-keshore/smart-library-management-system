"""Bug 1 regression, extended (ADR-81, TD-108): the same deterministic
global-ID collision fixed for enquiries/students/shift_slots (ADR-79, see
tests/test_18_id_allocation.py) also existed, independently implemented,
for `memberships.membership_id` (routes/membership.py + database/
membership_queries.py), `payments.payment_id` (database/payment_queries.py),
and `cashbook.entry_id` (database/cashbook_queries.py) - none of them went
through database/id_sequence.py's insert_with_next_id(), so ADR-79 alone
didn't cover them. These tests prove a brand-new tenant's first membership/
payment/cashbook entry succeeds regardless of what ids other tenants
already hold, that two tenants never collide, and that the fix never
renumbers an existing row.
"""
import random
import string

from database.supabase_client import get_service_role_client
from tests.conftest import (
    get_admin_by_username,
    make_enquiry,
    get_last_enquiry_id,
    admit_student,
    create_membership,
    get_last_membership_id,
    get_membership_by_id,
    get_last_cashbook_entry,
    get_cashbook_entry_by_id,
)


def _register(client, label):
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    creds = {
        "full_name": f"QA {label} {suffix}",
        "username": f"qa_{label}_{suffix}",
        "mobile": "9" + "".join(random.choices(string.digits, k=9)),
        "email": f"qa_{label}_{suffix}@example.com",
        "password": "TestPass123",
        "confirm_password": "TestPass123",
    }
    resp = client.post("/register", data=creds, follow_redirects=True)
    assert resp.status_code == 200
    admin = get_admin_by_username(creds["username"])
    assert admin is not None, "registration did not create an admin row"
    creds["admin_id"] = admin["admin_id"]

    login_resp = client.post(
        "/", data={"username": creds["username"], "password": creds["password"]},
        follow_redirects=True,
    )
    assert login_resp.status_code == 200
    return creds


def _admit_and_pay(client, admin, mobile, paid_amount="500"):
    """Registers an enquiry, admits it, and creates a fully-paid Custom
    membership - one HTTP call chain that exercises all three ids
    (membership_id, payment_id via record_payment(), entry_id via the
    automatic Cashbook Income entry) in a single request path, the same way
    a real admission does."""
    enquiry_resp, _ = make_enquiry(client, mobile=mobile)
    assert enquiry_resp.status_code == 200
    enquiry_id = get_last_enquiry_id(admin["admin_id"])
    assert enquiry_id is not None

    admit_resp = admit_student(client, enquiry_id)
    assert admit_resp.status_code == 200

    supabase = get_service_role_client()
    student = (
        supabase.table("students")
        .select("student_id")
        .eq("admin_id", admin["admin_id"])
        .order("student_id", desc=True)
        .limit(1)
        .execute()
        .data[0]
    )
    student_id = student["student_id"]

    membership_resp = create_membership(client, student_id, paid_amount=paid_amount, due_amount="0")
    assert membership_resp.status_code == 200
    assert b"Membership created successfully" in membership_resp.data

    return student_id


def _last_payment_for(admin_id):
    supabase = get_service_role_client()
    rows = (
        supabase.table("payments")
        .select("*")
        .eq("admin_id", admin_id)
        .order("payment_id", desc=True)
        .limit(1)
        .execute()
        .data
    )
    return rows[0] if rows else None


def test_new_tenant_membership_payment_cashbook_succeed_when_other_tenant_owns_global_ids(app):
    """Core regression: tenant A already holds global membership_id/
    payment_id/entry_id values before brand-new tenant B (zero rows of its
    own in any of the three tables) ever inserts. Pre-fix, B's RLS-filtered
    MAX was always empty for each of these, so B's computed next id was
    always 1 - a guaranteed collision on B's very first membership/payment/
    cashbook write whenever any tenant anywhere already owned that id."""
    client_a = app.test_client()
    admin_a = _register(client_a, "moneya")
    student_id_a = _admit_and_pay(client_a, admin_a, "9200000001")

    seeded_membership_id = get_last_membership_id(student_id_a)
    seeded_payment = _last_payment_for(admin_a["admin_id"])
    seeded_cashbook = get_last_cashbook_entry(admin_a["admin_id"])
    assert seeded_membership_id is not None
    assert seeded_payment is not None
    assert seeded_cashbook is not None

    client_b = app.test_client()
    admin_b = _register(client_b, "moneyb")
    student_id_b = _admit_and_pay(client_b, admin_b, "9200000002")

    new_membership_id = get_last_membership_id(student_id_b)
    new_payment = _last_payment_for(admin_b["admin_id"])
    new_cashbook = get_last_cashbook_entry(admin_b["admin_id"])

    assert new_membership_id is not None
    assert new_payment is not None
    assert new_cashbook is not None

    assert new_membership_id != seeded_membership_id
    assert new_payment["payment_id"] != seeded_payment["payment_id"]
    assert new_cashbook["entry_id"] != seeded_cashbook["entry_id"]

    assert get_membership_by_id(new_membership_id) is not None


def test_two_tenants_concurrent_membership_creation_get_distinct_ids(app):
    client_a = app.test_client()
    admin_a = _register(client_a, "moneyconca")
    client_b = app.test_client()
    admin_b = _register(client_b, "moneyconcb")

    student_id_a = _admit_and_pay(client_a, admin_a, "9200000011")
    student_id_b = _admit_and_pay(client_b, admin_b, "9200000012")

    membership_id_a = get_last_membership_id(student_id_a)
    membership_id_b = get_last_membership_id(student_id_b)
    payment_a = _last_payment_for(admin_a["admin_id"])
    payment_b = _last_payment_for(admin_b["admin_id"])
    cashbook_a = get_last_cashbook_entry(admin_a["admin_id"])
    cashbook_b = get_last_cashbook_entry(admin_b["admin_id"])

    assert membership_id_a != membership_id_b
    assert payment_a["payment_id"] != payment_b["payment_id"]
    assert cashbook_a["entry_id"] != cashbook_b["entry_id"]


def test_sequence_realignment_never_renumbers_existing_membership_payment_cashbook_row(app):
    """The sequence-realignment migration only reads MAX(id)/sequence state
    and calls setval() - pure sequence metadata, never row data. Proves an
    existing membership/payment/cashbook row's id and content survive
    subsequent inserts from other tenants untouched."""
    client_a = app.test_client()
    admin_a = _register(client_a, "moneystablea")
    student_id_a = _admit_and_pay(client_a, admin_a, "9200000021")

    before_membership = get_membership_by_id(get_last_membership_id(student_id_a))
    before_payment = _last_payment_for(admin_a["admin_id"])
    before_cashbook = get_cashbook_entry_by_id(get_last_cashbook_entry(admin_a["admin_id"])["entry_id"])

    for suffix, mobile_suffix in (("moneystableb", "22"), ("moneystablec", "23")):
        client = app.test_client()
        admin = _register(client, suffix)
        _admit_and_pay(client, admin, "92000000" + mobile_suffix)

    after_membership = get_membership_by_id(before_membership["membership_id"])
    after_payment_rows = (
        get_service_role_client()
        .table("payments")
        .select("*")
        .eq("payment_id", before_payment["payment_id"])
        .execute()
        .data
    )
    after_cashbook = get_cashbook_entry_by_id(before_cashbook["entry_id"])

    assert after_membership is not None
    assert after_membership["membership_id"] == before_membership["membership_id"]
    assert after_membership["total_fee"] == before_membership["total_fee"]

    assert after_payment_rows
    assert after_payment_rows[0]["payment_id"] == before_payment["payment_id"]
    assert after_payment_rows[0]["receipt_number"] == before_payment["receipt_number"]

    assert after_cashbook is not None
    assert after_cashbook["entry_id"] == before_cashbook["entry_id"]
    assert after_cashbook["amount"] == before_cashbook["amount"]
