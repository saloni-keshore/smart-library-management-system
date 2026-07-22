"""Cross-tenant isolation (IDOR): Admin B must never see or modify Admin A's
records by guessing/incrementing IDs, across every admin-scoped resource."""
import random
import string

from database.db import get_connection
from tests.conftest import (
    make_enquiry, get_last_enquiry_id, admit_student, get_last_student_id,
    create_membership, get_last_membership_id,
)


def _register_and_login(client, suffix):
    creds = {
        "full_name": f"Tenant {suffix}",
        "username": f"qa_tenant_{suffix}",
        "mobile": "9" + "".join(random.choices(string.digits, k=9)),
        "email": f"tenant_{suffix}@example.com",
        "password": "TenantPass1",
        "confirm_password": "TenantPass1",
    }
    client.post("/register", data=creds, follow_redirects=True)
    client.post("/", data={"username": creds["username"], "password": creds["password"]}, follow_redirects=True)

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT admin_id FROM admins WHERE username=?", (creds["username"],))
    creds["admin_id"] = cur.fetchone()["admin_id"]
    conn.close()
    return creds


def _full_pipeline(client, admin_id, mobile_suffix):
    make_enquiry(client, mobile="9" + mobile_suffix)
    eid = get_last_enquiry_id(admin_id)
    admit_student(client, eid)
    sid = get_last_student_id(admin_id)
    create_membership(client, sid, paid_amount="500", due_amount="500")
    mid = get_last_membership_id(sid)
    return eid, sid, mid


def test_admin_b_cannot_view_admin_a_enquiry(app):
    client_a = app.test_client()
    client_b = app.test_client()
    a = _register_and_login(client_a, "iso_enq_a")
    b = _register_and_login(client_b, "iso_enq_b")

    make_enquiry(client_a, full_name="Secret A Enquiry")
    eid_a = get_last_enquiry_id(a["admin_id"])

    resp = client_b.get(f"/enquiries/view/{eid_a}", follow_redirects=True)
    assert b"Enquiry not found" in resp.data
    assert b"Secret A Enquiry" not in resp.data


def test_admin_b_cannot_edit_admin_a_enquiry(app):
    client_a = app.test_client()
    client_b = app.test_client()
    a = _register_and_login(client_a, "iso_enqedit_a")
    b = _register_and_login(client_b, "iso_enqedit_b")

    make_enquiry(client_a, full_name="Original Name A")
    eid_a = get_last_enquiry_id(a["admin_id"])

    client_b.post(
        f"/enquiries/edit/{eid_a}",
        data={"full_name": "HACKED BY B", "mobile": "9000000000", "purpose": "x",
              "preferred_shift": "Morning", "followup_date": "2026-08-01", "remarks": "x"},
        follow_redirects=True,
    )
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT full_name FROM enquiries WHERE enquiry_id=?", (eid_a,))
    assert cur.fetchone()["full_name"] == "Original Name A"
    conn.close()


def test_admin_b_cannot_delete_admin_a_enquiry(app):
    client_a = app.test_client()
    client_b = app.test_client()
    a = _register_and_login(client_a, "iso_enqdel_a")
    b = _register_and_login(client_b, "iso_enqdel_b")

    make_enquiry(client_a)
    eid_a = get_last_enquiry_id(a["admin_id"])

    client_b.get(f"/enquiries/delete/{eid_a}", follow_redirects=True)
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM enquiries WHERE enquiry_id=?", (eid_a,))
    assert cur.fetchone() is not None  # NOT deleted by B
    conn.close()


def test_admin_b_cannot_view_admin_a_student(app):
    client_a = app.test_client()
    client_b = app.test_client()
    a = _register_and_login(client_a, "iso_stu_a")
    b = _register_and_login(client_b, "iso_stu_b")

    eid_a, sid_a, mid_a = _full_pipeline(client_a, a["admin_id"], "111000001")

    resp = client_b.get(f"/students/view/{sid_a}", follow_redirects=True)
    assert b"Student not found" in resp.data


def test_admin_b_cannot_edit_admin_a_student(app):
    client_a = app.test_client()
    client_b = app.test_client()
    a = _register_and_login(client_a, "iso_stuedit_a")
    b = _register_and_login(client_b, "iso_stuedit_b")

    eid_a, sid_a, mid_a = _full_pipeline(client_a, a["admin_id"], "111000002")

    client_b.post(
        f"/students/edit/{sid_a}",
        data={"full_name": "HACKED", "mobile": "9111222333", "address": "x",
              "purpose": "x", "shift": "Morning", "status": "Active"},
        follow_redirects=True,
    )
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT full_name FROM students WHERE student_id=?", (sid_a,))
    assert cur.fetchone()["full_name"] != "HACKED"
    conn.close()


def test_admin_b_cannot_admit_against_admin_a_enquiry(app):
    client_a = app.test_client()
    client_b = app.test_client()
    a = _register_and_login(client_a, "iso_admit_a")
    b = _register_and_login(client_b, "iso_admit_b")

    make_enquiry(client_a)
    eid_a = get_last_enquiry_id(a["admin_id"])

    resp = client_b.get(f"/students/admission/{eid_a}", follow_redirects=True)
    assert b"Enquiry not found" in resp.data


