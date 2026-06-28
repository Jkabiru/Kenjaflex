from tests.conftest import auth_headers, register_and_login


def test_verification_queue_and_approve_reject(client):
    manager_token = register_and_login(client, "+254744000001", role="manager")
    admin_token = register_and_login(client, "+254744000002", role="admin")

    p1 = client.post(
        "/properties",
        json={"name": "Queue Block A", "type": "bedsitter_block", "lat": -1.3, "lng": 36.8},
        headers=auth_headers(manager_token),
    ).json()["id"]
    p2 = client.post(
        "/properties",
        json={"name": "Queue Block B", "type": "bedsitter_block", "lat": -1.31, "lng": 36.81},
        headers=auth_headers(manager_token),
    ).json()["id"]

    queue = client.get("/admin/properties/pending", headers=auth_headers(admin_token)).json()
    assert {p["id"] for p in queue} == {p1, p2}

    resp = client.post(
        f"/admin/properties/{p1}/verify", json={"approve": True}, headers=auth_headers(admin_token)
    )
    assert resp.json()["status"] == "approved"

    resp = client.post(
        f"/admin/properties/{p2}/verify",
        json={"approve": False, "reason": "Photos unclear"},
        headers=auth_headers(admin_token),
    )
    assert resp.json()["status"] == "rejected"
    assert resp.json()["rejection_reason"] == "Photos unclear"

    queue_after = client.get("/admin/properties/pending", headers=auth_headers(admin_token)).json()
    assert queue_after == []


def test_non_admin_cannot_access_verification_queue(client):
    manager_token = register_and_login(client, "+254744000003", role="manager")
    resp = client.get("/admin/properties/pending", headers=auth_headers(manager_token))
    assert resp.status_code == 403


def test_executive_dashboard_reflects_state(client):
    manager_token = register_and_login(client, "+254744000004", role="manager")
    admin_token = register_and_login(client, "+254744000005", role="admin")

    property_id = client.post(
        "/properties",
        json={"name": "Dashboard Block", "type": "bedsitter_block", "lat": -1.3, "lng": 36.8},
        headers=auth_headers(manager_token),
    ).json()["id"]
    client.post(f"/admin/properties/{property_id}/verify", json={"approve": True}, headers=auth_headers(admin_token))

    unit_id = client.post(
        f"/properties/{property_id}/units", json={"type": "bedsitter", "rent": 6000}, headers=auth_headers(manager_token)
    ).json()["id"]
    client.post(
        f"/units/{unit_id}/tenants",
        json={"name": "Tenant One", "phone": "+254700555666", "move_in_date": "2026-01-01T00:00:00", "monthly_rent": 6000},
        headers=auth_headers(manager_token),
    )

    dashboard = client.get("/admin/dashboard", headers=auth_headers(admin_token)).json()
    assert dashboard["total_properties"] == 1
    assert dashboard["total_units"] == 1
    assert dashboard["occupied_units"] == 1
    assert dashboard["vacant_units"] == 0
    assert dashboard["occupancy_rate_pct"] == 100.0


# ---------------------------------------------------------------------------
# Estate CRUD
# ---------------------------------------------------------------------------

