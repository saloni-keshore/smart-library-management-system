"""Students/Admission -> Membership -> Payment: the core money workflow."""
import pytest

from database.supabase_client import get_supabase_client
from tests.conftest import (
    make_enquiry,
    get_last_enquiry_id,
    get_enquiry_by_id,
    admit_student,
    get_last_student_id,
    get_student_by_id,
    create_membership,
    get_last_membership_id,
    get_membership_by_id,
    save_membership_settings,
)


def _new_enquiry_and_admit(client, admin_id, **overrides):
    make_enquiry(client, **overrides)
    eid = get_last_enquiry_id(admin_id)
    admit_student(client, eid)
    sid = get_last_student_id(admin_id)
    return eid, sid


# ---------------------------------------------------------------------------
# Admission
# ---------------------------------------------------------------------------

def test_admission_requires_login(client):
    resp = client.get("/students/admission/1", follow_redirects=False)
    assert resp.status_code == 302


def test_admission_success_creates_student_and_sets_enquiry_admitted(logged_in_client):
    client, admin = logged_in_client
    make_enquiry(client)
    eid = get_last_enquiry_id(admin["admin_id"])
    resp = admit_student(client, eid)
    assert b"Student admitted successfully" in resp.data

    # enquiries.status now lives in Supabase (routes/enquiries.py reads it
    # from there); admission() writes the 'Admitted' flip there too (TD-36
    # resolved by this migration) instead of the SQLite mirror only.
    enquiry = get_enquiry_by_id(eid)
    assert enquiry["status"] == "Admitted"

    sid = get_last_student_id(admin["admin_id"])
    student = get_student_by_id(sid)
    assert student is not None
    assert student["enquiry_id"] == eid
    assert student["status"] == "Active"


def test_admission_nonexistent_enquiry(logged_in_client):
    client, admin = logged_in_client
    resp = client.get("/students/admission/999999999", follow_redirects=True)
    assert b"Enquiry not found" in resp.data


def test_admission_duplicate_mobile_blocked(logged_in_client):
    """Admitting the same mobile twice (same admin) must not create a
    second students row; UNIQUE(mobile, admin_id) is the DB-level guard."""
    client, admin = logged_in_client
    mobile = "9555511112"
    make_enquiry(client, mobile=mobile)
    eid1 = get_last_enquiry_id(admin["admin_id"])
    admit_student(client, eid1)
    sid1 = get_last_student_id(admin["admin_id"])

    make_enquiry(client, mobile=mobile)
    eid2 = get_last_enquiry_id(admin["admin_id"])
    resp = admit_student(client, eid2)
    assert b"already been admitted" in resp.data

    supabase = get_supabase_client()
    count = (
        supabase.table("students")
        .select("student_id", count="exact", head=True)
        .eq("mobile", mobile)
        .eq("admin_id", admin["admin_id"])
        .execute()
        .count
    )
    assert count == 1


def test_admission_empty_join_date(logged_in_client):
    client, admin = logged_in_client
    make_enquiry(client)
    eid = get_last_enquiry_id(admin["admin_id"])
    resp = admit_student(client, eid, join_date="")
    assert resp.status_code == 200


def test_admission_future_join_date(logged_in_client):
    client, admin = logged_in_client
    make_enquiry(client)
    eid = get_last_enquiry_id(admin["admin_id"])
    resp = admit_student(client, eid, join_date="2099-01-01")
    assert b"Student admitted successfully" in resp.data


def test_admission_unicode_address(logged_in_client):
    client, admin = logged_in_client
    make_enquiry(client)
    eid = get_last_enquiry_id(admin["admin_id"])
    resp = admit_student(client, eid, address="混合語 street 😀 #42")
    assert b"Student admitted successfully" in resp.data


# ---------------------------------------------------------------------------
# Student view/edit
# ---------------------------------------------------------------------------

def test_view_student_success(logged_in_client):
    client, admin = logged_in_client
    _, sid = _new_enquiry_and_admit(client, admin["admin_id"])
    resp = client.get(f"/students/view/{sid}")
    assert resp.status_code == 200


