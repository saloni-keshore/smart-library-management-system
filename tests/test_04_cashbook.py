"""Cashbook: manual entries, filters, ledger, edit, KPI consistency."""
from tests.conftest import (
    get_cashbook_entries, get_last_cashbook_entry, get_audit_log_entries,
    get_cashbook_entry_by_id,
)


def add_txn(client, **overrides):
    data = {
        "transaction_type": "Income",
        "category": "Donation",
        "amount": "500",
        "payment_method": "Cash",
        "transaction_date": "2026-07-22",
        "person": "Some Donor",
        "description": "test donation",
        "redirect_to": "cashbook",
    }
    data.update(overrides)
    return client.post("/cashbook/add", data=data, follow_redirects=True)


def test_cashbook_requires_login(client):
    resp = client.get("/cashbook/", follow_redirects=False)
    assert resp.status_code == 302


def test_cashbook_index_loads(logged_in_client):
    client, admin = logged_in_client
    resp = client.get("/cashbook/")
    assert resp.status_code == 200


def test_add_income_transaction_success(logged_in_client):
    client, admin = logged_in_client
    resp = add_txn(client)
    assert b"recorded under" in resp.data
    entries = get_cashbook_entries(admin["admin_id"], type="Income")
    assert len(entries) == 1


def test_add_expense_transaction_success(logged_in_client):
    client, admin = logged_in_client
    resp = add_txn(client, transaction_type="Expense", category="Rent", amount="2000")
    assert b"recorded under" in resp.data


def test_add_transaction_invalid_category_for_type_rejected(logged_in_client):
    """Expense category submitted while type=Income must be rejected."""
    client, admin = logged_in_client
    resp = add_txn(client, transaction_type="Income", category="Rent")
    assert b"valid category" in resp.data


def test_add_transaction_auto_category_rejected_from_manual_form(logged_in_client):
    """AUTO_CATEGORIES ('Admission Fee' etc.) must never be accepted from
    the manual entry form - only insert_income_entry() may create them."""
    client, admin = logged_in_client
    resp = add_txn(client, transaction_type="Income", category="Admission Fee")
    assert b"valid category" in resp.data


def test_add_transaction_invalid_type_rejected(logged_in_client):
    client, admin = logged_in_client
    resp = add_txn(client, transaction_type="Bogus")
    assert b"valid category" in resp.data


def test_add_transaction_invalid_payment_method_rejected(logged_in_client):
    client, admin = logged_in_client
    resp = add_txn(client, payment_method="Bitcoin")
    assert b"valid category" in resp.data


def test_add_transaction_zero_amount_rejected(logged_in_client):
    client, admin = logged_in_client
    resp = add_txn(client, amount="0")
    assert b"valid category" in resp.data


def test_add_transaction_negative_amount_rejected(logged_in_client):
    client, admin = logged_in_client
    resp = add_txn(client, amount="-100")
    assert b"valid category" in resp.data


def test_add_transaction_non_numeric_amount_rejected(logged_in_client):
    client, admin = logged_in_client
    resp = add_txn(client, amount="notanumber")
    assert b"valid category" in resp.data


def test_add_transaction_missing_amount_rejected(logged_in_client):
    client, admin = logged_in_client
    resp = add_txn(client, amount="")
    assert b"valid category" in resp.data


def test_add_transaction_huge_amount(logged_in_client):
    client, admin = logged_in_client
    resp = add_txn(client, amount="123456789")
    assert b"recorded under" in resp.data


def test_add_transaction_decimal_amount(logged_in_client):
    client, admin = logged_in_client
    resp = add_txn(client, amount="99.995")
    assert b"recorded under" in resp.data


def test_add_transaction_no_default_date_uses_today(logged_in_client):
    client, admin = logged_in_client
    resp = add_txn(client, transaction_date="")
    assert b"recorded under" in resp.data


def test_add_transaction_unicode_person_description(logged_in_client):
    client, admin = logged_in_client
    resp = add_txn(client, person="दानी 😀", description="备注 chars ñ")
    assert b"recorded under" in resp.data


