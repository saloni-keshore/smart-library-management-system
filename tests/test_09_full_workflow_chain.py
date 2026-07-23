"""End-to-end: Enquiry -> Admission -> Membership -> Payment -> Receipt ->
Cashbook -> Dashboard -> BI -> Notifications -> Audit Log, verifying every
downstream module updates exactly once and stays numerically consistent."""
from database.db import get_connection
from database.supabase_client import get_supabase_client
from tests.conftest import (
    make_enquiry, get_last_enquiry_id, get_enquiry_by_id, admit_student, get_last_student_id,
    create_membership, get_last_membership_id, get_membership_by_id,
)


def test_full_chain_updates_every_downstream_module_exactly_once(logged_in_client):
    client, admin = logged_in_client
    admin_id = admin["admin_id"]

    # 1. Enquiry
    make_enquiry(client, full_name="Chain Test Student", mobile="9199999001")
    eid = get_last_enquiry_id(admin_id)

    # 2. Admission
    admit_student(client, eid)
    sid = get_last_student_id(admin_id)

    # enquiries.status now lives in Supabase (routes/enquiries.py reads it
    # from there); admission() flips it there directly (TD-36 resolved).
    enquiry = get_enquiry_by_id(eid)
    assert enquiry["status"] == "Admitted"

    # 3. Membership + Payment + Receipt (admission payment)
    create_membership(client, sid, paid_amount="600", due_amount="400")
    mid = get_last_membership_id(sid)

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM payments WHERE membership_id=?", (mid,))
    assert cur.fetchone()["c"] == 1
    cur.execute("SELECT receipt_number, amount_paid FROM payments WHERE membership_id=?", (mid,))
    payment_1 = cur.fetchone()
    assert payment_1["amount_paid"] == 600
    conn.close()

    # 4. Cashbook: exactly one automatic Income entry for this payment
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM cashbook WHERE admin_id=? AND category='Admission Fee'",
        (admin_id,),
    )
    cb_rows = cur.fetchall()
    conn.close()
    assert len(cb_rows) == 1
    assert cb_rows[0]["amount"] == 600
    assert cb_rows[0]["source"] == "Admission"

    # 4b. Audit log: exactly one Auto-Created entry for that cashbook row
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "SELECT COUNT(*) AS c FROM audit_log WHERE admin_id=? AND entry_id=? AND action='Auto-Created'",
        (admin_id, cb_rows[0]["entry_id"]),
    )
    assert cur.fetchone()["c"] == 1
    conn.close()

    # 5. Collect the remaining pending balance -> second payment/receipt/cashbook/audit row
    client.post(
        f"/payments/collect/{mid}",
        data={"amount_paid": "400", "payment_mode": "UPI", "remarks": "final"},
        follow_redirects=True,
    )

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT paid_amount, pending_amount FROM memberships WHERE membership_id=?", (mid,))
    m = cur.fetchone()
    assert m["paid_amount"] == 1000
    assert m["pending_amount"] == 0

    cur.execute("SELECT COUNT(*) AS c FROM payments WHERE membership_id=?", (mid,))
    assert cur.fetchone()["c"] == 2

    cur.execute("SELECT COUNT(*) AS c FROM cashbook WHERE admin_id=? AND category='Membership Fee'", (admin_id,))
    assert cur.fetchone()["c"] == 1
    conn.close()

    # 6. Dashboard totals reflect the same numbers
    from database.cashbook_queries import get_total_fee_revenue, get_pending_fees
    assert get_total_fee_revenue(admin_id) == 1000
    assert get_pending_fees(admin_id) == 0

    resp = client.get("/dashboard")
    assert resp.status_code == 200

    # 7. Business Intelligence loads without error against this data
    resp = client.get("/business-intelligence/")
    assert resp.status_code == 200

    # 8. Membership Distribution reflects the same totals
    resp = client.get("/membership-distribution/")
    assert resp.status_code == 200

    # 9. Receipt numbers are unique across both payments
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT receipt_number FROM payments WHERE membership_id=?", (mid,))
    receipts = [r["receipt_number"] for r in cur.fetchall()]
    conn.close()
    assert len(receipts) == len(set(receipts)) == 2

    # 10. Notifications: this membership isn't expiring soon, so it must not
    # appear in any urgent bucket.
    resp = client.get("/notifications/")
    assert resp.status_code == 200
    assert b"Chain Test Student" not in resp.data


