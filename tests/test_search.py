from tests.conftest import auth_headers, register_and_login


def _onboard_property(client, manager_token, *, name, lat, lng, rent, estate="Kilimani", amenities=None):
    headers = auth_headers(manager_token)
    resp = client.post(
        "/properties",
        json={
            "name": name,
            "type": "apartment_block",
            "lat": lat,
            "lng": lng,
            "estate": estate,
            "amenities": amenities or [],
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    property_id = resp.json()["id"]

    resp = client.post(
        f"/properties/{property_id}/units",
        json={"type": "1br", "rent": rent},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    unit_id = resp.json()["id"]
    return property_id, unit_id


def _approve_property(client, admin_token, property_id):
    resp = client.post(
        f"/admin/properties/{property_id}/verify",
        json={"approve": True},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200, resp.text


def test_favorite_add_list_remove_roundtrip(client):
    manager_token = register_and_login(client, "+254711000014", role="manager")
    property_id, unit_id = _onboard_property(
        client, manager_token, name="Fave Test Block", lat=-1.286, lng=36.817, rent=12000,
        amenities=["wifi"],
    )
    admin_token = register_and_login(client, "+254711000015", role="admin")
    _approve_property(client, admin_token, property_id)

    hunter_token = register_and_login(client, "+254711000016", role="hunter")
    headers = auth_headers(hunter_token)

    resp = client.post("/favorites", json={"unit_id": unit_id}, headers=headers)
    assert resp.status_code == 200

    listing = client.get("/favorites", headers=headers).json()
    assert len(listing) == 1
    assert listing[0]["unit_id"] == unit_id
    assert listing[0]["property_id"] == property_id
    assert listing[0]["property_name"] == "Fave Test Block"
    assert listing[0]["manager_phone"] == "+254711000014"

    # adding again is idempotent
    client.post("/favorites", json={"unit_id": unit_id}, headers=headers)
    assert len(client.get("/favorites", headers=headers).json()) == 1

    resp = client.delete(f"/favorites/{unit_id}", headers=headers)
    assert resp.status_code == 200
    assert client.get("/favorites", headers=headers).json() == []


def test_search_returns_zero_matches_when_nothing_fits(client):
    hunter_token = register_and_login(client, "+254711000001", role="hunter")
    resp = client.post(
        "/search",
        json={
            "commute_lat": -1.286389,
            "commute_lng": 36.817223,
            "max_commute_minutes": 30,
            "unit_type": "1br",
            "max_rent_kes": 10000,
            "amenities": [],
            "commute_mode": "matatu",
        },
        headers=auth_headers(hunter_token),
    )
    assert resp.status_code == 200
    assert resp.json()["match_count"] == 0


def test_unapproved_property_is_excluded_from_search(client):
    manager_token = register_and_login(client, "+254711000002", role="manager")
    _onboard_property(
        client, manager_token, name="Pending Towers", lat=-1.286, lng=36.817, rent=15000
    )
    # never approved by admin

    hunter_token = register_and_login(client, "+254711000003", role="hunter")
    resp = client.post(
        "/search",
        json={
            "commute_lat": -1.286389,
            "commute_lng": 36.817223,
            "max_commute_minutes": 60,
            "unit_type": "1br",
            "max_rent_kes": 50000,
            "amenities": [],
            "commute_mode": "matatu",
        },
        headers=auth_headers(hunter_token),
    )
    assert resp.json()["match_count"] == 0


def test_full_search_to_payment_to_results_flow(client):
    manager_token = register_and_login(client, "+254711000004", role="manager")
    property_id, unit_id = _onboard_property(
        client,
        manager_token,
        name="Kilimani Heights",
        lat=-1.286,
        lng=36.817,
        rent=15000,
        amenities=["wifi", "parking"],
    )

    admin_token = register_and_login(client, "+254711000005", role="admin")
    _approve_property(client, admin_token, property_id)

    hunter_token = register_and_login(client, "+254711000006", role="hunter")
    search_resp = client.post(
        "/search",
        json={
            "commute_lat": -1.286389,
            "commute_lng": 36.817223,
            "max_commute_minutes": 60,
            "unit_type": "1br",
            "max_rent_kes": 50000,
            "amenities": ["wifi"],
            "commute_mode": "matatu",
        },
        headers=auth_headers(hunter_token),
    )
    assert search_resp.status_code == 200
    body = search_resp.json()
    assert body["match_count"] == 1
    assert body["payment_status"] == "pending"
    search_id = body["search_id"]

    # Results are gated until payment.
    locked = client.get(f"/search/{search_id}/results", headers=auth_headers(hunter_token))
    assert locked.status_code == 402

    unlock = client.post(
        f"/search/{search_id}/unlock",
        json={"phone": "+254711000006"},
        headers=auth_headers(hunter_token),
    )
    assert unlock.status_code == 200
    assert unlock.json()["status"] == "success"

    results = client.get(f"/search/{search_id}/results", headers=auth_headers(hunter_token))
    assert results.status_code == 200
    data = results.json()
    assert len(data) == 1
    assert data[0]["rank"] == 1
    assert data[0]["property_id"] == property_id
    assert data[0]["unit_id"] == unit_id
    assert data[0]["manager_phone"] == "+254711000004"
    assert data[0]["property_lat"] == -1.286
    assert data[0]["property_lng"] == 36.817
    assert "wifi" in data[0]["matched_amenities"]


def test_closer_cheaper_property_ranks_first(client):
    manager_token = register_and_login(client, "+254711000007", role="manager")
    admin_token = register_and_login(client, "+254711000008", role="admin")

    # Property A: right at the commute anchor, cheap rent.
    prop_a, _ = _onboard_property(
        client, manager_token, name="Near & Cheap", lat=-1.286389, lng=36.817223, rent=10000
    )
    # Property B: far away, expensive rent.
    prop_b, _ = _onboard_property(
        client, manager_token, name="Far & Pricey", lat=-1.40, lng=36.95, rent=45000
    )
    _approve_property(client, admin_token, prop_a)
    _approve_property(client, admin_token, prop_b)

    hunter_token = register_and_login(client, "+254711000009", role="hunter")
    search_resp = client.post(
        "/search",
        json={
            "commute_lat": -1.286389,
            "commute_lng": 36.817223,
            "max_commute_minutes": 120,
            "unit_type": "1br",
            "max_rent_kes": 50000,
            "amenities": [],
            "commute_mode": "matatu",
        },
        headers=auth_headers(hunter_token),
    )
    body = search_resp.json()
    assert body["match_count"] == 2
    search_id = body["search_id"]

    client.post(
        f"/search/{search_id}/unlock", json={"phone": "+254711000009"}, headers=auth_headers(hunter_token)
    )
    results = client.get(f"/search/{search_id}/results", headers=auth_headers(hunter_token)).json()

    assert results[0]["property_id"] == prop_a
    assert results[0]["rank"] == 1
    assert results[1]["property_id"] == prop_b
    assert results[1]["rank"] == 2
    assert results[0]["overall_score"] > results[1]["overall_score"]


def test_cannot_unlock_someone_elses_search(client):
    manager_token = register_and_login(client, "+254711000010", role="manager")
    property_id, _ = _onboard_property(
        client, manager_token, name="Some Place", lat=-1.286, lng=36.817, rent=12000
    )
    admin_token = register_and_login(client, "+254711000011", role="admin")
    _approve_property(client, admin_token, property_id)

    hunter_a = register_and_login(client, "+254711000012", role="hunter")
    hunter_b = register_and_login(client, "+254711000013", role="hunter")

    search_id = client.post(
        "/search",
        json={
            "commute_lat": -1.286389, "commute_lng": 36.817223, "max_commute_minutes": 60,
            "unit_type": "1br", "max_rent_kes": 50000, "amenities": [], "commute_mode": "matatu",
        },
        headers=auth_headers(hunter_a),
    ).json()["search_id"]

    resp = client.post(
        f"/search/{search_id}/unlock", json={"phone": "+254711000013"}, headers=auth_headers(hunter_b)
    )
    assert resp.status_code == 404
