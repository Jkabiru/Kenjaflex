"""Tests for the remaining gap endpoints:
- GET /field-agent/captures/{id}
- GET /field-agent/payouts
- GET/POST/DELETE /admin/amenities
- GET /admin/field-agent/captures?status=
- GET /admin/revenue?range=
"""
from tests.conftest import auth_headers, register_and_login


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _verified_agent(client, phone):
    from app.database import SessionLocal
    from app.models import AgentVerificationStatus, User

    token = register_and_login(client, phone, role="field_agent")
    db = SessionLocal()
    user = db.query(User).filter(User.phone == phone).one()
    user.agent_verification_status = AgentVerificationStatus.verified
    db.commit()
    db.close()
    return token


def _submit_capture(client, agent_token, *, lat=-1.30, lng=36.80):
    return client.post(
        "/field-agent/capture",
        json={
            "property_name": "Test Block", "unit_count": 4,
            "estimated_rent_min": 5000, "estimated_rent_max": 8000,
            "gps_lat": lat, "gps_lng": lng,
            "photos": ["a.jpg", "b.jpg", "c.jpg"],
        },
        headers=auth_headers(agent_token),
    ).json()


def _setup_paid_search(client, hunter_token, manager_token, admin_token):
    prop_id = client.post(
        "/properties",
        json={"name": "Revenue Block", "type": "bedsitter_block", "lat": -1.30, "lng": 36.80},
        headers=auth_headers(manager_token),
    ).json()["id"]
    client.post(f"/admin/properties/{prop_id}/verify", json={"approve": True}, headers=auth_headers(admin_token))
    client.post(f"/properties/{prop_id}/units", json={"type": "bedsitter", "rent": 6000}, headers=auth_headers(manager_token))
    search_id = client.post(
        "/search",
        json={"commute_lat": -1.286, "commute_lng": 36.817, "max_commute_minutes": 60,
              "unit_type": "bedsitter", "max_rent_kes": 8000, "amenities": [], "commute_mode": "matatu"},
        headers=auth_headers(hunter_token),
    ).json()["search_id"]
    hunter_phone = client.get("/auth/me", headers=auth_headers(hunter_token)).json()["phone"]
    client.post(f"/search/{search_id}/unlock", json={"phone": hunter_phone}, headers=auth_headers(hunter_token))
    return search_id


# ---------------------------------------------------------------------------
# GET /field-agent/captures/{id}
# ---------------------------------------------------------------------------

def test_capture_detail_returns_own_capture(client):
    agent_token = _verified_agent(client, "+254760000001")
    capture = _submit_capture(client, agent_token)

    resp = client.get(f"/field-agent/captures/{capture['id']}", headers=auth_headers(agent_token))
    assert resp.status_code == 200
    assert resp.json()["id"] == capture["id"]
    assert resp.json()["status"] == "under_review"


def test_capture_detail_returns_404_for_another_agents_capture(client):
    agent1_token = _verified_agent(client, "+254760000002")
    agent2_token = _verified_agent(client, "+254760000003")

    capture = _submit_capture(client, agent1_token, lat=-1.31, lng=36.81)

    resp = client.get(f"/field-agent/captures/{capture['id']}", headers=auth_headers(agent2_token))
    assert resp.status_code == 404


def test_capture_detail_returns_404_for_nonexistent(client):
    agent_token = _verified_agent(client, "+254760000004")
    resp = client.get("/field-agent/captures/9999", headers=auth_headers(agent_token))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /field-agent/payouts
# ---------------------------------------------------------------------------

def test_payout_history_empty_initially(client):
    agent_token = _verified_agent(client, "+254760000005")
    resp = client.get("/field-agent/payouts", headers=auth_headers(agent_token))
    assert resp.status_code == 200
    assert resp.json() == []


def test_payout_history_appears_after_successful_payout(client):
    phone = "+254760000006"
    agent_token = _verified_agent(client, phone)
    admin_token = register_and_login(client, "+254760000007", role="admin")

    capture = _submit_capture(client, agent_token)
    client.post(
        f"/admin/field-agent/captures/{capture['id']}/review?approve=true",
        headers=auth_headers(admin_token),
    )

    client.post("/field-agent/payout", json={"phone": phone}, headers=auth_headers(agent_token))

    resp = client.get("/field-agent/payouts", headers=auth_headers(agent_token))
    assert resp.status_code == 200
    payouts = resp.json()
    assert len(payouts) == 1
    assert payouts[0]["amount"] == 500
    assert payouts[0]["status"] == "success"


# ---------------------------------------------------------------------------
# GET/POST/DELETE /admin/amenities
# ---------------------------------------------------------------------------

def test_amenities_lifecycle(client):
    admin_token = register_and_login(client, "+254760000008", role="admin")

    assert client.get("/admin/amenities", headers=auth_headers(admin_token)).json() == []

    resp = client.post("/admin/amenities", json={"name": "wifi"}, headers=auth_headers(admin_token))
    assert resp.status_code == 201
    amenity_id = resp.json()["id"]
    assert resp.json()["name"] == "wifi"

    client.post("/admin/amenities", json={"name": "parking"}, headers=auth_headers(admin_token))
    listing = client.get("/admin/amenities", headers=auth_headers(admin_token)).json()
    assert len(listing) == 2
    assert [a["name"] for a in listing] == ["parking", "wifi"]  # alpha order

    resp = client.delete(f"/admin/amenities/{amenity_id}", headers=auth_headers(admin_token))
    assert resp.status_code == 204
    assert len(client.get("/admin/amenities", headers=auth_headers(admin_token)).json()) == 1


