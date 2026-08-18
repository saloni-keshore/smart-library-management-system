"""Global navbar search (ADR-44) - database/search_queries.py,
routes/search.py's GET /search/suggestions."""

from tests.conftest import (
    make_enquiry, get_last_enquiry_id, admit_student, get_last_student_id,
    create_membership,
)


def test_search_requires_login(client):
    resp = client.get("/search/suggestions?q=x")
    assert resp.status_code == 401
    assert resp.get_json() == {}


def test_search_empty_query_returns_empty_groups(logged_in_client):
    client, admin = logged_in_client
    resp = client.get("/search/suggestions?q=")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data == {"students": [], "payments": [], "enquiries": [], "cashbook": []}


def test_search_finds_student_by_name_and_mobile(logged_in_client):
    client, admin = logged_in_client
    make_enquiry(client, full_name="Zanzibar Query Target", mobile="9123456780")
    eid = get_last_enquiry_id(admin["admin_id"])
    admit_student(client, eid)

    resp_name = client.get("/search/suggestions?q=zanzibar query")
    names = [s["full_name"] for s in resp_name.get_json()["students"]]
    assert "Zanzibar Query Target" in names

    resp_mobile = client.get("/search/suggestions?q=123456780")
    names = [s["full_name"] for s in resp_mobile.get_json()["students"]]
    assert "Zanzibar Query Target" in names


def test_search_finds_payment_by_receipt_number(logged_in_client):
    client, admin = logged_in_client
    make_enquiry(client, full_name="Payment Search Target", mobile="9123456781")
    eid = get_last_enquiry_id(admin["admin_id"])
    admit_student(client, eid)
    sid = get_last_student_id(admin["admin_id"])
    create_membership(client, sid, paid_amount="500", due_amount="0")

    resp = client.get("/search/suggestions?q=payment search target")
    payments = resp.get_json()["payments"]
    assert any(p["full_name"] == "Payment Search Target" for p in payments)
    assert payments[0]["receipt_number"]


def test_search_finds_enquiry(logged_in_client):
    client, admin = logged_in_client
    make_enquiry(client, full_name="Enquiry Search Target", mobile="9123456782")

    resp = client.get("/search/suggestions?q=enquiry search")
    names = [e["full_name"] for e in resp.get_json()["enquiries"]]
    assert "Enquiry Search Target" in names


def test_search_finds_cashbook_entry(logged_in_client):
    client, admin = logged_in_client
    client.post(
        "/cashbook/add",
        data={
            "transaction_type": "Income", "category": "Donation", "amount": "500",
            "payment_method": "Cash", "transaction_date": "2026-08-01",
            "person": "Cashbook Search Target", "description": "x",
            "redirect_to": "cashbook",
        },
        follow_redirects=True,
    )

    resp = client.get("/search/suggestions?q=cashbook search target")
    persons = [c["person"] for c in resp.get_json()["cashbook"]]
    assert "Cashbook Search Target" in persons


def test_search_cross_tenant_isolation(app):
    client_a = app.test_client()
    client_b = app.test_client()

    from tests.conftest import get_admin_by_username
    import random, string

    def register(client, suffix):
        creds = {
            "full_name": f"Tenant {suffix}",
            "username": f"qa_search_{suffix}",
            "mobile": "9" + "".join(random.choices(string.digits, k=9)),
            "email": f"search_tenant_{suffix}@example.com",
            "password": "TenantPass1",
            "confirm_password": "TenantPass1",
        }
        client.post("/register", data=creds, follow_redirects=True)
        client.post("/", data={"username": creds["username"], "password": creds["password"]}, follow_redirects=True)
        creds["admin_id"] = get_admin_by_username(creds["username"])["admin_id"]
        return creds

    register(client_a, "iso_search_a")
    register(client_b, "iso_search_b")

    make_enquiry(client_a, full_name="Tenant A Isolation Target", mobile="9123456799")

    resp = client_b.get("/search/suggestions?q=tenant a isolation")
    data = resp.get_json()
    assert data["students"] == []
    assert data["payments"] == []
    assert data["enquiries"] == []
    assert data["cashbook"] == []


def test_search_caps_results_per_type(logged_in_client):
    client, admin = logged_in_client
    for i in range(7):
        make_enquiry(
            client,
            full_name=f"Cap Test Sibling {i}",
            mobile=f"91234567{i:02d}",
        )
        eid = get_last_enquiry_id(admin["admin_id"])
        admit_student(client, eid, id_proof=f"AADHAR-CAP-{i}")

    resp = client.get("/search/suggestions?q=cap test sibling")
    assert len(resp.get_json()["students"]) <= 5