def test_add_transaction_sql_injection_description(logged_in_client):
    client, admin = logged_in_client
    resp = add_txn(client, description="'; DROP TABLE cashbook;--")
    assert b"recorded under" in resp.data
    assert len(get_cashbook_entries(admin["admin_id"])) > 0


def test_add_transaction_reference_id_generated(logged_in_client):
    client, admin = logged_in_client
    add_txn(client, transaction_type="Expense", category="Rent", amount="999")
    entry = get_last_cashbook_entry(admin["admin_id"])
    assert entry["reference_id"].startswith("EXP-")


def test_add_transaction_audit_log_created(logged_in_client):
    client, admin = logged_in_client
    add_txn(client)
    entries = get_audit_log_entries(admin["admin_id"], action="Created")
    assert len(entries) >= 1


def test_add_transaction_redirect_to_dashboard(logged_in_client):
    client, admin = logged_in_client
    resp = add_txn(client, redirect_to="dashboard")
    assert resp.request.path == "/dashboard"


# ---------------------------------------------------------------------------
# Edit transaction
# ---------------------------------------------------------------------------

def _last_entry_id(admin_id):
    entry = get_last_cashbook_entry(admin_id)
    return entry["entry_id"] if entry else None


def test_edit_manual_transaction_success(logged_in_client):
    client, admin = logged_in_client
    add_txn(client)
    eid = _last_entry_id(admin["admin_id"])
    resp = client.post(
        f"/cashbook/edit/{eid}",
        data={"category": "Library Fine", "amount": "750", "payment_method": "UPI",
              "transaction_date": "2026-07-23", "person": "Updated", "description": "updated"},
        follow_redirects=True,
    )
    assert b"Transaction updated successfully" in resp.data
    row = get_cashbook_entry_by_id(eid)
    assert row["amount"] == 750
    assert row["category"] == "Library Fine"


def test_edit_automatic_entry_blocked(logged_in_client):
    """Automatic (Admission/Renewal/Payments-sourced) ledger entries must
    never be editable through this endpoint."""
    client, admin = logged_in_client
    from tests.conftest import make_enquiry, get_last_enquiry_id, admit_student, get_last_student_id, create_membership
    make_enquiry(client)
    eid_e = get_last_enquiry_id(admin["admin_id"])
    admit_student(client, eid_e)
    sid = get_last_student_id(admin["admin_id"])
    create_membership(client, sid, paid_amount="500", due_amount="0")

    auto_entries = [
        e for e in get_cashbook_entries(admin["admin_id"])
        if e.get("source") != "Cashbook Manual Entry"
    ]
    auto_entry = max(auto_entries, key=lambda e: e["entry_id"]) if auto_entries else None
    assert auto_entry is not None

    resp = client.post(
        f"/cashbook/edit/{auto_entry['entry_id']}",
        data={"category": "Donation", "amount": "1", "payment_method": "Cash",
              "transaction_date": "2026-07-22", "person": "Hacker", "description": "x"},
        follow_redirects=True,
    )
    assert b"cannot be edited" in resp.data

    row = get_cashbook_entry_by_id(auto_entry["entry_id"])
    assert row["amount"] == auto_entry["amount"]


def test_edit_transaction_nonexistent(logged_in_client):
    client, admin = logged_in_client
    resp = client.post(
        "/cashbook/edit/999999999",
        data={"category": "Donation", "amount": "1", "payment_method": "Cash", "transaction_date": "2026-07-22"},
        follow_redirects=True,
    )
    assert b"Transaction not found" in resp.data


def test_edit_transaction_invalid_amount_rejected(logged_in_client):
    client, admin = logged_in_client
    add_txn(client)
    eid = _last_entry_id(admin["admin_id"])
    resp = client.post(
        f"/cashbook/edit/{eid}",
        data={"category": "Donation", "amount": "-5", "payment_method": "Cash", "transaction_date": "2026-07-22"},
        follow_redirects=True,
    )
    assert b"valid category" in resp.data


def test_edit_transaction_wrong_category_for_type_rejected(logged_in_client):
    client, admin = logged_in_client
    add_txn(client)  # Income/Donation
    eid = _last_entry_id(admin["admin_id"])
    resp = client.post(
        f"/cashbook/edit/{eid}",
        data={"category": "Rent", "amount": "5", "payment_method": "Cash", "transaction_date": "2026-07-22"},
        follow_redirects=True,
    )
    assert b"valid category" in resp.data


