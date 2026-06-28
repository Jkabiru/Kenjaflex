from tests.conftest import auth_headers, register_and_login


def test_get_hunter_profile_creates_one_if_missing(client):
    token = register_and_login(client, "+254755000001", role="hunter")
    resp = client.get("/hunter-profile", headers=auth_headers(token))
    assert resp.status_code == 200
    assert resp.json()["workplace_name"] is None


def test_update_hunter_profile_persists_workplace_and_tenancy(client):
    manager_token = register_and_login(client, "+254755000002", role="manager")
    property_id = client.post(
        "/properties",
        json={"name": "Test Block", "type": "bedsitter_block", "lat": -1.3, "lng": 36.8},
        headers=auth_headers(manager_token),
    ).json()["id"]
    unit_id = client.post(
        f"/properties/{property_id}/units", json={"type": "1br", "rent": 12000}, headers=auth_headers(manager_token)
    ).json()["id"]

    hunter_token = register_and_login(client, "+254755000003", role="hunter")
    resp = client.patch(
        "/hunter-profile",
        json={"workplace_name": "Two Rivers Mall", "workplace_lat": -1.21, "workplace_lng": 36.79, "current_tenancy_unit_id": unit_id},
        headers=auth_headers(hunter_token),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["workplace_name"] == "Two Rivers Mall"
    assert body["current_tenancy_unit_id"] == unit_id

    # confirm it persisted (a second GET reflects the update, not just the response echo)
    again = client.get("/hunter-profile", headers=auth_headers(hunter_token)).json()
    assert again["workplace_name"] == "Two Rivers Mall"


def test_update_own_name(client):
    token = register_and_login(client, "+254755000004", role="hunter", name="Original Name")
    resp = client.patch("/auth/me", json={"name": "Updated Name"}, headers=auth_headers(token))
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated Name"

    me = client.get("/auth/me", headers=auth_headers(token)).json()
    assert me["name"] == "Updated Name"


def test_hunter_profile_requires_hunter_role(client):
    manager_token = register_and_login(client, "+254755000005", role="manager")
    resp = client.get("/hunter-profile", headers=auth_headers(manager_token))
    assert resp.status_code == 403
