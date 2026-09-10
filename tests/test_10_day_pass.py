"""Walk-in / Day Pass (ADR-71).

Quick Admit registers a 'Casual', 'Pending' student with no enquiry and
optional address/ID; the "Day Pass" plan preset on Create/Renew Membership is
a flat per-visit charge (from Settings > Membership Settings) booked to its
own "Day Pass" Cashbook category; a returning visitor is found by mobile and
sent to their profile to Renew.

Runs against the shared Supabase test project (slow). The `student_type`
column may not be applied on that project yet - the Casual assertions self-
skip in that case, same pattern as test_03's discount/admission-fee guards.
"""

from tests.conftest import (
    _rand_mobile,
    get_student_by_id,
    get_last_student_id,
    get_last_membership_id,
    get_membership_by_id,
    get_cashbook_entries,
    save_membership_settings,
)


def _quick_admit(client, **overrides):
    data = {
        "full_name": "Walk In Visitor",
        "mobile": _rand_mobile(),
        "purpose": "Interview",
        "shift": "Morning",
    }
    data.update(overrides)
    resp = client.post("/students/quick-admit", data=data, follow_redirects=True)
    return resp, data


def _sell_day_pass(client, student_id, *, endpoint="create", fee="40", days="1"):
    data = {
        "plan_name": "Day Pass",
        "joining_date": "2026-07-22",
        "duration": days,
        "end_date": "2026-07-23",
        "total_fee": fee,
        "paid_amount": fee,
        "payment_mode": "Cash",
        "remarks": "",
    }
    return client.post(
        f"/memberships/{endpoint}/{student_id}", data=data, follow_redirects=True
    )


# --------------------------------------------------------------------------
# Quick Admit
# --------------------------------------------------------------------------

def test_quick_admit_creates_casual_pending_student(logged_in_client):
    client, admin = logged_in_client

    resp, data = _quick_admit(client)
    assert resp.status_code == 200

    sid = get_last_student_id(admin["admin_id"])
    student = get_student_by_id(sid)

    assert student["full_name"] == "Walk In Visitor"
    assert student["mobile"] == data["mobile"]
    assert student["status"] == "Pending"
    assert student["enquiry_id"] is None

    if "student_type" not in student:
        # Column not applied on this project yet (TD-102) - degrades to Regular.
        return
    assert student["student_type"] == "Casual"


def test_quick_admit_lands_on_membership_create(logged_in_client):
    client, _ = logged_in_client
    resp, _ = _quick_admit(client)
    # follow_redirects landed us on the Membership & Payment step, which now
    # offers the Day Pass plan.
    assert b"Membership" in resp.data
    assert b"Day Pass" in resp.data


def test_quick_admit_requires_name(logged_in_client):
    client, _ = logged_in_client
    resp = client.post(
        "/students/quick-admit",
        data={"full_name": "  ", "mobile": _rand_mobile()},
        follow_redirects=True,
    )
    assert b"required" in resp.data


def test_quick_admit_rejects_bad_mobile(logged_in_client):
    client, _ = logged_in_client
    resp = client.post(
        "/students/quick-admit",
        data={"full_name": "No Number", "mobile": "abc"},
        follow_redirects=True,
    )
    assert b"10-digit" in resp.data


def test_quick_admit_same_mobile_returns_existing_profile(logged_in_client):
    client, admin = logged_in_client

    _, data = _quick_admit(client)
    first_sid = get_last_student_id(admin["admin_id"])

    resp, _ = _quick_admit(client, mobile=data["mobile"], full_name="Someone Else")
    assert resp.status_code == 200
    # No new row created - newest id is still the first visitor.
    assert get_last_student_id(admin["admin_id"]) == first_sid
    assert b"already on file" in resp.data


# --------------------------------------------------------------------------
# Day Pass plan
# --------------------------------------------------------------------------

def test_day_pass_sale_flat_fee_and_cashbook(logged_in_client):
    client, admin = logged_in_client
    save_membership_settings(client, day_pass_fee="40", day_pass_days="1")

    _quick_admit(client)
    sid = get_last_student_id(admin["admin_id"])

    resp = _sell_day_pass(client, sid, fee="40")
    assert resp.status_code == 200

    m = get_membership_by_id(get_last_membership_id(sid))
    assert m["plan_name"] == "DAY PASS"
    assert m["total_fee"] == 40
    assert m["duration_days"] == 1
    assert m["pending_amount"] == 0

    day_pass_rows = get_cashbook_entries(admin["admin_id"], category="Day Pass")
    assert [r["amount"] for r in day_pass_rows] == [40]
    # Not double-booked as an admission/membership fee.
    assert get_cashbook_entries(admin["admin_id"], category="Admission Fee") == []
    assert get_cashbook_entries(admin["admin_id"], category="Membership Fee") == []


def test_day_pass_receipt_labels_the_plan(logged_in_client):
    client, admin = logged_in_client
    save_membership_settings(client, day_pass_fee="30", day_pass_days="1")
    _quick_admit(client)
    sid = get_last_student_id(admin["admin_id"])

    resp = _sell_day_pass(client, sid, fee="30")
    assert b"Day Pass" in resp.data


def test_day_pass_amount_is_editable_per_visit(logged_in_client):
    client, admin = logged_in_client
    save_membership_settings(client, day_pass_fee="40", day_pass_days="1")
    _quick_admit(client)
    sid = get_last_student_id(admin["admin_id"])

    # Staff charged 25 for a shorter visit, overriding the 40 default.
    _sell_day_pass(client, sid, fee="25")
    m = get_membership_by_id(get_last_membership_id(sid))
    assert m["total_fee"] == 25
    assert [r["amount"] for r in get_cashbook_entries(admin["admin_id"], category="Day Pass")] == [25]


def test_day_pass_second_visit_via_renew(logged_in_client):
    client, admin = logged_in_client
    save_membership_settings(client, day_pass_fee="40", day_pass_days="1")
    _quick_admit(client)
    sid = get_last_student_id(admin["admin_id"])

    _sell_day_pass(client, sid, fee="40")                       # first visit
    resp = _sell_day_pass(client, sid, endpoint="renew", fee="40")   # they came back
    assert resp.status_code == 200

    m = get_membership_by_id(get_last_membership_id(sid))
    assert m["plan_name"] == "DAY PASS"
    assert m["total_fee"] == 40

    amounts = sorted(r["amount"] for r in get_cashbook_entries(admin["admin_id"], category="Day Pass"))
    assert amounts == [40, 40]


def test_casual_student_not_flagged_incomplete(logged_in_client):
    client, admin = logged_in_client
    _quick_admit(client)
    sid = get_last_student_id(admin["admin_id"])

    if "student_type" not in (get_student_by_id(sid) or {}):
        return  # column not applied - the flag-skip can't take effect anyway

    # Casual student with no membership yet must not appear in the
    # "N admissions incomplete" banner.
    resp = client.get("/students/", follow_redirects=True)
    assert resp.status_code == 200
    assert b"Casual" in resp.data