def test_view_student_nonexistent(logged_in_client):
    client, admin = logged_in_client
    resp = client.get("/students/view/999999999", follow_redirects=True)
    assert b"Student not found" in resp.data


def test_edit_student_success(logged_in_client):
    client, admin = logged_in_client
    _, sid = _new_enquiry_and_admit(client, admin["admin_id"])
    resp = client.post(
        f"/students/edit/{sid}",
        data={
            "full_name": "Renamed Student",
            "mobile": "9666677778",
            "address": "New Addr",
            "purpose": "Reading",
            "shift": "Evening",
            "status": "Active",
        },
        follow_redirects=True,
    )
    assert b"Student updated successfully" in resp.data


def test_edit_student_duplicate_mobile_crashes_or_handled(logged_in_client):
    """Edit sets mobile to a value already used by another student of the
    same admin -> violates UNIQUE(mobile, admin_id). No try/except exists
    around this UPDATE in routes/student.py. Verifying actual behavior."""
    client, admin = logged_in_client
    _, sid1 = _new_enquiry_and_admit(client, admin["admin_id"], mobile="9777788881")
    _, sid2 = _new_enquiry_and_admit(client, admin["admin_id"], mobile="9777788882")

    resp = client.post(
        f"/students/edit/{sid2}",
        data={
            "full_name": "Collider",
            "mobile": "9777788881",
            "address": "x",
            "purpose": "x",
            "shift": "Morning",
            "status": "Active",
        },
        follow_redirects=True,
    )
    # Document actual behavior for the report either way.
    assert resp.status_code in (200, 500)


def test_edit_student_empty_full_name(logged_in_client):
    client, admin = logged_in_client
    _, sid = _new_enquiry_and_admit(client, admin["admin_id"])
    resp = client.post(
        f"/students/edit/{sid}",
        data={"full_name": "", "mobile": "9888800001", "address": "x", "purpose": "x", "shift": "Morning", "status": "Active"},
        follow_redirects=True,
    )
    assert resp.status_code == 200