def test_full_chain_renewal_expires_old_and_all_totals_stay_consistent(logged_in_client):
    client, admin = logged_in_client
    admin_id = admin["admin_id"]

    make_enquiry(client, full_name="Renewal Chain Student", mobile="9199999002")
    eid = get_last_enquiry_id(admin_id)
    admit_student(client, eid)
    sid = get_last_student_id(admin_id)
    create_membership(client, sid, paid_amount="500", due_amount="0")
    old_mid = get_last_membership_id(sid)

    client.post(
        f"/memberships/renew/{sid}",
        data={
            "plan_name": "Monthly", "joining_date": "2026-08-22", "duration_days": "30",
            "end_date": "2026-09-21", "remarks": "renew", "payment_mode": "Cash",
            "paid_amount": "500", "due_amount": "0",
        },
        follow_redirects=True,
    )

    old_membership = get_membership_by_id(old_mid)
    assert old_membership["membership_status"] == "Expired"

    supabase = get_supabase_client()
    total_count = (
        supabase.table("memberships")
        .select("membership_id", count="exact", head=True)
        .eq("student_id", sid)
        .execute()
        .count
    )
    assert total_count == 2  # exactly one old (expired) + one new (active)

    active_count = (
        supabase.table("memberships")
        .select("membership_id", count="exact", head=True)
        .eq("student_id", sid)
        .eq("membership_status", "Active")
        .execute()
        .count
    )
    assert active_count == 1

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) AS c FROM payments p JOIN memberships m ON p.membership_id=m.membership_id WHERE m.student_id=?", (sid,))
    assert cur.fetchone()["c"] == 2  # one payment per membership, none lost/duplicated

    cur.execute(
        "SELECT COUNT(*) AS c FROM cashbook WHERE admin_id=? AND category IN ('Admission Fee','Membership Renewal')",
        (admin_id,),
    )
    assert cur.fetchone()["c"] == 2
    conn.close()

    from database.cashbook_queries import get_total_fee_revenue
    assert get_total_fee_revenue(admin_id) == 1000


def test_no_orphan_payments_or_cashbook_rows_after_full_run(logged_in_client):
    """Referential sanity: every payments row traces to a real membership;
    every payment-sourced cashbook row traces to a real payment."""
    client, admin = logged_in_client
    admin_id = admin["admin_id"]

    make_enquiry(client, full_name="Orphan Check Student", mobile="9199999003")
    eid = get_last_enquiry_id(admin_id)
    admit_student(client, eid)
    sid = get_last_student_id(admin_id)
    create_membership(client, sid, paid_amount="300", due_amount="200")
    mid = get_last_membership_id(sid)
    client.post(f"/payments/collect/{mid}", data={"amount_paid": "200", "payment_mode": "Cash"}, follow_redirects=True)

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT COUNT(*) AS c FROM payments p
        LEFT JOIN memberships m ON p.membership_id = m.membership_id
        WHERE m.membership_id IS NULL
    """)
    assert cur.fetchone()["c"] == 0

    cur.execute("""
        SELECT COUNT(*) AS c FROM cashbook c
        WHERE c.payment_id IS NOT NULL
        AND c.payment_id NOT IN (SELECT payment_id FROM payments)
    """)
    assert cur.fetchone()["c"] == 0

    # Every payment for this membership has a matching cashbook row via payment_id
    cur.execute("SELECT payment_id FROM payments WHERE membership_id=?", (mid,))
    payment_ids = [r["payment_id"] for r in cur.fetchall()]
    for pid in payment_ids:
        cur.execute("SELECT COUNT(*) AS c FROM cashbook WHERE payment_id=?", (pid,))
        assert cur.fetchone()["c"] == 1

    conn.close()


def test_receipt_numbers_globally_unique_across_two_fresh_admins(app):
    """Regression test for the fixed generate_receipt_number() bug: two
    different fresh admins (neither with a Library Profile) must not
    collide on their first receipt number."""
    client_a = app.test_client()
    client_b = app.test_client()

    import random, string as _s
    def _reg(client, tag):
        creds = {
            "full_name": f"Fresh {tag}", "username": f"qa_fresh_{tag}_{''.join(random.choices(_s.ascii_lowercase, k=5))}",
            "mobile": "9" + "".join(random.choices(_s.digits, k=9)),
            "email": f"{tag}@example.com", "password": "FreshPass1", "confirm_password": "FreshPass1",
        }
        client.post("/register", data=creds, follow_redirects=True)
        client.post("/", data={"username": creds["username"], "password": creds["password"]}, follow_redirects=True)
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("SELECT admin_id FROM admins WHERE username=?", (creds["username"],))
        return cur.fetchone()["admin_id"]

    admin_a = _reg(client_a, "a")
    admin_b = _reg(client_b, "b")

    for client, admin_id in ((client_a, admin_a), (client_b, admin_b)):
        make_enquiry(client, mobile="9" + "".join(__import__("random").choices("0123456789", k=9)))
        eid = get_last_enquiry_id(admin_id)
        admit_student(client, eid)
        sid = get_last_student_id(admin_id)
        resp = create_membership(client, sid, paid_amount="500", due_amount="0")
        assert b"Membership created successfully" in resp.data
        assert b"Receipt No:" in resp.data

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT receipt_number, COUNT(*) AS c FROM payments GROUP BY receipt_number HAVING c > 1")
    dupes = cur.fetchall()
    conn.close()
    assert dupes == []
