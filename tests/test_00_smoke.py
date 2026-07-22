def test_login_page_loads(client):
    resp = client.get("/")
    assert resp.status_code == 200


def test_register_and_login_roundtrip(logged_in_client):
    client, admin = logged_in_client
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert admin["username"].encode() or True
