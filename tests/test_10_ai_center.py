"""AI Center - Student Risk Analysis (Phase 1, rule-based retention scoring)."""
from datetime import date, timedelta

import pytest

from tests.conftest import (
    make_enquiry, get_last_enquiry_id, admit_student, get_last_student_id,
    create_membership, save_membership_settings,
)


def _admitted_student_with_membership(client, admin_id, **overrides):
    make_enquiry(client)
    eid = get_last_enquiry_id(admin_id)
    admit_student(client, eid)
    sid = get_last_student_id(admin_id)
    create_membership(client, sid, **overrides)
    return sid


def test_ai_center_requires_login(client):
    resp = client.get("/ai-center/", follow_redirects=False)
    assert resp.status_code == 302


def test_ai_center_empty_state_with_no_query(logged_in_client):
    client, admin = logged_in_client
    resp = client.get("/ai-center/")
    assert resp.status_code == 200
    assert b"Search for a student" in resp.data


def test_ai_center_suggestions_requires_login(client):
    resp = client.get("/ai-center/student-suggestions?q=anything")
    assert resp.status_code == 401
    assert resp.get_json() == []


def test_ai_center_suggestions_case_insensitive_partial_name_match(logged_in_client):
    client, admin = logged_in_client
    make_enquiry(client, full_name="Risk Analysis Search Target")
    eid = get_last_enquiry_id(admin["admin_id"])
    admit_student(client, eid)

    resp = client.get("/ai-center/student-suggestions?q=risk analysis")
    assert resp.status_code == 200
    names = [row["full_name"] for row in resp.get_json()]
    assert "Risk Analysis Search Target" in names


def test_ai_center_suggestions_partial_mobile_match(logged_in_client):
    client, admin = logged_in_client
    make_enquiry(client, full_name="Mobile Match Student", mobile="9123456780")
    eid = get_last_enquiry_id(admin["admin_id"])
    admit_student(client, eid)

    resp = client.get("/ai-center/student-suggestions?q=3456780")
    assert resp.status_code == 200
    mobiles = [row["mobile"] for row in resp.get_json()]
    assert "9123456780" in mobiles


def test_ai_center_suggestions_include_library_id_mobile_and_plan(logged_in_client):
    client, admin = logged_in_client
    save_membership_settings(client)  # Quarterly needs a configured, nonzero fee
    make_enquiry(client, full_name="Suggestion Fields Student", mobile="9123456781")
    eid = get_last_enquiry_id(admin["admin_id"])
    admit_student(client, eid)
    sid = get_last_student_id(admin["admin_id"])
    create_membership(client, sid, plan_name="Quarterly", duration="90", paid_amount="500", due_amount="0")

    resp = client.get("/ai-center/student-suggestions?q=Suggestion Fields")
    assert resp.status_code == 200
    rows = resp.get_json()
    assert len(rows) == 1
    row = rows[0]
    assert row["student_id"] == sid
    assert row["full_name"] == "Suggestion Fields Student"
    assert row["mobile"] == "9123456781"
    assert row["plan_name"] == "QUARTERLY"  # plan_name is a normalized Category field, stored UPPERCASE (ADR-36)


def test_ai_center_suggestions_student_with_no_membership_has_null_plan(logged_in_client):
    client, admin = logged_in_client
    make_enquiry(client, full_name="No Membership Yet Student")
    eid = get_last_enquiry_id(admin["admin_id"])
    admit_student(client, eid)

    resp = client.get("/ai-center/student-suggestions?q=No Membership Yet")
    rows = resp.get_json()
    assert len(rows) == 1
    assert rows[0]["plan_name"] is None


def test_ai_center_suggestions_returns_all_same_name_students(logged_in_client):
    """Ambiguous name -> every match comes back, none silently dropped."""
    client, admin = logged_in_client
    for mobile_suffix in ("1", "2", "3"):
        make_enquiry(client, full_name="Duplicate Name Student", mobile="912345678" + mobile_suffix)
        eid = get_last_enquiry_id(admin["admin_id"])
        admit_student(client, eid)

    resp = client.get("/ai-center/student-suggestions?q=Duplicate Name Student")
    rows = resp.get_json()
    assert len(rows) == 3
    assert {row["mobile"] for row in rows} == {"9123456781", "9123456782", "9123456783"}


