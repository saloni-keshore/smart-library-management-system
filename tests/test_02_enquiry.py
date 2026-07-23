"""Enquiries: CRUD, validation, edge cases."""
from database.supabase_client import get_supabase_client
from tests.conftest import make_enquiry, get_last_enquiry_id, get_enquiry_by_id


def test_enquiry_requires_login(client):
    resp = client.get("/enquiries/", follow_redirects=False)
    assert resp.status_code == 302


def test_add_enquiry_success(logged_in_client):
    client, admin = logged_in_client
    resp, data = make_enquiry(client)
    assert resp.status_code == 200
    assert b"Enquiry added successfully" in resp.data
    eid = get_last_enquiry_id(admin["admin_id"])
    assert eid is not None


def test_add_enquiry_empty_full_name(logged_in_client):
    client, admin = logged_in_client
    resp, data = make_enquiry(client, full_name="")
    assert resp.status_code == 200
    eid = get_last_enquiry_id(admin["admin_id"])
    row = get_enquiry_by_id(eid)
    # Gap: no server-side validation rejects empty name (NOT NULL allows "")
    assert row["full_name"] == ""


def test_add_enquiry_empty_mobile(logged_in_client):
    client, admin = logged_in_client
    resp, data = make_enquiry(client, mobile="")
    assert resp.status_code == 200


def test_add_enquiry_invalid_mobile_letters(logged_in_client):
    client, admin = logged_in_client
    resp, data = make_enquiry(client, mobile="abcdefghij")
    assert resp.status_code == 200
    eid = get_last_enquiry_id(admin["admin_id"])
    row = get_enquiry_by_id(eid)
    # Gap: mobile format is not validated at all on enquiry add
    assert row["mobile"] == "abcdefghij"


def test_add_enquiry_duplicate_mobile_allowed(logged_in_client):
    client, admin = logged_in_client
    make_enquiry(client, mobile="9111122223")
    resp, data = make_enquiry(client, mobile="9111122223")
    assert resp.status_code == 200  # duplicates intentionally allowed (re-enquiry)


def test_add_enquiry_very_long_remarks(logged_in_client):
    client, admin = logged_in_client
    long_remark = "x" * 10000
    resp, data = make_enquiry(client, remarks=long_remark)
    assert resp.status_code == 200
    eid = get_last_enquiry_id(admin["admin_id"])
    row = get_enquiry_by_id(eid)
    assert len(row["remarks"]) == 10000


def test_add_enquiry_unicode_emoji(logged_in_client):
    client, admin = logged_in_client
    resp, data = make_enquiry(client, full_name="राज कुमार 😀", remarks="备注 🎉")
    assert resp.status_code == 200
    eid = get_last_enquiry_id(admin["admin_id"])
    row = get_enquiry_by_id(eid)
    assert row["full_name"] == "राज कुमार 😀"


def test_add_enquiry_sql_injection_remarks(logged_in_client):
    client, admin = logged_in_client
    resp, data = make_enquiry(client, remarks="'; DROP TABLE enquiries;--")
    assert resp.status_code == 200
    supabase = get_supabase_client()
    count = supabase.table("enquiries").select("enquiry_id", count="exact", head=True).execute().count
    assert count > 0


def test_add_enquiry_bad_date_format(logged_in_client):
    client, admin = logged_in_client
    resp, data = make_enquiry(client, followup_date="not-a-date")
    assert resp.status_code == 200
    # Supabase's followup_date is a strictly-typed PostgreSQL DATE, unlike
    # SQLite's -- unparsable input is sanitized to NULL rather than crashing
    # or being stored verbatim (see routes/enquiries.py's _sanitize_date).
    eid = get_last_enquiry_id(admin["admin_id"])
    row = get_enquiry_by_id(eid)
    assert row["followup_date"] is None


def test_add_enquiry_missing_fields(logged_in_client):
    client, admin = logged_in_client
    resp = client.post("/enquiries/add", data={}, follow_redirects=True)
    assert resp.status_code == 200


def test_enquiry_list_shows_only_this_admins_rows(logged_in_client):
    client, admin = logged_in_client
    make_enquiry(client)
    resp = client.get("/enquiries/")
    assert resp.status_code == 200


def test_view_enquiry_success(logged_in_client):
    client, admin = logged_in_client
    make_enquiry(client)
    eid = get_last_enquiry_id(admin["admin_id"])
    resp = client.get(f"/enquiries/view/{eid}")
    assert resp.status_code == 200


def test_view_enquiry_nonexistent(logged_in_client):
    client, admin = logged_in_client
    resp = client.get("/enquiries/view/999999999", follow_redirects=True)
    assert b"Enquiry not found" in resp.data


def test_view_enquiry_negative_id(logged_in_client):
    client, admin = logged_in_client
    resp = client.get("/enquiries/view/-1")
    assert resp.status_code == 404  # Flask int converter rejects negative


def test_view_enquiry_non_numeric_id(logged_in_client):
    client, admin = logged_in_client
    resp = client.get("/enquiries/view/abc")
    assert resp.status_code == 404


def test_edit_enquiry_success(logged_in_client):
    client, admin = logged_in_client
    make_enquiry(client)
    eid = get_last_enquiry_id(admin["admin_id"])
    resp = client.post(
        f"/enquiries/edit/{eid}",
        data={
            "full_name": "Updated Name",
            "mobile": "9333344445",
            "purpose": "Reading",
            "preferred_shift": "Evening",
            "followup_date": "2026-09-01",
            "remarks": "updated",
        },
        follow_redirects=True,
    )
    assert b"Enquiry updated successfully" in resp.data
    row = get_enquiry_by_id(eid)
    assert row["full_name"] == "Updated Name"


def test_edit_enquiry_nonexistent(logged_in_client):
    client, admin = logged_in_client
    resp = client.post(
        "/enquiries/edit/999999999",
        data={"full_name": "X", "mobile": "9000000000"},
        follow_redirects=True,
    )
    assert resp.status_code == 200


def test_delete_enquiry_success(logged_in_client):
    client, admin = logged_in_client
    make_enquiry(client)
    eid = get_last_enquiry_id(admin["admin_id"])
    resp = client.get(f"/enquiries/delete/{eid}", follow_redirects=True)
    assert b"Enquiry deleted successfully" in resp.data
    assert get_enquiry_by_id(eid) is None


def test_delete_enquiry_twice_is_idempotent_no_crash(logged_in_client):
    client, admin = logged_in_client
    make_enquiry(client)
    eid = get_last_enquiry_id(admin["admin_id"])
    client.get(f"/enquiries/delete/{eid}")
    resp = client.get(f"/enquiries/delete/{eid}", follow_redirects=True)
    assert resp.status_code == 200  # no crash on deleting already-deleted row


def test_delete_enquiry_via_get_no_csrf_confirmation(logged_in_client):
    """TD-14: delete runs on a plain GET with no confirmation - a crawler
    or prefetch could trigger deletion. Confirming this is still true."""
    client, admin = logged_in_client
    make_enquiry(client)
    eid = get_last_enquiry_id(admin["admin_id"])
    resp = client.get(f"/enquiries/delete/{eid}")
    assert resp.status_code == 302  # GET alone deletes, no confirm step
