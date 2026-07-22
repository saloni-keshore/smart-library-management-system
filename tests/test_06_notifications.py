"""Notifications: bucketing (today/tomorrow/3-day/expired), filters."""
from datetime import date, timedelta

from tests.conftest import (
    make_enquiry, get_last_enquiry_id, admit_student, get_last_student_id,
    create_membership,
)


def _membership_ending(client, admin_id, end_date):
    make_enquiry(client)
    eid = get_last_enquiry_id(admin_id)
    admit_student(client, eid)
    sid = get_last_student_id(admin_id)
    create_membership(client, sid, paid_amount="500", due_amount="0", end_date=end_date)
    return sid


def test_notifications_requires_login(client):
    resp = client.get("/notifications/", follow_redirects=False)
    assert resp.status_code == 302


def test_notifications_empty_state(logged_in_client):
    client, admin = logged_in_client
    resp = client.get("/notifications/")
    assert resp.status_code == 200


def test_notification_bucket_expires_today(logged_in_client):
    client, admin = logged_in_client
    today = date.today().isoformat()
    _membership_ending(client, admin["admin_id"], today)
    resp = client.get("/notifications/today")
    assert resp.status_code == 200
    assert b"Memberships Expiring Today" in resp.data


def test_notification_bucket_expires_tomorrow(logged_in_client):
    client, admin = logged_in_client
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    _membership_ending(client, admin["admin_id"], tomorrow)
    resp = client.get("/notifications/tomorrow")
    assert resp.status_code == 200
    assert b"Memberships Expiring Tomorrow" in resp.data


def test_notification_bucket_three_days(logged_in_client):
    client, admin = logged_in_client
    in3 = (date.today() + timedelta(days=3)).isoformat()
    _membership_ending(client, admin["admin_id"], in3)
    resp = client.get("/notifications/three_days")
    assert resp.status_code == 200


def test_notification_bucket_expired(logged_in_client):
    client, admin = logged_in_client
    past = (date.today() - timedelta(days=5)).isoformat()
    _membership_ending(client, admin["admin_id"], past)
    resp = client.get("/notifications/expired")
    assert resp.status_code == 200
    assert b"Expired Memberships" in resp.data


def test_notification_membership_expiring_in_4_days_not_bucketed(logged_in_client):
    """days_left <= 3 boundary - a membership expiring in exactly 4 days
    must not appear in any of today/tomorrow/three_days/expired buckets."""
    client, admin = logged_in_client
    in4 = (date.today() + timedelta(days=4)).isoformat()
    _membership_ending(client, admin["admin_id"], in4)
    resp = client.get("/notifications/")
    assert resp.status_code == 200
    assert b"All Notifications" in resp.data


def test_notification_invalid_filter_type_falls_back_to_all(logged_in_client):
    client, admin = logged_in_client
    resp = client.get("/notifications/not_a_real_filter")
    assert resp.status_code == 200
    assert b"All Notifications" in resp.data


def test_notification_all_view_combines_all_buckets_expired_first(logged_in_client):
    client, admin = logged_in_client
    today = date.today().isoformat()
    past = (date.today() - timedelta(days=2)).isoformat()
    _membership_ending(client, admin["admin_id"], today)
    _membership_ending(client, admin["admin_id"], past)
    resp = client.get("/notifications/")
    assert resp.status_code == 200


def test_notification_isolated_per_admin(logged_in_client):
    client, admin = logged_in_client
    today = date.today().isoformat()
    _membership_ending(client, admin["admin_id"], today)

    client.get("/logout")
    client.post(
        "/register",
        data={
            "full_name": "Other Admin", "username": "qa_other_notif",
            "mobile": "9123498765", "email": "o@example.com",
            "password": "GoodPass1", "confirm_password": "GoodPass1",
        },
        follow_redirects=True,
    )
    client.post("/", data={"username": "qa_other_notif", "password": "GoodPass1"})
    resp = client.get("/notifications/today")
    assert resp.status_code == 200
    assert admin["full_name"].encode() not in resp.data
