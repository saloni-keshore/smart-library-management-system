"""Bug 1 regression (ADR-79, TD-78/TD-108): deterministic global-ID
collision under RLS.

`database/id_sequence.py`'s `insert_with_next_id()` used to compute
`MAX(id) + 1` through the app's tenant-scoped, Row-Level-Security-filtered
Supabase client. `enquiries.enquiry_id` / `students.student_id` /
`shift_slots.slot_id` are each a single GLOBAL identity primary key shared
by every tenant, not a per-tenant sequence - so a brand-new tenant's
RLS-filtered view was always empty, making that computed `next_id`
deterministically `1` and guaranteed to collide with any other tenant's
existing global row. These tests prove a brand-new tenant can create its
first record regardless of what ids other tenants already hold, that two
tenants never collide, and that the fix never renumbers an existing row.
"""
import pytest

from database.supabase_client import get_service_role_client
from tests.conftest import (
    make_enquiry,
    get_last_enquiry_id,
    get_enquiry_by_id,
    admit_student,
    get_last_student_id,
    get_student_by_id,
)

_SHIFT_SLOT_UNAVAILABLE = b"Shift slots aren't available yet on this system"


def _seed_enquiry(admin_id, mobile):
    """Insert an enquiry row directly via the service-role client (bypasses
    RLS), letting the identity column assign its own id - the same
    mechanism the fixed insert_with_next_id() now relies on. Returns the
    assigned enquiry_id."""
    response = (
        get_service_role_client()
        .table("enquiries")
        .insert({
            "admin_id": admin_id,
            "full_name": "Seed Tenant",
            "mobile": mobile,
            "purpose": "Study",
            "preferred_shift": "Morning",
        })
        .execute()
    )
    return response.data[0]["enquiry_id"]


def test_new_tenant_enquiry_succeeds_when_other_tenant_owns_a_global_id(app):
    """Core regression: tenant A already holds a global enquiry_id before
    brand-new tenant B (zero rows of its own) ever inserts. Pre-fix, B's
    RLS-filtered MAX was always empty, so B's computed next_id was always 1
    - not a race, a guaranteed collision on B's very first insert whenever
    any tenant anywhere already owned that id."""
    client_a = app.test_client()
    resp_a, admin_a = _register(client_a, "seqa")
    seeded_id = _seed_enquiry(admin_a["admin_id"], "9100000001")
    assert seeded_id is not None

    client_b = app.test_client()
    resp_b, admin_b = _register(client_b, "seqb")

    add_resp, _ = make_enquiry(client_b, mobile="9100000002")
    assert add_resp.status_code == 200
    assert b"Enquiry added successfully" in add_resp.data

    new_id = get_last_enquiry_id(admin_b["admin_id"])
    assert new_id is not None
    assert new_id != seeded_id
    assert get_enquiry_by_id(new_id) is not None


def test_new_tenant_student_and_shift_slot_succeed(app):
    """Same shape as the enquiry case, for admission() (students.student_id)
    and Shift Slots (shift_slots.slot_id) - the other two tables that share
    insert_with_next_id()."""
    client_a = app.test_client()
    _, admin_a = _register(client_a, "seqstua")
    other_enquiry_resp, other_data = make_enquiry(client_a, mobile="9100000011")
    assert other_enquiry_resp.status_code == 200
    other_enquiry_id = get_last_enquiry_id(admin_a["admin_id"])
    admit_resp = admit_student(client_a, other_enquiry_id)
    assert admit_resp.status_code == 200

    client_b = app.test_client()
    _, admin_b = _register(client_b, "seqstub")
    enquiry_resp, _ = make_enquiry(client_b, mobile="9100000012")
    assert enquiry_resp.status_code == 200
    enquiry_id_b = get_last_enquiry_id(admin_b["admin_id"])

    admit_resp_b = admit_student(client_b, enquiry_id_b)
    assert admit_resp_b.status_code == 200
    assert b"admitted successfully" in admit_resp_b.data.lower()
    new_student_id = get_last_student_id(admin_b["admin_id"])
    assert new_student_id is not None
    assert get_student_by_id(new_student_id) is not None

    slot_resp = client_b.post(
        "/settings/shift-slots",
        data={"name": f"QA Slot {admin_b['username']}"},
        follow_redirects=True,
    )
    assert slot_resp.status_code == 200
    if _SHIFT_SLOT_UNAVAILABLE in slot_resp.data:
        pytest.skip("shift_slots table not yet created on this Supabase project")
    assert b"added" in slot_resp.data.lower()


def test_two_tenants_concurrent_inserts_get_distinct_ids(app):
    client_a = app.test_client()
    _, admin_a = _register(client_a, "seqconca")
    client_b = app.test_client()
    _, admin_b = _register(client_b, "seqconcb")

    resp_a, _ = make_enquiry(client_a, mobile="9100000021")
    resp_b, _ = make_enquiry(client_b, mobile="9100000022")
    assert resp_a.status_code == 200
    assert resp_b.status_code == 200

    id_a = get_last_enquiry_id(admin_a["admin_id"])
    id_b = get_last_enquiry_id(admin_b["admin_id"])
    assert id_a is not None
    assert id_b is not None
    assert id_a != id_b


def test_sequence_realignment_never_renumbers_existing_row(app):
    """The sequence-realignment migration only reads MAX(id)/sequence state
    and calls setval() - pure sequence metadata, never row data. Proves an
    existing row's id and content survive several subsequent inserts from
    other tenants untouched."""
    client_a = app.test_client()
    _, admin_a = _register(client_a, "seqstablea")
    seeded_id = _seed_enquiry(admin_a["admin_id"], "9100000031")
    before = get_enquiry_by_id(seeded_id)
    assert before is not None

    for suffix in ("seqstableb", "seqstablec"):
        client = app.test_client()
        _, admin = _register(client, suffix)
        resp, _ = make_enquiry(client, mobile=f"91000000{suffix[-2:]}")
        assert resp.status_code == 200

    after = get_enquiry_by_id(seeded_id)
    assert after is not None
    assert after["enquiry_id"] == before["enquiry_id"]
    assert after["full_name"] == before["full_name"]
    assert after["mobile"] == before["mobile"]


# --- local helper (avoids relying on the shared `new_admin` fixture's
# module-scoped randomness colliding across the several fresh tenants each
# test in this file needs) --------------------------------------------------

def _register(client, label):
    import random
    import string

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

    from tests.conftest import get_admin_by_username
    admin = get_admin_by_username(creds["username"])
    assert admin is not None, "registration did not create an admin row"
    creds["admin_id"] = admin["admin_id"]

    login_resp = client.post(
        "/",
        data={"username": creds["username"], "password": creds["password"]},
        follow_redirects=True,
    )
    assert login_resp.status_code == 200
    return login_resp, creds
