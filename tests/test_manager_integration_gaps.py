from tests.conftest import auth_headers, register_and_login


def test_update_kyc_persists_id_and_company(client):
    token = register_and_login(client, "+254766000001", role="manager")
    resp = client.patch(
        "/auth/me/kyc",
        json={"id_or_business_number": "30112233", "company_name": "Mwangi Properties Ltd"},
        headers=auth_headers(token),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id_or_business_number"] == "30112233"
    assert body["company_name"] == "Mwangi Properties Ltd"

    me = client.get("/auth/me", headers=auth_headers(token)).json()
    assert me["id_or_business_number"] == "30112233"


def test_record_full_tenant_payment_clears_arrears(client):
    manager_token = register_and_login(client, "+254766000002", role="manager")
    headers = auth_headers(manager_token)
    property_id = client.post(
        "/properties",
        json={"name": "Arrears Block", "type": "bedsitter_block", "lat": -1.3, "lng": 36.8},
        headers=headers,
    ).json()["id"]
    unit_id = client.post(
        f"/properties/{property_id}/units", json={"type": "bedsitter", "rent": 6000}, headers=headers
    ).json()["id"]
    tenant_id = client.post(
        f"/units/{unit_id}/tenants",
        json={"name": "Brian Otieno", "phone": "+254712334110", "move_in_date": "2025-03-01T00:00:00", "monthly_rent": 6000},
        headers=headers,
    ).json()["id"]

    # manually set arrears via a second partial payment scenario
    from app.database import SessionLocal
    from app.models import Tenant

    db = SessionLocal()
    t = db.get(Tenant, tenant_id)
    t.arrears = 3500
    db.commit()
    db.close()

    resp = client.post(f"/tenants/{tenant_id}/record-payment", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["arrears"] == 0


def test_record_partial_tenant_payment(client):
    manager_token = register_and_login(client, "+254766000003", role="manager")
    headers = auth_headers(manager_token)
    property_id = client.post(
        "/properties",
        json={"name": "Partial Pay Block", "type": "bedsitter_block", "lat": -1.3, "lng": 36.8},
        headers=headers,
    ).json()["id"]
    unit_id = client.post(
        f"/properties/{property_id}/units", json={"type": "bedsitter", "rent": 6000}, headers=headers
    ).json()["id"]
    tenant_id = client.post(
        f"/units/{unit_id}/tenants",
        json={"name": "Mary Wanjiru", "phone": "+254712000000", "move_in_date": "2025-03-01T00:00:00", "monthly_rent": 6000},
        headers=headers,
    ).json()["id"]

    from app.database import SessionLocal
    from app.models import Tenant

    db = SessionLocal()
    t = db.get(Tenant, tenant_id)
    t.arrears = 3500
    db.commit()
    db.close()

    resp = client.post(f"/tenants/{tenant_id}/record-payment?amount=1000", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["arrears"] == 2500


def test_property_leads_reflects_unlocked_searches(client):
    manager_token = register_and_login(client, "+254766000004", role="manager")
    headers = auth_headers(manager_token)
    property_id = client.post(
        "/properties",
        json={"name": "Lead Test Block", "type": "bedsitter_block", "lat": -1.286, "lng": 36.817},
        headers=headers,
    ).json()["id"]
    client.post(f"/properties/{property_id}/units", json={"type": "1br", "rent": 12000}, headers=headers)

    admin_token = register_and_login(client, "+254766000005", role="admin")
    client.post(f"/admin/properties/{property_id}/verify", json={"approve": True}, headers=auth_headers(admin_token))

    # zero leads before any hunter unlocks a search containing this property
    before = client.get(f"/properties/{property_id}/leads", headers=headers).json()
    assert before["leads_30d"] == 0

    hunter_token = register_and_login(client, "+254766000006", role="hunter")
    search_id = client.post(
        "/search",
        json={
            "commute_lat": -1.286389, "commute_lng": 36.817223, "max_commute_minutes": 60,
            "unit_type": "1br", "max_rent_kes": 50000, "amenities": [], "commute_mode": "matatu",
        },
        headers=auth_headers(hunter_token),
    ).json()["search_id"]
    client.post(f"/search/{search_id}/unlock", json={"phone": "+254766000006"}, headers=auth_headers(hunter_token))

    after = client.get(f"/properties/{property_id}/leads", headers=headers).json()
    assert after["leads_30d"] == 1


def test_leads_endpoint_requires_property_ownership(client):
    manager_a = register_and_login(client, "+254766000007", role="manager")
    manager_b = register_and_login(client, "+254766000008", role="manager")
    property_id = client.post(
        "/properties",
        json={"name": "Owned By A", "type": "bedsitter_block", "lat": -1.3, "lng": 36.8},
        headers=auth_headers(manager_a),
    ).json()["id"]

    resp = client.get(f"/properties/{property_id}/leads", headers=auth_headers(manager_b))
    assert resp.status_code == 403