def test_list_estates_empty(client):
    admin_token = register_and_login(client, "+254744000010", role="admin")
    resp = client.get("/admin/estates", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_and_list_estate(client):
    admin_token = register_and_login(client, "+254744000011", role="admin")
    resp = client.post(
        "/admin/estates",
        json={"name": "Kilimani", "sub_county": "Dagoretti", "county": "Nairobi", "avg_food_spend_monthly_kes": 12000},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Kilimani"
    assert data["avg_food_spend_monthly_kes"] == 12000
    assert "id" in data

    estates = client.get("/admin/estates", headers=auth_headers(admin_token)).json()
    assert len(estates) == 1
    assert estates[0]["name"] == "Kilimani"


def test_create_duplicate_estate_returns_409(client):
    admin_token = register_and_login(client, "+254744000012", role="admin")
    payload = {"name": "Westlands", "avg_food_spend_monthly_kes": 15000}
    client.post("/admin/estates", json=payload, headers=auth_headers(admin_token))
    resp = client.post("/admin/estates", json=payload, headers=auth_headers(admin_token))
    assert resp.status_code == 409


def test_delete_estate(client):
    admin_token = register_and_login(client, "+254744000013", role="admin")
    estate_id = client.post(
        "/admin/estates",
        json={"name": "Kasarani", "avg_food_spend_monthly_kes": 8000},
        headers=auth_headers(admin_token),
    ).json()["id"]

    resp = client.delete(f"/admin/estates/{estate_id}", headers=auth_headers(admin_token))
    assert resp.status_code == 204

    estates = client.get("/admin/estates", headers=auth_headers(admin_token)).json()
    assert estates == []


def test_delete_nonexistent_estate_returns_404(client):
    admin_token = register_and_login(client, "+254744000014", role="admin")
    resp = client.delete("/admin/estates/9999", headers=auth_headers(admin_token))
    assert resp.status_code == 404


def test_non_admin_cannot_manage_estates(client):
    manager_token = register_and_login(client, "+254744000015", role="manager")
    resp = client.get("/admin/estates", headers=auth_headers(manager_token))
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Field Agent KYC queue
# ---------------------------------------------------------------------------

def test_pending_kyc_queue_lists_new_agents(client):
    admin_token = register_and_login(client, "+254744000020", role="admin")
    register_and_login(client, "+254744000021", role="field_agent", name="Agent Alice")
    register_and_login(client, "+254744000022", role="field_agent", name="Agent Bob")

    pending = client.get(
        "/admin/field-agents?status=pending", headers=auth_headers(admin_token)
    ).json()
    assert len(pending) == 2
    assert all(a["agent_verification_status"] == "pending" for a in pending)


def test_admin_can_verify_field_agent(client):
    admin_token = register_and_login(client, "+254744000023", role="admin")
    register_and_login(client, "+254744000024", role="field_agent", name="Agent Carol")
    agent_id = client.get(
        "/admin/field-agents?status=pending", headers=auth_headers(admin_token)
    ).json()[0]["id"]

    resp = client.post(f"/admin/field-agents/{agent_id}/verify", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    assert resp.json()["agent_verification_status"] == "verified"

    pending = client.get(
        "/admin/field-agents?status=pending", headers=auth_headers(admin_token)
    ).json()
    assert pending == []


def test_admin_can_reject_field_agent_with_reason(client):
    admin_token = register_and_login(client, "+254744000025", role="admin")
    register_and_login(client, "+254744000026", role="field_agent", name="Agent Dave")
    agent_id = client.get(
        "/admin/field-agents", headers=auth_headers(admin_token)
    ).json()[0]["id"]

    resp = client.post(
        f"/admin/field-agents/{agent_id}/reject",
        json={"reason": "Student ID photo is blurry"},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["agent_verification_status"] == "rejected"
    assert data["agent_verification_rejection_reason"] == "Student ID photo is blurry"


def test_rejected_agent_resubmits_by_updating_name(client):
    """Updating name while rejected flips status back to pending."""
    admin_token = register_and_login(client, "+254744000027", role="admin")
    agent_token = register_and_login(client, "+254744000028", role="field_agent", name="Agent Eve")
    agent_id = client.get("/admin/field-agents", headers=auth_headers(admin_token)).json()[0]["id"]

    client.post(
        f"/admin/field-agents/{agent_id}/reject",
        json={"reason": "Cannot read ID"},
        headers=auth_headers(admin_token),
    )

    resp = client.patch(
        "/field-agent/profile", json={"name": "Agent Eve Updated"}, headers=auth_headers(agent_token)
    )
    assert resp.status_code == 200
    assert resp.json()["agent_verification_status"] == "pending"
    assert resp.json()["agent_verification_rejection_reason"] is None


def test_unverified_agent_blocked_from_capture(client):
    agent_token = register_and_login(client, "+254744000029", role="field_agent")
    resp = client.post(
        "/field-agent/capture",
        json={
            "property_name": "Test", "unit_count": 2,
            "estimated_rent_min": 5000, "estimated_rent_max": 8000,
            "gps_lat": -1.31, "gps_lng": 36.85,
            "photos": ["a.jpg", "b.jpg", "c.jpg"],
        },
        headers=auth_headers(agent_token),
    )
    assert resp.status_code == 403


def test_field_agent_profile_endpoint(client):
    agent_token = register_and_login(client, "+254744000030", role="field_agent", name="Agent Frank")
    resp = client.get("/field-agent/profile", headers=auth_headers(agent_token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["agent_verification_status"] == "pending"
    assert data["name"] == "Agent Frank"


# ---------------------------------------------------------------------------
# Analytics (Decision 3 — search event logging)
# ---------------------------------------------------------------------------

def _setup_search(client, hunter_token, manager_token, admin_token, *, estate="Kilimani", unit_type="bedsitter", unlock=False):
    property_id = client.post(
        "/properties",
        json={"name": f"{estate} Block", "type": "bedsitter_block",
              "lat": -1.286, "lng": 36.817, "estate": estate},
        headers=auth_headers(manager_token),
    ).json()["id"]
    client.post(f"/admin/properties/{property_id}/verify", json={"approve": True}, headers=auth_headers(admin_token))
    client.post(
        f"/properties/{property_id}/units",
        json={"type": unit_type, "rent": 6000},
        headers=auth_headers(manager_token),
    )
    search_id = client.post(
        "/search",
        json={"commute_lat": -1.286, "commute_lng": 36.817, "max_commute_minutes": 60,
              "unit_type": unit_type, "max_rent_kes": 8000, "amenities": [], "commute_mode": "matatu"},
        headers=auth_headers(hunter_token),
    ).json()["search_id"]
    if unlock:
        hunter_phone = client.get("/auth/me", headers=auth_headers(hunter_token)).json()["phone"]
        client.post(f"/search/{search_id}/unlock", json={"phone": hunter_phone}, headers=auth_headers(hunter_token))
    return search_id


def test_analytics_searches_total_and_conversion(client):
    admin_token = register_and_login(client, "+254744000031", role="admin")
    manager_token = register_and_login(client, "+254744000032", role="manager")
    hunter_token = register_and_login(client, "+254744000033", role="hunter")

    _setup_search(client, hunter_token, manager_token, admin_token, unlock=False)
    _setup_search(client, hunter_token, manager_token, admin_token, estate="Westlands", unlock=True)

    resp = client.get("/admin/analytics", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["searches_total"] == 2
    assert data["paid_searches"] == 1
    assert data["search_to_payment_conversion_pct"] == 50.0


def test_analytics_top_unit_types_from_search_events(client):
    admin_token = register_and_login(client, "+254744000034", role="admin")
    manager_token = register_and_login(client, "+254744000035", role="manager")
    hunter_token = register_and_login(client, "+254744000036", role="hunter")

    _setup_search(client, hunter_token, manager_token, admin_token, unit_type="bedsitter")
    _setup_search(client, hunter_token, manager_token, admin_token, estate="Lavington", unit_type="bedsitter")

    data = client.get("/admin/analytics", headers=auth_headers(admin_token)).json()
    types = {t["unit_type"]: t["count"] for t in data["top_unit_types"]}
    assert types.get("bedsitter", 0) == 2


def test_analytics_top_estates_from_search_results(client):
    admin_token = register_and_login(client, "+254744000037", role="admin")
    manager_token = register_and_login(client, "+254744000038", role="manager")
    hunter_token = register_and_login(client, "+254744000039", role="hunter")

    _setup_search(client, hunter_token, manager_token, admin_token, estate="Kasarani")
    _setup_search(client, hunter_token, manager_token, admin_token, estate="Kasarani")

    data = client.get("/admin/analytics", headers=auth_headers(admin_token)).json()
    estates = {e["estate"]: e["count"] for e in data["top_estates"]}
    assert estates.get("Kasarani", 0) == 2


def test_analytics_searches_by_hour_has_correct_shape(client):
    admin_token = register_and_login(client, "+254744000040", role="admin")
    manager_token = register_and_login(client, "+254744000041", role="manager")
    hunter_token = register_and_login(client, "+254744000042", role="hunter")

    _setup_search(client, hunter_token, manager_token, admin_token)

    data = client.get("/admin/analytics", headers=auth_headers(admin_token)).json()
    by_hour = data["searches_by_hour"]
    assert isinstance(by_hour, list)
    assert len(by_hour) >= 1
    assert all("hour" in h and "count" in h for h in by_hour)
    assert all(0 <= h["hour"] <= 23 for h in by_hour)
    assert sum(h["count"] for h in by_hour) == data["searches_total"]