def test_ai_center_high_risk_student_shows_score_and_reasons(logged_in_client):
    client, admin = logged_in_client
    today = date.today()

    sid = _admitted_student_with_membership(
        client, admin["admin_id"],
        duration="30",
        joining_date=(today - timedelta(days=40)).isoformat(),
        end_date=(today - timedelta(days=5)).isoformat(),
        paid_amount="200",
        due_amount="800",
    )

    resp = client.get(f"/ai-center/?student_id={sid}")
    assert resp.status_code == 200
    assert b"High Risk" in resp.data
    assert b"expired 5 days ago" in resp.data
    assert b"pending" in resp.data
    assert b"Not tracked yet" in resp.data  # no attendance log - honest gap, not fabricated


def test_ai_center_healthy_student_is_low_risk_with_no_reasons(logged_in_client):
    client, admin = logged_in_client
    today = date.today()

    sid = _admitted_student_with_membership(
        client, admin["admin_id"],
        duration="365",
        joining_date=today.isoformat(),
        end_date=(today + timedelta(days=365)).isoformat(),
        paid_amount="1000",
        due_amount="0",
    )

    resp = client.get(f"/ai-center/?student_id={sid}")
    assert resp.status_code == 200
    assert b"Low Risk" in resp.data
    assert b"No risk signals detected" in resp.data


# ---------------------------------------------------------------------------
# AI Center Settings (ADR-40) - weights/thresholds are database-backed, not
# hardcoded. `ai_center_settings` is a brand-new table this app cannot
# create itself (see the CREATE TABLE's comment in
# database/supabase_migration.sql) - the save/persistence tests below only
# pass once that table exists on the Supabase project the tests run
# against; the default-fallback and validation tests pass either way.
# ---------------------------------------------------------------------------

def test_ai_center_settings_requires_login(client):
    resp = client.get("/ai-center/settings", follow_redirects=False)
    assert resp.status_code == 302


def test_ai_center_settings_shows_defaults_when_never_saved(logged_in_client):
    client, admin = logged_in_client
    resp = client.get("/ai-center/settings")
    assert resp.status_code == 200
    assert b'value="45"' in resp.data
    assert b'value="35"' in resp.data
    assert b'value="20"' in resp.data
    assert b'value="40"' in resp.data
    assert b'value="70"' in resp.data


def test_ai_center_settings_rejects_weights_not_summing_to_100(logged_in_client):
    client, admin = logged_in_client
    resp = client.post(
        "/ai-center/settings",
        data={
            "weight_payment_delay": "50", "weight_renewal_history": "35",
            "weight_membership_duration": "20",  # sums to 105
            "high_risk_max": "40", "low_risk_min": "70",
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"must add up to 100" in resp.data


def test_ai_center_settings_rejects_inverted_thresholds(logged_in_client):
    client, admin = logged_in_client
    resp = client.post(
        "/ai-center/settings",
        data={
            "weight_payment_delay": "45", "weight_renewal_history": "35",
            "weight_membership_duration": "20",
            "high_risk_max": "70", "low_risk_min": "40",  # inverted
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"must be lower than the Low Risk number" in resp.data


def test_ai_center_settings_save_persists_and_changes_scoring(logged_in_client):
    """End-to-end: saving new weights actually changes a real student's
    computed score - proves Settings and the scoring engine share the same
    configuration, not two independent copies."""
    client, admin = logged_in_client
    today = date.today()

    # A student who is *only* short-plan risk (no pending balance, no
    # renewal risk) - membership_duration weight fully controls this score.
    sid = _admitted_student_with_membership(
        client, admin["admin_id"],
        duration="30",
        joining_date=today.isoformat(),
        end_date=(today + timedelta(days=25)).isoformat(),
        paid_amount="500", due_amount="0",
    )

    resp_before = client.get(f"/ai-center/?student_id={sid}")
    assert resp_before.status_code == 200

    save_resp = client.post(
        "/ai-center/settings",
        data={
            "weight_payment_delay": "10", "weight_renewal_history": "10",
            "weight_membership_duration": "80",  # crank up the only active signal
            "high_risk_max": "40", "low_risk_min": "70",
        },
        follow_redirects=True,
    )
    assert save_resp.status_code == 200
    if b"missing the ai_center_settings table" in save_resp.data:
        pytest.skip("ai_center_settings table not yet created on this Supabase project")

    assert b"Settings saved" in save_resp.data

    settings_resp = client.get("/ai-center/settings")
    assert b'value="80"' in settings_resp.data

    resp_after = client.get(f"/ai-center/?student_id={sid}")
    assert resp_after.status_code == 200
    assert resp_after.data != resp_before.data