def test_admin_b_cannot_create_membership_for_admin_a_student(app):
    client_a = app.test_client()
    client_b = app.test_client()
    a = _register_and_login(client_a, "iso_mcreate_a")
    b = _register_and_login(client_b, "iso_mcreate_b")

    make_enquiry(client_a)
    eid_a = get_last_enquiry_id(a["admin_id"])
    admit_student(client_a, eid_a)
    sid_a = get_last_student_id(a["admin_id"])

    resp = client_b.post(
        f"/memberships/create/{sid_a}",
        data={"plan_name": "Monthly", "joining_date": "2026-07-22", "duration": "30",
              "end_date": "2026-08-21", "remarks": "x", "payment_mode": "Cash",
              "paid_amount": "500", "due_amount": "0"},
        follow_redirects=True,
    )
    assert b"Student not found" in resp.data
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM memberships WHERE student_id=?", (sid_a,))
    assert cur.fetchone()["c"] == 0
    conn.close()


def test_admin_b_cannot_renew_admin_a_membership(app):
    client_a = app.test_client()
    client_b = app.test_client()
    a = _register_and_login(client_a, "iso_renew_a")
    b = _register_and_login(client_b, "iso_renew_b")

    eid_a, sid_a, mid_a = _full_pipeline(client_a, a["admin_id"], "111000003")

    resp = client_b.get(f"/memberships/renew/{sid_a}", follow_redirects=True)
    assert b"Student not found" in resp.data


def test_admin_b_cannot_collect_payment_on_admin_a_membership(app):
    client_a = app.test_client()
    client_b = app.test_client()
    a = _register_and_login(client_a, "iso_pay_a")
    b = _register_and_login(client_b, "iso_pay_b")

    eid_a, sid_a, mid_a = _full_pipeline(client_a, a["admin_id"], "111000004")

    resp = client_b.post(
        f"/payments/collect/{mid_a}",
        data={"amount_paid": "100", "payment_mode": "Cash"},
        follow_redirects=True,
    )
    assert b"Membership not found" in resp.data

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT paid_amount FROM memberships WHERE membership_id=?", (mid_a,))
    assert cur.fetchone()["paid_amount"] == 500  # unchanged by B's attempt
    conn.close()


def test_admin_b_lists_dont_leak_admin_a_data(app):
    client_a = app.test_client()
    client_b = app.test_client()
    a = _register_and_login(client_a, "iso_list_a")
    b = _register_and_login(client_b, "iso_list_b")

    make_enquiry(client_a, full_name="UniqueNameForListLeakTestAAA")
    _full_pipeline(client_a, a["admin_id"], "111000005")

    for path in ("/enquiries/", "/students/", "/memberships/", "/payments/", "/cashbook/"):
        resp = client_b.get(path)
        assert resp.status_code == 200
        assert b"UniqueNameForListLeakTestAAA" not in resp.data


def test_admin_b_cannot_edit_admin_a_cashbook_entry(app):
    client_a = app.test_client()
    client_b = app.test_client()
    a = _register_and_login(client_a, "iso_cb_a")
    b = _register_and_login(client_b, "iso_cb_b")

    client_a.post(
        "/cashbook/add",
        data={"transaction_type": "Income", "category": "Donation", "amount": "500",
              "payment_method": "Cash", "transaction_date": "2026-07-22",
              "person": "Donor A", "description": "x", "redirect_to": "cashbook"},
        follow_redirects=True,
    )
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT entry_id, amount FROM cashbook WHERE admin_id=? ORDER BY entry_id DESC LIMIT 1", (a["admin_id"],))
    entry = cur.fetchone()
    conn.close()

    resp = client_b.post(
        f"/cashbook/edit/{entry['entry_id']}",
        data={"category": "Donation", "amount": "1", "payment_method": "Cash",
              "transaction_date": "2026-07-22", "person": "Hacker", "description": "x"},
        follow_redirects=True,
    )
    assert b"Transaction not found" in resp.data
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT amount FROM cashbook WHERE entry_id=?", (entry["entry_id"],))
    assert cur.fetchone()["amount"] == entry["amount"]
    conn.close()


def test_admin_b_notifications_dont_include_admin_a_memberships(app):
    client_a = app.test_client()
    client_b = app.test_client()
    a = _register_and_login(client_a, "iso_notif_a")
    b = _register_and_login(client_b, "iso_notif_b")

    from datetime import date
    _full_pipeline(client_a, a["admin_id"], "111000006")
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE memberships SET end_date=? WHERE student_id IN (SELECT student_id FROM students WHERE admin_id=?)",
        (date.today().isoformat(), a["admin_id"]),
    )
    conn.commit()
    conn.close()

    resp = client_b.get("/notifications/today")
    assert resp.status_code == 200
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT full_name FROM students WHERE admin_id=?", (a["admin_id"],))
    a_name = cur.fetchone()["full_name"]
    conn.close()
    assert a_name.encode() not in resp.data


def test_admin_b_settings_are_independent_of_admin_a(app):
    client_a = app.test_client()
    client_b = app.test_client()
    a = _register_and_login(client_a, "iso_set_a")
    b = _register_and_login(client_b, "iso_set_b")

    client_a.post(
        "/settings/library",
        data={"library_name": "Admin A Private Library", "owner_name": "A Owner",
              "phone": "9111111111", "email": "", "address": "", "city": "",
              "state": "", "pincode": "", "opening_time": "", "closing_time": "",
              "weekly_holiday": "", "receipt_footer": ""},
        follow_redirects=True,
    )
    resp = client_b.get("/settings/library")
    assert b"Admin A Private Library" not in resp.data