def test_duplicate_amenity_returns_409(client):
    admin_token = register_and_login(client, "+254760000009", role="admin")
    client.post("/admin/amenities", json={"name": "borehole_water"}, headers=auth_headers(admin_token))
    resp = client.post("/admin/amenities", json={"name": "borehole_water"}, headers=auth_headers(admin_token))
    assert resp.status_code == 409


def test_delete_nonexistent_amenity_returns_404(client):
    admin_token = register_and_login(client, "+254760000010", role="admin")
    resp = client.delete("/admin/amenities/9999", headers=auth_headers(admin_token))
    assert resp.status_code == 404


def test_non_admin_cannot_manage_amenities(client):
    manager_token = register_and_login(client, "+254760000011", role="manager")
    resp = client.get("/admin/amenities", headers=auth_headers(manager_token))
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /admin/field-agent/captures?status=
# ---------------------------------------------------------------------------

def test_admin_captures_list_filters_by_status(client):
    agent_token = _verified_agent(client, "+254760000012")
    admin_token = register_and_login(client, "+254760000013", role="admin")

    capture = _submit_capture(client, agent_token)

    under_review = client.get(
        "/admin/field-agent/captures?status=under_review", headers=auth_headers(admin_token)
    ).json()
    assert len(under_review) == 1
    assert under_review[0]["status"] == "under_review"

    client.post(
        f"/admin/field-agent/captures/{capture['id']}/review?approve=true",
        headers=auth_headers(admin_token),
    )

    resolved = client.get(
        "/admin/field-agent/captures?status=approved", headers=auth_headers(admin_token)
    ).json()
    assert len(resolved) == 1
    assert resolved[0]["status"] == "approved"

    # Still nothing under review
    assert client.get(
        "/admin/field-agent/captures?status=under_review", headers=auth_headers(admin_token)
    ).json() == []


def test_admin_captures_list_no_filter_returns_all(client):
    agent_token = _verified_agent(client, "+254760000014")
    admin_token = register_and_login(client, "+254760000015", role="admin")

    _submit_capture(client, agent_token, lat=-1.40, lng=36.90)
    capture2 = _submit_capture(client, agent_token, lat=-1.50, lng=37.00)
    client.post(
        f"/admin/field-agent/captures/{capture2['id']}/review?approve=true",
        headers=auth_headers(admin_token),
    )

    all_captures = client.get("/admin/field-agent/captures", headers=auth_headers(admin_token)).json()
    assert len(all_captures) == 2


# ---------------------------------------------------------------------------
# GET /admin/revenue?range=
# ---------------------------------------------------------------------------

def test_revenue_empty_database(client):
    admin_token = register_and_login(client, "+254760000016", role="admin")
    resp = client.get("/admin/revenue", headers=auth_headers(admin_token))
    assert resp.status_code == 200
    data = resp.json()
    assert data["search_unlock_revenue_kes"] == 0
    assert data["field_agent_payout_outflow_kes"] == 0
    assert data["net_kes"] == 0
    assert data["transactions"] == []


def test_revenue_includes_search_unlock_payment(client):
    admin_token = register_and_login(client, "+254760000017", role="admin")
    manager_token = register_and_login(client, "+254760000018", role="manager")
    hunter_token = register_and_login(client, "+254760000019", role="hunter")

    _setup_paid_search(client, hunter_token, manager_token, admin_token)

    data = client.get("/admin/revenue?range=7", headers=auth_headers(admin_token)).json()
    assert data["period_days"] == 7
    assert data["search_unlock_revenue_kes"] == 250.0
    assert data["field_agent_payout_outflow_kes"] == 0
    assert data["net_kes"] == 250.0
    assert len(data["transactions"]) == 1
    assert data["transactions"][0]["type"] == "search_unlock"


def test_revenue_includes_field_agent_payout(client):
    phone = "+254760000020"
    agent_token = _verified_agent(client, phone)
    admin_token = register_and_login(client, "+254760000021", role="admin")

    capture = _submit_capture(client, agent_token)
    client.post(
        f"/admin/field-agent/captures/{capture['id']}/review?approve=true",
        headers=auth_headers(admin_token),
    )
    client.post("/field-agent/payout", json={"phone": phone}, headers=auth_headers(agent_token))

    data = client.get("/admin/revenue?range=30", headers=auth_headers(admin_token)).json()
    assert data["field_agent_payout_outflow_kes"] == 500.0
    assert data["net_kes"] == -500.0
    payout_txns = [t for t in data["transactions"] if t["type"] == "field_agent_payout"]
    assert len(payout_txns) == 1


def test_revenue_invalid_range_returns_400(client):
    admin_token = register_and_login(client, "+254760000022", role="admin")
    resp = client.get("/admin/revenue?range=14", headers=auth_headers(admin_token))
    assert resp.status_code == 400
