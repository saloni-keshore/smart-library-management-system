"""Dashboard: soft onboarding message for a fresh admin.

Guidance only - a fresh admin must never be blocked, redirected, or gated
away from any route. The message just nudges them toward Settings and
disappears on its own once Library Profile has been saved (see
routes/dashboard.py's show_setup_message / routes/setting.py's
session["library_setup_done"])."""

SETUP_MESSAGE_TEXT = "Complete your library setup"


def _save_library_profile(client, **overrides):
    data = {
        "library_name": "Test Library",
        "owner_name": "Test Owner",
        "phone": "9876543210",
    }
    data.update(overrides)
    return client.post("/settings/library", data=data, follow_redirects=True)


def test_fresh_admin_sees_setup_message(logged_in_client):
    client, _ = logged_in_client
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert SETUP_MESSAGE_TEXT in resp.get_data(as_text=True)


def test_setup_message_links_to_settings_page(logged_in_client):
    client, _ = logged_in_client
    body = client.get("/dashboard").get_data(as_text=True)
    assert 'href="/settings/"' in body


def test_settings_link_reaches_settings_page_normally(logged_in_client):
    client, _ = logged_in_client
    resp = client.get("/settings/")
    assert resp.status_code == 200


def test_fresh_admin_not_blocked_from_dashboard_or_other_routes(logged_in_client):
    client, _ = logged_in_client
    for path in ("/dashboard", "/enquiries/", "/students/", "/settings/"):
        resp = client.get(path, follow_redirects=False)
        assert resp.status_code == 200, f"{path} unexpectedly blocked/redirected for a fresh admin"


def test_configured_admin_does_not_see_setup_message(logged_in_client):
    client, _ = logged_in_client
    _save_library_profile(client)
    body = client.get("/dashboard").get_data(as_text=True)
    assert SETUP_MESSAGE_TEXT not in body


def test_setup_message_is_not_a_permanent_recurring_reminder(logged_in_client):
    client, _ = logged_in_client

    assert SETUP_MESSAGE_TEXT in client.get("/dashboard").get_data(as_text=True)

    _save_library_profile(client)

    # Gone immediately after saving, and stays gone on later loads too -
    # not just suppressed for the one response right after the POST.
    assert SETUP_MESSAGE_TEXT not in client.get("/dashboard").get_data(as_text=True)
    assert SETUP_MESSAGE_TEXT not in client.get("/dashboard").get_data(as_text=True)
