from tests.conftest import auth_headers, register_and_login


def test_property_onboarding_and_unit_creation(client):
    manager_token = register_and_login(client, "+254722000001", role="manager")
    headers = auth_headers(manager_token)

    resp = client.post(
        "/properties",
        json={
            "name": "Greenview Apartments",
            "type": "apartment_block",
            "lat": -1.29,
            "lng": 36.78,
            "estate": "Lavington",
            "sub_county": "Dagoretti",
            "county": "Nairobi",
            "amenities": ["parking", "cctv", "borehole_water"],
        },
        headers=headers,
    )
    assert resp.status_code == 200
    property_id = resp.json()["id"]
    assert resp.json()["status"] == "pending"

    resp = client.post(
        f"/properties/{property_id}/units",
        json={"type": "bedsitter", "rent": 7000, "deposit_months": 1, "water_deposit": 500},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["is_vacant"] is True

    resp = client.get(f"/properties/{property_id}/units", headers=headers)
    assert len(resp.json()) == 1


def test_adding_tenant_marks_unit_occupied_and_vacancy_dashboard_updates(client):
    manager_token = register_and_login(client, "+254722000002", role="manager")
    headers = auth_headers(manager_token)

    property_id = client.post(
        "/properties",
        json={"name": "Tenant Test Block", "type": "bedsitter_block", "lat": -1.3, "lng": 36.8},
        headers=headers,
    ).json()["id"]
    unit_id = client.post(
        f"/properties/{property_id}/units", json={"type": "bedsitter", "rent": 6000}, headers=headers
    ).json()["id"]

    resp = client.post(
        f"/units/{unit_id}/tenants",
        json={"name": "John Mwangi", "phone": "+254700111222", "move_in_date": "2026-01-01T00:00:00", "monthly_rent": 6000},
        headers=headers,
    )
    assert resp.status_code == 200

    unit = client.get(f"/properties/{property_id}/units", headers=headers).json()[0]
    assert unit["is_vacant"] is False

    tenants = client.get(f"/properties/{property_id}/tenants", headers=headers).json()
    assert len(tenants) == 1
    assert tenants[0]["name"] == "John Mwangi"


def test_archiving_tenant_marks_unit_vacant(client):
    manager_token = register_and_login(client, "+254722000003", role="manager")
    headers = auth_headers(manager_token)

    property_id = client.post(
        "/properties",
        json={"name": "Archive Test", "type": "bedsitter_block", "lat": -1.3, "lng": 36.8},
        headers=headers,
    ).json()["id"]
    unit_id = client.post(
        f"/properties/{property_id}/units", json={"type": "bedsitter", "rent": 6000}, headers=headers
    ).json()["id"]
    tenant_id = client.post(
        f"/units/{unit_id}/tenants",
        json={"name": "Mary Wanjiru", "phone": "+254700333444", "move_in_date": "2026-01-01T00:00:00", "monthly_rent": 6000},
        headers=headers,
    ).json()["id"]

    resp = client.post(f"/tenants/{tenant_id}/archive", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["is_active"] is False

    unit = client.get(f"/properties/{property_id}/units", headers=headers).json()[0]
    assert unit["is_vacant"] is True


def test_manager_cannot_access_other_managers_property(client):
    manager_a = register_and_login(client, "+254722000004", role="manager")
    manager_b = register_and_login(client, "+254722000005", role="manager")

    property_id = client.post(
        "/properties",
        json={"name": "Manager A Block", "type": "bedsitter_block", "lat": -1.3, "lng": 36.8},
        headers=auth_headers(manager_a),
    ).json()["id"]

    resp = client.post(
        f"/properties/{property_id}/units",
        json={"type": "bedsitter", "rent": 6000},
        headers=auth_headers(manager_b),
    )
    assert resp.status_code == 403


def test_vacancy_signal_created_when_hunter_with_linked_tenancy_searches(client):
    # Manager + property + tenant-occupied unit
    manager_token = register_and_login(client, "+254722000006", role="manager")
    property_id = client.post(
        "/properties",
        json={"name": "Linked Tenancy Block", "type": "bedsitter_block", "lat": -1.286, "lng": 36.817},
        headers=auth_headers(manager_token),
    ).json()["id"]
    unit_id = client.post(
        f"/properties/{property_id}/units", json={"type": "1br", "rent": 12000}, headers=auth_headers(manager_token)
    ).json()["id"]

    admin_token = register_and_login(client, "+254722000007", role="admin")
    client.post(f"/admin/properties/{property_id}/verify", json={"approve": True}, headers=auth_headers(admin_token))

    # Hunter links their current tenancy to that unit, then searches.
    hunter_token = register_and_login(client, "+254722000008", role="hunter")
    # (Hunter profile update endpoint not wired to a router in this slice;
    # set directly for the purposes of this test via raw DB access.)
    from app.database import SessionLocal
    from app.models import HunterProfile, User

    db = SessionLocal()
    user = db.query(User).filter(User.phone == "+254722000008").one()
    profile = db.get(HunterProfile, user.id)
    profile.current_tenancy_unit_id = unit_id
    db.commit()
    db.close()

    client.post(
        "/search",
        json={
            "commute_lat": -1.286389, "commute_lng": 36.817223, "max_commute_minutes": 60,
            "unit_type": "1br", "max_rent_kes": 50000, "amenities": [], "commute_mode": "matatu",
        },
        headers=auth_headers(hunter_token),
    )

    signals = client.get(
        f"/properties/{property_id}/vacancy-signals", headers=auth_headers(manager_token)
    ).json()
    assert len(signals) == 1
    assert signals[0]["status"] == "pending"