def test_edit_student_invalid_status_value_accepted(logged_in_client):
    """No server-side allowlist on `status` - any string is stored."""
    client, admin = logged_in_client
    _, sid = _new_enquiry_and_admit(client, admin["admin_id"])
    resp = client.post(
        f"/students/edit/{sid}",
        data={"full_name": "X", "mobile": "9888800002", "address": "x", "purpose": "x", "shift": "Morning", "status": "NotARealStatus"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    student = get_student_by_id(sid)
    assert student["status"] == "NotARealStatus"


# ---------------------------------------------------------------------------
# Membership create
# ---------------------------------------------------------------------------

def test_membership_create_success_with_payment(logged_in_client):
    client, admin = logged_in_client
    _, sid = _new_enquiry_and_admit(client, admin["admin_id"])
    resp = create_membership(client, sid, paid_amount="1000", due_amount="0")
    assert b"Membership created successfully" in resp.data
    assert b"Receipt No:" in resp.data

    mid = get_last_membership_id(sid)
    m = get_membership_by_id(mid)
    assert m["paid_amount"] == 1000
    assert m["pending_amount"] == 0
    assert m["total_fee"] == 1000

    supabase = get_supabase_client()
    payment_rows = supabase.table("payments").select("*").eq("membership_id", mid).execute().data
    assert len(payment_rows) == 1
    payment_id = payment_rows[0]["payment_id"]

    # cashbook.payment_id now round-trips through Supabase too (ADR-25,
    # closes TD-38's common case) - payments itself migrated to Supabase,
    # so cashbook's FK to it can resolve.
    cashbook_rows = supabase.table("cashbook").select("*").eq("payment_id", payment_id).execute().data
    assert len(cashbook_rows) == 1


def test_membership_create_with_partial_due(logged_in_client):
    client, admin = logged_in_client
    _, sid = _new_enquiry_and_admit(client, admin["admin_id"])
    resp = create_membership(client, sid, paid_amount="300", due_amount="700")
    assert b"Membership created successfully" in resp.data
    mid = get_last_membership_id(sid)
    row = get_membership_by_id(mid)
    assert row["paid_amount"] == 300
    assert row["pending_amount"] == 700
    assert row["total_fee"] == 1000


def test_membership_create_zero_paid_zero_due_rejected(logged_in_client):
    client, admin = logged_in_client
    _, sid = _new_enquiry_and_admit(client, admin["admin_id"])
    resp = create_membership(client, sid, paid_amount="0", due_amount="0")
    assert b"Total Payable must be greater than zero" in resp.data


def test_membership_create_negative_paid_rejected(logged_in_client):
    client, admin = logged_in_client
    _, sid = _new_enquiry_and_admit(client, admin["admin_id"])
    resp = create_membership(client, sid, paid_amount="-100", due_amount="0")
    assert b"cannot be negative" in resp.data


def test_membership_create_negative_total_fee_rejected(logged_in_client):
    """Custom plan is the only one with a client-supplied Total Payable
    (standard plans derive it server-side from membership_settings) -
    this is where a negative total can actually reach validation."""
    client, admin = logged_in_client
    _, sid = _new_enquiry_and_admit(client, admin["admin_id"])
    resp = create_membership(client, sid, paid_amount="0", total_fee="-50")
    assert b"cannot be negative" in resp.data


def test_membership_create_paid_exceeds_total_payable_rejected(logged_in_client):
    client, admin = logged_in_client
    _, sid = _new_enquiry_and_admit(client, admin["admin_id"])
    resp = create_membership(client, sid, paid_amount="150", total_fee="100")
    assert b"Paid cannot exceed Final Payable" in resp.data


def test_membership_create_non_numeric_amount_rejected(logged_in_client):
    client, admin = logged_in_client
    _, sid = _new_enquiry_and_admit(client, admin["admin_id"])
    resp = create_membership(client, sid, paid_amount="abc", due_amount="0")
    assert b"Invalid amount entered" in resp.data


def test_membership_create_empty_plan_name_rejected(logged_in_client):
    client, admin = logged_in_client
    _, sid = _new_enquiry_and_admit(client, admin["admin_id"])
    resp = create_membership(client, sid, plan_name="")
    assert b"Membership plan is required" in resp.data
    assert get_last_membership_id(sid) is None


def test_membership_create_empty_joining_date_rejected(logged_in_client):
    client, admin = logged_in_client
    _, sid = _new_enquiry_and_admit(client, admin["admin_id"])
    resp = create_membership(client, sid, joining_date="")
    assert b"Joining date is required" in resp.data
    assert get_last_membership_id(sid) is None


def test_membership_create_zero_pay_full_due_no_payment_row(logged_in_client):
    """paid_amount=0, due_amount>0 -> membership created, but no payment/
    receipt/cashbook row (paid_amount > 0 guard in membership.create)."""
    client, admin = logged_in_client
    _, sid = _new_enquiry_and_admit(client, admin["admin_id"])
    resp = create_membership(client, sid, paid_amount="0", due_amount="1000")
    assert b"Membership created successfully" in resp.data
    assert b"Receipt No:" not in resp.data
    mid = get_last_membership_id(sid)
    supabase = get_supabase_client()
    payment_rows = supabase.table("payments").select("payment_id").eq("membership_id", mid).execute().data
    assert len(payment_rows) == 0


def test_membership_create_for_nonexistent_student(logged_in_client):
    client, admin = logged_in_client
    resp = client.post(
        "/memberships/create/999999999",
        data={"plan_name": "Monthly", "joining_date": "2026-07-22", "duration": "30",
              "end_date": "2026-08-21", "remarks": "x", "payment_mode": "Cash",
              "paid_amount": "500", "due_amount": "0"},
        follow_redirects=True,
    )
    assert b"Student not found" in resp.data


def test_membership_create_second_time_blocked_use_renew(logged_in_client):
    client, admin = logged_in_client
    _, sid = _new_enquiry_and_admit(client, admin["admin_id"])
    create_membership(client, sid, paid_amount="500", due_amount="0")
    resp = create_membership(client, sid, paid_amount="500", due_amount="0")
    assert b"already has an active membership" in resp.data

    supabase = get_supabase_client()
    count = (
        supabase.table("memberships")
        .select("membership_id", count="exact", head=True)
        .eq("student_id", sid)
        .execute()
        .count
    )
    assert count == 1  # second attempt did NOT create a row


def test_membership_create_huge_amount(logged_in_client):
    client, admin = logged_in_client
    _, sid = _new_enquiry_and_admit(client, admin["admin_id"])
    resp = create_membership(client, sid, paid_amount="99999999999", due_amount="0")
    assert b"Membership created successfully" in resp.data


def test_membership_create_decimal_amount(logged_in_client):
    client, admin = logged_in_client
    _, sid = _new_enquiry_and_admit(client, admin["admin_id"])
    resp = create_membership(client, sid, paid_amount="499.99", due_amount="0.01")
    assert b"Membership created successfully" in resp.data
    mid = get_last_membership_id(sid)
    total = get_membership_by_id(mid)["total_fee"]
    assert abs(total - 500.00) < 0.001


def test_membership_create_standard_plan_total_fee_from_settings_plus_admission(logged_in_client):
    """Regression for the bug where Total Fee silently included the
    admission fee inside "Paid" instead of being derived from the
    admin-configured plan price: Total Payable for a standard plan must
    equal monthly_fee + admission_fee, and Pending must be the balance
    (never added into Total Payable)."""
    client, admin = logged_in_client
    save_membership_settings(client, monthly_fee="2400", admission_fee="400")
    _, sid = _new_enquiry_and_admit(client, admin["admin_id"])

    resp = create_membership(
        client, sid, plan_name="Monthly", paid_amount="2000", total_fee="ignored-for-standard-plans",
    )
    assert b"Membership created successfully" in resp.data

    mid = get_last_membership_id(sid)
    m = get_membership_by_id(mid)
    assert m["total_fee"] == 2800  # 2400 plan fee + 400 admission fee
    assert m["paid_amount"] == 2000
    assert m["pending_amount"] == 800  # balance, never folded into total_fee


def test_membership_create_custom_plan_total_fee_is_manual(logged_in_client):
    client, admin = logged_in_client
    save_membership_settings(client, monthly_fee="2400", admission_fee="400")
    _, sid = _new_enquiry_and_admit(client, admin["admin_id"])

    resp = create_membership(client, sid, plan_name="Custom", paid_amount="1000", total_fee="3000")
    assert b"Membership created successfully" in resp.data

    mid = get_last_membership_id(sid)
    m = get_membership_by_id(mid)
    assert m["total_fee"] == 3000
    assert m["pending_amount"] == 2000


def test_membership_create_discount_negative_rejected(logged_in_client):
    client, admin = logged_in_client
    _, sid = _new_enquiry_and_admit(client, admin["admin_id"])
    resp = create_membership(
        client, sid, paid_amount="0", total_fee="1000", discount_amount="-50"
    )
    assert b"Discount cannot be negative" in resp.data


def test_membership_create_discount_equal_to_total_rejected(logged_in_client):
    client, admin = logged_in_client
    _, sid = _new_enquiry_and_admit(client, admin["admin_id"])
    resp = create_membership(
        client, sid, paid_amount="0", total_fee="1000", discount_amount="1000"
    )
    assert b"Discount cannot be greater than or equal to Total Payable" in resp.data


def test_membership_create_discount_reduces_total_fee(logged_in_client):
    """ADR-46: Total Payable = Plan Fee + Admission Fee, Discount is a
    separate line item, Final Payable = Total Payable - Discount (stored as
    total_fee). Skips if this Supabase project hasn't had the
    discount_amount/discount_reason ALTER TABLE applied yet (see
    database/supabase_migration.sql) - same not-yet-migrated skip pattern
    tests/test_11_panda.py uses for its own new tables."""
    client, admin = logged_in_client
    save_membership_settings(client, monthly_fee="2400", admission_fee="400")
    _, sid = _new_enquiry_and_admit(client, admin["admin_id"])

    resp = create_membership(
        client, sid, plan_name="Monthly", paid_amount="2000",
        discount_amount="300", discount_reason="Referral discount",
    )

    if b"available yet on this system" in resp.data:
        pytest.skip(
            "memberships.discount_amount/discount_reason columns not yet "
            "added on this Supabase project"
        )

    assert b"Membership created successfully" in resp.data
    mid = get_last_membership_id(sid)
    m = get_membership_by_id(mid)
    assert m["total_fee"] == 2500  # 2400 + 400 - 300
    assert m["discount_amount"] == 300
    assert m["discount_reason"] == "Referral discount"
    assert m["paid_amount"] == 2000
    assert m["pending_amount"] == 500


def test_membership_create_discount_unavailable_fails_safely(logged_in_client):
    """When discount_amount/discount_reason don't exist yet on this
    Supabase project, a real discount must NOT silently vanish while the
    student is still charged the discounted price (ADR-46) - membership
    creation is blocked with a clear message instead, and nothing is saved."""
    client, admin = logged_in_client
    save_membership_settings(client, monthly_fee="2400", admission_fee="400")
    _, sid = _new_enquiry_and_admit(client, admin["admin_id"])

    resp = create_membership(
        client, sid, plan_name="Monthly", paid_amount="2000", discount_amount="300"
    )

    if b"Membership created successfully" in resp.data:
        pytest.skip(
            "memberships.discount_amount/discount_reason columns already "
            "exist on this Supabase project"
        )

    assert b"available yet on this system" in resp.data
    assert get_last_membership_id(sid) is None


# ---------------------------------------------------------------------------
# Membership renew
# ---------------------------------------------------------------------------

def test_renew_without_existing_membership_redirects_to_create(logged_in_client):
    client, admin = logged_in_client
    _, sid = _new_enquiry_and_admit(client, admin["admin_id"])
    resp = client.get(f"/memberships/renew/{sid}", follow_redirects=True)
    assert b"No existing membership found" in resp.data


def test_renew_success_expires_old_creates_new(logged_in_client):
    client, admin = logged_in_client
    _, sid = _new_enquiry_and_admit(client, admin["admin_id"])
    create_membership(client, sid, paid_amount="500", due_amount="0")
    old_mid = get_last_membership_id(sid)

    resp = client.post(
        f"/memberships/renew/{sid}",
        data={
            "plan_name": "Custom",
            "joining_date": "2026-08-22",
            "duration_days": "30",
            "end_date": "2026-09-21",
            "remarks": "renewal",
            "payment_mode": "UPI",
            "paid_amount": "500",
            "total_fee": "500",
        },
        follow_redirects=True,
    )
    assert b"Membership renewed successfully" in resp.data

    old_membership = get_membership_by_id(old_mid)
    assert old_membership["membership_status"] == "Expired"

    supabase = get_supabase_client()
    active_count = (
        supabase.table("memberships")
        .select("membership_id", count="exact", head=True)
        .eq("student_id", sid)
        .eq("membership_status", "Active")
        .execute()
        .count
    )
    assert active_count == 1


def test_renew_zero_total_fee_rejected(logged_in_client):
    client, admin = logged_in_client
    _, sid = _new_enquiry_and_admit(client, admin["admin_id"])
    create_membership(client, sid, paid_amount="500", due_amount="0")
    resp = client.post(
        f"/memberships/renew/{sid}",
        data={"plan_name": "Custom", "joining_date": "2026-08-22", "duration_days": "30",
              "end_date": "2026-09-21", "remarks": "x", "payment_mode": "Cash",
              "paid_amount": "0", "total_fee": "0"},
        follow_redirects=True,
    )
    assert b"Total Payable must be greater than zero" in resp.data


def test_renew_for_nonexistent_student(logged_in_client):
    client, admin = logged_in_client
    resp = client.get("/memberships/renew/999999999", follow_redirects=True)
    assert b"Student not found" in resp.data


def test_renew_standard_plan_total_fee_excludes_admission_fee(logged_in_client):
    """Regression: admission fee is a one-time new-admission charge only
    (routes/membership.py's create()) - a renewal's Total Payable must be
    the configured plan price alone, unlike Create's."""
    client, admin = logged_in_client
    save_membership_settings(client, monthly_fee="2400", admission_fee="400")
    _, sid = _new_enquiry_and_admit(client, admin["admin_id"])
    create_membership(client, sid, plan_name="Monthly", paid_amount="2800")

    resp = client.post(
        f"/memberships/renew/{sid}",
        data={
            "plan_name": "Monthly", "joining_date": "2026-08-22", "duration_days": "30",
            "end_date": "2026-09-21", "remarks": "renewal", "payment_mode": "Cash",
            "paid_amount": "2000",
        },
        follow_redirects=True,
    )
    assert b"Membership renewed successfully" in resp.data

    mid = get_last_membership_id(sid)
    m = get_membership_by_id(mid)
    assert m["total_fee"] == 2400  # plan fee only, no admission fee
    assert m["paid_amount"] == 2000
    assert m["pending_amount"] == 400


# ---------------------------------------------------------------------------
# Payment collect (pending balance)
# ---------------------------------------------------------------------------

def test_collect_payment_success(logged_in_client):
    client, admin = logged_in_client
    _, sid = _new_enquiry_and_admit(client, admin["admin_id"])
    create_membership(client, sid, paid_amount="200", due_amount="800")
    mid = get_last_membership_id(sid)

    resp = client.post(
        f"/payments/collect/{mid}",
        data={"amount_paid": "300", "payment_mode": "UPI", "remarks": "partial"},
        follow_redirects=True,
    )
    assert b"collected successfully" in resp.data

    # memberships now lives in Supabase only (ADR-29) - the source of truth
    # routes/membership.py's index() reads.
    m = get_membership_by_id(mid)
    assert m["paid_amount"] == 500
    assert m["pending_amount"] == 500


def test_collect_payment_exceeding_pending_rejected(logged_in_client):
    client, admin = logged_in_client
    _, sid = _new_enquiry_and_admit(client, admin["admin_id"])
    create_membership(client, sid, paid_amount="200", due_amount="800")
    mid = get_last_membership_id(sid)

    resp = client.post(
        f"/payments/collect/{mid}",
        data={"amount_paid": "801", "payment_mode": "Cash", "remarks": "x"},
        follow_redirects=True,
    )
    assert b"cannot exceed pending balance" in resp.data


def test_collect_payment_exact_pending_clears_balance(logged_in_client):
    client, admin = logged_in_client
    _, sid = _new_enquiry_and_admit(client, admin["admin_id"])
    create_membership(client, sid, paid_amount="200", due_amount="800")
    mid = get_last_membership_id(sid)

    resp = client.post(
        f"/payments/collect/{mid}",
        data={"amount_paid": "800", "payment_mode": "Cash", "remarks": "final"},
        follow_redirects=True,
    )
    assert b"collected successfully" in resp.data

    assert get_membership_by_id(mid)["pending_amount"] == 0


def test_collect_payment_reflected_on_memberships_index_page(logged_in_client):
    """TD-37 regression: before this migration, routes/membership.py's
    index() (Supabase-read) kept showing the pre-payment balance after a
    payment was collected, because collect() only updated the SQLite
    mirror. The "Collect" action only renders while pending_amount > 0
    (templates/memberships/index.html), so its disappearance after a
    full payment proves the page is reading the post-payment balance."""
    client, admin = logged_in_client
    _, sid = _new_enquiry_and_admit(client, admin["admin_id"])
    create_membership(client, sid, paid_amount="200", due_amount="800")
    mid = get_last_membership_id(sid)

    collect_url = f"/payments/collect/{mid}"
    resp = client.get("/memberships/")
    assert collect_url.encode() in resp.data

    client.post(
        collect_url,
        data={"amount_paid": "800", "payment_mode": "Cash", "remarks": "final"},
        follow_redirects=True,
    )

    resp = client.get("/memberships/")
    assert resp.status_code == 200
    assert collect_url.encode() not in resp.data


def test_collect_payment_zero_amount_rejected(logged_in_client):
    client, admin = logged_in_client
    _, sid = _new_enquiry_and_admit(client, admin["admin_id"])
    create_membership(client, sid, paid_amount="200", due_amount="800")
    mid = get_last_membership_id(sid)
    resp = client.post(f"/payments/collect/{mid}", data={"amount_paid": "0", "payment_mode": "Cash"}, follow_redirects=True)
    assert b"must be greater than zero" in resp.data


def test_collect_payment_negative_amount_rejected(logged_in_client):
    client, admin = logged_in_client
    _, sid = _new_enquiry_and_admit(client, admin["admin_id"])
    create_membership(client, sid, paid_amount="200", due_amount="800")
    mid = get_last_membership_id(sid)
    resp = client.post(f"/payments/collect/{mid}", data={"amount_paid": "-50", "payment_mode": "Cash"}, follow_redirects=True)
    assert b"must be greater than zero" in resp.data


def test_collect_payment_non_numeric_amount_rejected(logged_in_client):
    client, admin = logged_in_client
    _, sid = _new_enquiry_and_admit(client, admin["admin_id"])
    create_membership(client, sid, paid_amount="200", due_amount="800")
    mid = get_last_membership_id(sid)
    resp = client.post(f"/payments/collect/{mid}", data={"amount_paid": "abc", "payment_mode": "Cash"}, follow_redirects=True)
    assert b"Invalid amount entered" in resp.data


def test_collect_payment_on_fully_paid_membership_rejected(logged_in_client):
    client, admin = logged_in_client
    _, sid = _new_enquiry_and_admit(client, admin["admin_id"])
    create_membership(client, sid, paid_amount="1000", due_amount="0")
    mid = get_last_membership_id(sid)
    resp = client.post(f"/payments/collect/{mid}", data={"amount_paid": "100", "payment_mode": "Cash"}, follow_redirects=True)
    assert b"no pending balance" in resp.data


def test_collect_payment_nonexistent_membership(logged_in_client):
    client, admin = logged_in_client
    resp = client.post("/payments/collect/999999999", data={"amount_paid": "100", "payment_mode": "Cash"}, follow_redirects=True)
    assert b"Membership not found" in resp.data


def test_receipt_numbers_are_unique_across_multiple_payments(logged_in_client):
    client, admin = logged_in_client
    _, sid = _new_enquiry_and_admit(client, admin["admin_id"])
    create_membership(client, sid, paid_amount="100", due_amount="900")
    mid = get_last_membership_id(sid)
    for amt in ("100", "100", "100"):
        client.post(f"/payments/collect/{mid}", data={"amount_paid": amt, "payment_mode": "Cash"}, follow_redirects=True)

    supabase = get_supabase_client()
    rows = supabase.table("payments").select("receipt_number").eq("membership_id", mid).execute().data
    receipts = [r["receipt_number"] for r in rows]
    assert len(receipts) == len(set(receipts))
    assert len(receipts) == 4  # 1 from create + 3 collects


def test_double_submit_membership_create_creates_two_active_rows_race():
    """TD-30 (documented): no idempotency guard. This test documents the
    mechanism rather than re-litigating already-known debt: two rapid
    creates before any 'active membership' guard sees the first commit
    would both succeed. Skipped as a live concurrency test (needs threads);
    kept as a marker referencing the known issue."""
    import pytest as _pytest
    _pytest.skip("TD-30 already documented; concurrency repro out of scope for this pass")
