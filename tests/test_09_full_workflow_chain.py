"""End-to-end: Enquiry -> Admission -> Membership -> Payment -> Receipt ->
Cashbook -> Dashboard -> BI -> Notifications -> Audit Log, verifying every
downstream module updates exactly once and stays numerically consistent."""
from database.supabase_client import get_supabase_client
from tests.conftest import (
    make_enquiry, get_last_enquiry_id, get_enquiry_by_id, admit_student, get_last_student_id,
    create_membership, get_last_membership_id, get_membership_by_id,
    get_cashbook_entries, get_audit_log_entries, get_admin_by_username,
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

    supabase = get_supabase_client()
    payment_rows = supabase.table("payments").select("*").eq("membership_id", mid).execute().data
    assert len(payment_rows) == 1
    assert payment_rows[0]["amount_paid"] == 600

    # 4. Cashbook: exactly one automatic Income entry for this payment.
    # cashbook now lives in Supabase (ADR-22) - the automatic entry made by
    # insert_income_entry() is mirrored there too, so this checks the
    # source of truth routes/cashbook.py's index() actually reads.
    cb_rows = get_cashbook_entries(admin_id, category="Admission Fee")
    assert len(cb_rows) == 1
    assert cb_rows[0]["amount"] == 600
    assert cb_rows[0]["source"] == "Admission"

    # 4b. Audit log: exactly one Auto-Created entry for that cashbook row
    audit_rows = get_audit_log_entries(
        admin_id, entry_id=cb_rows[0]["entry_id"], action="Auto-Created"
    )
    assert len(audit_rows) == 1

    # 5. Collect the remaining pending balance -> second payment/receipt/cashbook/audit row
    client.post(
        f"/payments/collect/{mid}",
        data={"amount_paid": "400", "payment_mode": "UPI", "remarks": "final"},
        follow_redirects=True,
    )

    # memberships now lives in Supabase only (ADR-29) - the source of truth
    # routes/membership.py's index() reads.
    m_supabase = get_membership_by_id(mid)
    assert m_supabase["paid_amount"] == 1000
    assert m_supabase["pending_amount"] == 0

    payment_rows = supabase.table("payments").select("payment_id").eq("membership_id", mid).execute().data
    assert len(payment_rows) == 2

    assert len(get_cashbook_entries(admin_id, category="Membership Fee")) == 1

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
    receipt_rows = supabase.table("payments").select("receipt_number").eq("membership_id", mid).execute().data
    receipts = [r["receipt_number"] for r in receipt_rows]
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
            "plan_name": "Custom", "joining_date": "2026-08-22", "duration_days": "30",
            "end_date": "2026-09-21", "remarks": "renew", "payment_mode": "Cash",
            "paid_amount": "500", "total_fee": "500",
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

    payment_rows = supabase.table("payments").select("payment_id").eq("student_id", sid).execute().data
    assert len(payment_rows) == 2  # one payment per membership, none lost/duplicated

    admission_and_renewal = [
        e for e in get_cashbook_entries(admin_id)
        if e.get("category") in ("Admission Fee", "Membership Renewal")
    ]
    assert len(admission_and_renewal) == 2

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

    supabase = get_supabase_client()

    payment_rows = supabase.table("payments").select("payment_id, membership_id").eq("membership_id", mid).execute().data
    assert len(payment_rows) > 0
    membership_ids = {p["membership_id"] for p in payment_rows}
    for m_id in membership_ids:
        assert supabase.table("memberships").select("membership_id").eq("membership_id", m_id).execute().data

    # payment_id now round-trips through Supabase too (ADR-25, closes TD-38's
    # common case) - every payment for this membership has a matching
    # cashbook row via payment_id.
    payment_ids = [p["payment_id"] for p in payment_rows]
    for pid in payment_ids:
        cashbook_rows = supabase.table("cashbook").select("entry_id").eq("payment_id", pid).execute().data
        assert len(cashbook_rows) == 1


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
        # admins now lives in Supabase only (ADR-31) - no SQLite mirror left.
        return get_admin_by_username(creds["username"])["admin_id"]

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

    supabase = get_supabase_client()
    all_receipts = []
    start = 0
    page_size = 1000
    while True:
        page = (
            supabase.table("payments")
            .select("receipt_number")
            .order("payment_id")
            .range(start, start + page_size - 1)
            .execute()
            .data
        )
        all_receipts.extend(r["receipt_number"] for r in page)
        if len(page) < page_size:
            break
        start += page_size

    dupes = {r for r in all_receipts if all_receipts.count(r) > 1}
    assert dupes == set()
