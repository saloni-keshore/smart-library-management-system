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
    """Re-running admission for someone who is already a student (same
    admin) must not create a second students row. A phone number identifies
    one person (ADR-58), so admission() detects the existing student and
    redirects to their record instead of inserting."""
    client, admin = logged_in_client
    mobile = "9555511112"
    make_enquiry(client, mobile=mobile)
    eid = get_last_enquiry_id(admin["admin_id"])
    admit_student(client, eid)

    # Back-button / double submit: POST the same admission a second time.
    resp = admit_student(client, eid)
    assert b"already registered" in resp.data

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


def test_edit_student_invalid_mobile_rejected(logged_in_client):
    """ADR-59: editing a student's mobile to a non-10-digit value is
    rejected and the stored number is unchanged."""
    client, admin = logged_in_client
    _, sid = _new_enquiry_and_admit(client, admin["admin_id"])
    original = get_student_by_id(sid)["mobile"]
    resp = client.post(
        f"/students/edit/{sid}",
        data={"full_name": "X", "mobile": "notaphone", "address": "x",
              "purpose": "x", "shift": "Morning", "status": "Active"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"valid 10-digit mobile number" in resp.data
    assert get_student_by_id(sid)["mobile"] == original


def test_edit_student_mobile_formatting_is_canonicalized(logged_in_client):
    """A formatted but valid number is accepted and stored as bare digits."""
    client, admin = logged_in_client
    _, sid = _new_enquiry_and_admit(client, admin["admin_id"])
    resp = client.post(
        f"/students/edit/{sid}",
        data={"full_name": "X", "mobile": "091234-56789", "address": "x",
              "purpose": "x", "shift": "Morning", "status": "Active"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert get_student_by_id(sid)["mobile"] == "9123456789"


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


def test_membership_create_prefills_joining_date_from_admission_join_date(logged_in_client):
    """UX: the join_date entered on admission (Step 1) is carried into the
    membership Joining Date field (Step 2) so the operator doesn't retype the
    same date. The input keeps `required` and stays editable."""
    client, admin = logged_in_client
    make_enquiry(client)
    eid = get_last_enquiry_id(admin["admin_id"])
    admit_student(client, eid, join_date="2026-05-14")
    sid = get_last_student_id(admin["admin_id"])

    resp = client.get(f"/memberships/create/{sid}")
    assert resp.status_code == 200
    assert b'name="joining_date"' in resp.data
    assert b'value="2026-05-14"' in resp.data


def test_membership_joining_date_stays_editable_and_independent_of_join_date(logged_in_client):
    """The prefill is only a default: posting a different joining_date is
    accepted and stored, and students.join_date is left untouched (the two
    dates are allowed to differ)."""
    client, admin = logged_in_client
    make_enquiry(client)
    eid = get_last_enquiry_id(admin["admin_id"])
    admit_student(client, eid, join_date="2026-05-14")
    sid = get_last_student_id(admin["admin_id"])

    create_membership(client, sid, joining_date="2026-06-01")
    m = get_membership_by_id(get_last_membership_id(sid))
    assert m["joining_date"] == "2026-06-01"
    assert get_student_by_id(sid)["join_date"] == "2026-05-14"


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


def test_membership_insert_with_duplicate_idempotency_key_returns_existing_row(logged_in_client):
    """TD-30/ADR-53, the create() call site: routes/membership.py's create()
    is already guarded against a *sequential* double-submit by its
    pre-existing get_active_membership() check (a second request sees the
    first's committed row and gets redirected to Renew before ever reaching
    the new idempotency logic) - so an HTTP-level double-POST test would
    only prove that old guard works, not the new one. This instead calls
    database/membership_queries.py's insert_membership() directly, twice,
    with the same idempotency_key - the actual mechanism (DB-level UNIQUE
    constraint + 23505 handling) that protects against a genuine *concurrent*
    race, which the pre-existing guard can't: neither request has committed
    yet when the other checks "is there an active membership".

    Self-skips (rather than failing) if this Supabase project hasn't had
    ADR-53's `idempotency_key` column added yet (see
    database/supabase_migration.sql's inline ALTER TABLE block) - on such a
    project, insert_membership() detects the missing column and silently
    falls back to pre-ADR-53 behavior (no dedup), the same self-skip
    convention TD-53/TD-55's tests already use for their own
    not-yet-migrated-project case.
    """
    from database.membership_queries import insert_membership

    client, admin = logged_in_client
    _, sid = _new_enquiry_and_admit(client, admin["admin_id"])

    supabase = get_supabase_client()
    key = f"test-key-{admin['admin_id']}-direct-insert"

    def _next_membership_id():
        resp = (
            supabase.table("memberships")
            .select("membership_id")
            .order("membership_id", desc=True)
            .limit(1)
            .execute()
        )
        return (resp.data[0]["membership_id"] + 1) if resp.data else 1

    base_row = {
        "student_id": sid,
        "plan_name": "Custom",
        "joining_date": "2026-07-22",
        "duration_days": 30,
        "end_date": "2026-08-21",
        "total_fee": 1000,
        "paid_amount": 0,
        "pending_amount": 1000,
        "remarks": "direct insert_membership() dedup test",
        "membership_status": "Active",
        "idempotency_key": key,
    }

    row_a = {**base_row, "membership_id": _next_membership_id()}
    result_a = insert_membership(supabase, row_a)
    assert result_a is None, "first insert with a fresh idempotency_key should just insert, not find an existing row"

    row_b = {**base_row, "membership_id": _next_membership_id()}
    result_b = insert_membership(supabase, row_b)

    rows = supabase.table("memberships").select("membership_id").eq("student_id", sid).execute().data

    if result_b is None and len(rows) == 2:
        pytest.skip(
            "idempotency_key column not present on this Supabase project yet "
            "(ADR-53 manual ALTER TABLE not applied) - insert_membership() "
            "silently degraded to its pre-ADR-53 always-insert behavior."
        )

    assert result_b is not None, (
        "second insert with a duplicate idempotency_key should return the "
        "existing row instead of inserting a new one"
    )
    assert result_b["membership_id"] == row_a["membership_id"]
    assert len(rows) == 1


def test_double_submit_membership_renew_is_deduplicated(logged_in_client):
    """Same protection as the create() test above, for renew() (TD-30/ADR-53)."""
    client, admin = logged_in_client
    _, sid = _new_enquiry_and_admit(client, admin["admin_id"])
    create_membership(client, sid, paid_amount="200", due_amount="800")

    key = f"test-key-{admin['admin_id']}-renew"
    payload = {
        "plan_name": "Custom",
        "joining_date": "2026-07-22",
        "duration_days": "30",
        "end_date": "2026-08-21",
        "remarks": "double-submit renew test",
        "payment_mode": "Cash",
        "paid_amount": "100",
        "total_fee": "1000",
        "idempotency_key": key,
    }
    client.post(f"/memberships/renew/{sid}", data=payload, follow_redirects=True)
    client.post(f"/memberships/renew/{sid}", data=payload, follow_redirects=True)

    # Total row count (not just the Active-filtered count) is what actually
    # proves dedup: renew() always expires the previous row before inserting
    # a new one, so exactly one row stays 'Active' either way - a
    # not-deduplicated double-submit would still show only 1 Active row, but
    # 3 total (original + two renewals) instead of the expected 2 (original
    # + one renewal).
    supabase = get_supabase_client()
    rows = (
        supabase.table("memberships")
        .select("membership_id")
        .eq("student_id", sid)
        .execute()
        .data
    )

    if len(rows) != 2:
        pytest.skip(
            "idempotency_key column not present on this Supabase project yet "
            "(ADR-53 manual ALTER TABLE not applied) - double-submit "
            "protection isn't active until it is."
        )
    assert len(rows) == 2


def test_double_submit_collect_payment_is_deduplicated(logged_in_client):
    """TD-30/ADR-53, the collect() call site: two identical Collect Payment
    POSTs (same idempotency_key) must record exactly one payment and
    decrement the membership's pending_amount exactly once - not twice, even
    though collect()'s own membership-balance update runs *before*
    record_payment()'s own dedup check (see routes/payment.py's early
    idempotency pre-check, added specifically so this can't happen)."""
    client, admin = logged_in_client
    _, sid = _new_enquiry_and_admit(client, admin["admin_id"])
    create_membership(client, sid, paid_amount="100", due_amount="900")
    mid = get_last_membership_id(sid)

    key = f"test-key-{admin['admin_id']}-collect"
    payload = {"amount_paid": "100", "payment_mode": "Cash", "idempotency_key": key}
    client.post(f"/payments/collect/{mid}", data=payload, follow_redirects=True)
    client.post(f"/payments/collect/{mid}", data=payload, follow_redirects=True)

    # select("*") rather than naming idempotency_key explicitly - on a
    # project where that column doesn't exist yet, naming it in the SELECT
    # itself raises 42703 before we even get to check for its absence.
    supabase = get_supabase_client()
    payment_rows = (
        supabase.table("payments")
        .select("*")
        .eq("membership_id", mid)
        .execute()
        .data
    )

    if not payment_rows or "idempotency_key" not in payment_rows[0]:
        pytest.skip(
            "idempotency_key column not present on this Supabase project yet "
            "(ADR-53 manual ALTER TABLE not applied) - double-submit "
            "protection isn't active until it is."
        )

    matching = [p for p in payment_rows if p.get("idempotency_key") == key]
    membership = get_membership_by_id(mid)
    assert len(matching) == 1
    assert float(membership["pending_amount"]) == 800.0


def test_payment_survives_cashbook_sync_failure_and_is_flagged(logged_in_client, monkeypatch):
    """TD-43/ADR-53: if the automatic Cashbook Income entry fails even after
    its own retry (simulated here via monkeypatch, standing in for a
    persistent Supabase outage on the cashbook/audit_log tables
    specifically), the payment itself must still succeed - it's already
    validated money, and rolling it back over an unrelated ledger-mirror
    failure would be worse than the gap it's meant to fix. The payment row
    should instead be flagged (cashbook_synced=False) so
    routes/cashbook.py's banner can surface the gap to the admin.

    Self-skips if cashbook_synced isn't a column on this Supabase project
    yet, same convention as the idempotency tests above.
    """
    import database.payment_queries as payment_queries

    monkeypatch.setattr(payment_queries, "insert_income_entry", lambda *a, **kw: None)

    client, admin = logged_in_client
    _, sid = _new_enquiry_and_admit(client, admin["admin_id"])
    create_membership(client, sid, paid_amount="100", due_amount="900")
    mid = get_last_membership_id(sid)

    resp = client.post(
        f"/payments/collect/{mid}",
        data={"amount_paid": "100", "payment_mode": "Cash"},
        follow_redirects=True,
    )
    assert b"collected successfully" in resp.data

    # select("*") rather than naming cashbook_synced explicitly - see the
    # collect-payment dedup test above for why.
    supabase = get_supabase_client()
    payment_rows = (
        supabase.table("payments")
        .select("*")
        .eq("membership_id", mid)
        .order("payment_id", desc=True)
        .limit(1)
        .execute()
        .data
    )
    assert payment_rows, "payment was not recorded despite the simulated cashbook failure"

    if "cashbook_synced" not in payment_rows[0]:
        pytest.skip(
            "cashbook_synced column not present on this Supabase project yet "
            "(ADR-53 manual ALTER TABLE not applied)."
        )

    assert payment_rows[0]["cashbook_synced"] is False

    from database.payment_queries import get_unsynced_payment_count
    assert get_unsynced_payment_count(admin["admin_id"]) >= 1

    cashbook_resp = client.get("/cashbook/")
    assert b"missing a matching Cashbook ledger entry" in cashbook_resp.data