# ---------------------------------------------------------------------------
# Filters, search, pagination
# ---------------------------------------------------------------------------

def test_cashbook_filter_by_type(logged_in_client):
    client, admin = logged_in_client
    add_txn(client, transaction_type="Income", category="Donation")
    add_txn(client, transaction_type="Expense", category="Rent")
    resp = client.get("/cashbook/?transaction_type=Expense")
    assert resp.status_code == 200


def test_cashbook_filter_by_category(logged_in_client):
    client, admin = logged_in_client
    add_txn(client, category="Donation")
    resp = client.get("/cashbook/?category=Donation")
    assert resp.status_code == 200


def test_cashbook_filter_date_preset_today(logged_in_client):
    client, admin = logged_in_client
    resp = client.get("/cashbook/?date_preset=today")
    assert resp.status_code == 200


def test_cashbook_filter_date_preset_this_week(logged_in_client):
    client, admin = logged_in_client
    resp = client.get("/cashbook/?date_preset=this_week")
    assert resp.status_code == 200


def test_cashbook_filter_date_preset_this_month(logged_in_client):
    client, admin = logged_in_client
    resp = client.get("/cashbook/?date_preset=this_month")
    assert resp.status_code == 200


def test_cashbook_filter_custom_date_range(logged_in_client):
    client, admin = logged_in_client
    resp = client.get("/cashbook/?date_preset=custom&date_from=2026-01-01&date_to=2026-12-31")
    assert resp.status_code == 200


def test_cashbook_filter_invalid_date_range_no_crash(logged_in_client):
    """date_from after date_to - should just return empty results, no crash."""
    client, admin = logged_in_client
    resp = client.get("/cashbook/?date_from=2026-12-31&date_to=2026-01-01")
    assert resp.status_code == 200


def test_cashbook_search_by_reference_or_person(logged_in_client):
    client, admin = logged_in_client
    add_txn(client, person="FindMePlease")
    resp = client.get("/cashbook/?search=FindMePlease")
    assert resp.status_code == 200
    assert b"FindMePlease" in resp.data


def test_cashbook_search_special_characters_no_crash(logged_in_client):
    client, admin = logged_in_client
    resp = client.get("/cashbook/?search=%25%27%22--")
    assert resp.status_code == 200


def test_cashbook_pagination_page_1(logged_in_client):
    client, admin = logged_in_client
    for _ in range(15):
        add_txn(client)
    resp = client.get("/cashbook/?page=1")
    assert resp.status_code == 200


def test_cashbook_pagination_out_of_range_page_clamped(logged_in_client):
    client, admin = logged_in_client
    add_txn(client)
    resp = client.get("/cashbook/?page=9999")
    assert resp.status_code == 200  # clamped server-side, no crash


def test_cashbook_pagination_negative_page_no_crash(logged_in_client):
    client, admin = logged_in_client
    resp = client.get("/cashbook/?page=-5")
    assert resp.status_code == 200


def test_cashbook_pagination_non_numeric_page_defaults(logged_in_client):
    client, admin = logged_in_client
    resp = client.get("/cashbook/?page=abc")
    assert resp.status_code == 200


def test_cashbook_filter_source_manual(logged_in_client):
    client, admin = logged_in_client
    add_txn(client)
    resp = client.get("/cashbook/?source=Manual")
    assert resp.status_code == 200


def test_cashbook_filter_source_automatic(logged_in_client):
    client, admin = logged_in_client
    resp = client.get("/cashbook/?source=Automatic")
    assert resp.status_code == 200


def test_cashbook_kpi_cash_balance_matches_math(logged_in_client):
    client, admin = logged_in_client
    add_txn(client, transaction_type="Income", category="Donation", amount="1000", payment_method="Cash")
    add_txn(client, transaction_type="Expense", category="Rent", amount="300", payment_method="Cash")
    resp = client.get("/cashbook/")
    assert resp.status_code == 200

    from database.cashbook_queries import get_cash_balance
    assert get_cash_balance(admin["admin_id"]) == 700
