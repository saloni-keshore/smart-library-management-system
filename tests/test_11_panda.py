"""Panda AI Assistant (Phase 1 - architecture + dummy responses, ADR-43).

panda_conversations/panda_messages are brand-new Supabase tables this app
cannot create itself (same shape as ai_center_settings, see
database/panda_queries.py) - chat-persistence tests below skip themselves
if the connected Supabase project doesn't have them yet. Insights,
suggested questions, and every validation/auth-guard check don't depend on
those tables and always run for real.
"""
import pytest

from tests.conftest import get_admin_by_username


def _register_and_login(client, suffix):
    import random
    import string

    creds = {
        "full_name": f"Panda Tester {suffix}",
        "username": f"qa_panda_{suffix}",
        "mobile": "9" + "".join(random.choices(string.digits, k=9)),
        "email": f"panda_{suffix}@example.com",
        "password": "PandaPass1",
        "confirm_password": "PandaPass1",
    }
    client.post("/register", data=creds, follow_redirects=True)
    client.post("/", data={"username": creds["username"], "password": creds["password"]}, follow_redirects=True)
    creds["admin_id"] = get_admin_by_username(creds["username"])["admin_id"]
    return creds


def _create_conversation(client):
    resp = client.post("/panda/conversations")
    if resp.status_code == 503:
        pytest.skip("panda_conversations/panda_messages tables not yet created on this Supabase project")
    assert resp.status_code == 201
    return resp.get_json()["conversation"]["conversation_id"]


# ---------------------------------------------------------------------------
# Auth guard
# ---------------------------------------------------------------------------

def test_insights_requires_login(client):
    resp = client.get("/panda/insights")
    assert resp.status_code == 401


def test_suggested_questions_requires_login(client):
    resp = client.get("/panda/suggested-questions")
    assert resp.status_code == 401


def test_conversations_list_requires_login(client):
    resp = client.get("/panda/conversations")
    assert resp.status_code == 401


def test_conversations_create_requires_login(client):
    resp = client.post("/panda/conversations")
    assert resp.status_code == 401


def test_messages_requires_login(client):
    resp = client.get("/panda/conversations/1/messages")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Insights + suggested questions
# ---------------------------------------------------------------------------

def test_insights_for_fresh_admin_only_flags_empty_seats(logged_in_client):
    """A brand-new admin has no revenue drop and no expiring memberships,
    but does have the default seating capacity (see
    database/bi_queries.py's get_shift_capacities) sitting at 0% occupied -
    genuinely underutilized, so panda/notifications.py's shift-utilization
    check is expected to fire; the revenue/membership checks should not."""
    client, admin = logged_in_client
    resp = client.get("/panda/insights")
    assert resp.status_code == 200
    insights = resp.get_json()["insights"]
    assert [item["type"] for item in insights] == ["occupancy"]


def test_suggested_questions_returns_static_list(logged_in_client):
    client, admin = logged_in_client
    resp = client.get("/panda/suggested-questions")
    assert resp.status_code == 200
    questions = resp.get_json()["questions"]
    assert len(questions) > 0
    assert all(isinstance(q, str) for q in questions)


# ---------------------------------------------------------------------------
# Chat: create / list / message / dummy reply
# ---------------------------------------------------------------------------

def test_create_and_list_conversation(logged_in_client):
    client, admin = logged_in_client
    conversation_id = _create_conversation(client)

    resp = client.get("/panda/conversations")
    assert resp.status_code == 200
    ids = [c["conversation_id"] for c in resp.get_json()["conversations"]]
    assert conversation_id in ids


def test_send_message_persists_and_returns_dummy_reply(logged_in_client):
    client, admin = logged_in_client
    conversation_id = _create_conversation(client)

    resp = client.post(
        f"/panda/conversations/{conversation_id}/messages",
        json={"message": "How many students do I have?"},
    )
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["user_message"]["role"] == "user"
    assert data["user_message"]["content"] == "How many students do I have?"
    assert data["assistant_message"]["role"] == "assistant"
    assert "not connected to a real" in data["assistant_message"]["content"]

    thread = client.get(f"/panda/conversations/{conversation_id}/messages")
    assert thread.status_code == 200
    roles = [m["role"] for m in thread.get_json()["messages"]]
    assert roles == ["user", "assistant"]


def test_conversation_title_set_from_first_user_message(logged_in_client):
    client, admin = logged_in_client
    conversation_id = _create_conversation(client)

    client.post(
        f"/panda/conversations/{conversation_id}/messages",
        json={"message": "What's my revenue trend?"},
    )

    resp = client.get("/panda/conversations")
    conversation = next(c for c in resp.get_json()["conversations"] if c["conversation_id"] == conversation_id)
    assert conversation["title"] == "What's my revenue trend?"


def test_empty_message_rejected(logged_in_client):
    client, admin = logged_in_client
    resp = client.post("/panda/conversations/999999/messages", json={"message": "   "})
    assert resp.status_code == 400


def test_message_over_length_limit_rejected(logged_in_client):
    client, admin = logged_in_client
    resp = client.post("/panda/conversations/999999/messages", json={"message": "x" * 2001})
    assert resp.status_code == 400


def test_message_to_nonexistent_conversation_returns_404_when_tables_exist(logged_in_client):
    client, admin = logged_in_client
    resp = client.post("/panda/conversations/999999/messages", json={"message": "hello"})
    if resp.status_code == 503:
        pytest.skip("panda_conversations/panda_messages tables not yet created on this Supabase project")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Cross-tenant isolation (IDOR) - same category of check as
# tests/test_08_cross_tenant_isolation.py, applied to Panda's own chat data.
# ---------------------------------------------------------------------------

def test_admin_b_cannot_read_admin_a_conversation(app):
    client_a = app.test_client()
    client_b = app.test_client()
    _register_and_login(client_a, "iso_a")
    _register_and_login(client_b, "iso_b")

    conversation_id = _create_conversation(client_a)
    client_a.post(
        f"/panda/conversations/{conversation_id}/messages",
        json={"message": "Admin A's private question"},
    )

    resp = client_b.get(f"/panda/conversations/{conversation_id}/messages")
    assert resp.status_code == 404


def test_admin_b_cannot_post_into_admin_a_conversation(app):
    client_a = app.test_client()
    client_b = app.test_client()
    _register_and_login(client_a, "iso_c")
    _register_and_login(client_b, "iso_d")

    conversation_id = _create_conversation(client_a)

    resp = client_b.post(
        f"/panda/conversations/{conversation_id}/messages",
        json={"message": "Admin B trying to inject a message"},
    )
    assert resp.status_code == 404

    thread = client_a.get(f"/panda/conversations/{conversation_id}/messages")
    assert thread.get_json()["messages"] == []


def test_admin_b_conversation_list_excludes_admin_a(app):
    client_a = app.test_client()
    client_b = app.test_client()
    _register_and_login(client_a, "iso_e")
    _register_and_login(client_b, "iso_f")

    conversation_id = _create_conversation(client_a)

    resp = client_b.get("/panda/conversations")
    ids = [c["conversation_id"] for c in resp.get_json()["conversations"]]
    assert conversation_id not in ids
