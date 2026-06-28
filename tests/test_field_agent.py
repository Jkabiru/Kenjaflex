from tests.conftest import auth_headers, register_and_login


def _verify_agent_as_student(phone: str):
    from app.database import SessionLocal
    from app.models import AgentVerificationStatus, User

    db = SessionLocal()
    user = db.query(User).filter(User.phone == phone).one()
    user.agent_verification_status = AgentVerificationStatus.verified
    db.commit()
    db.close()


def test_capture_requires_min_three_photos(client):
    phone = "+254733000001"
    token = register_and_login(client, phone, role="field_agent")
    _verify_agent_as_student(phone)

    resp = client.post(
        "/field-agent/capture",
        json={
            "property_name": "Roadside Bedsitters",
            "unit_count": 6,
            "estimated_rent_min": 5000,
            "estimated_rent_max": 7000,
            "gps_lat": -1.31,
            "gps_lng": 36.85,
            "photos": ["a.jpg", "b.jpg"],
        },
        headers=auth_headers(token),
    )
    assert resp.status_code == 400


def test_unverified_agent_cannot_submit_capture(client):
    token = register_and_login(client, "+254733000002", role="field_agent")
    resp = client.post(
        "/field-agent/capture",
        json={
            "property_name": "X", "unit_count": 1, "estimated_rent_min": 1000, "estimated_rent_max": 2000,
            "gps_lat": -1.31, "gps_lng": 36.85, "photos": ["a.jpg", "b.jpg", "c.jpg"],
        },
        headers=auth_headers(token),
    )
    assert resp.status_code == 403


def test_successful_capture_and_admin_approval_credits_reward(client):
    phone = "+254733000003"
    agent_token = register_and_login(client, phone, role="field_agent")
    _verify_agent_as_student(phone)

    capture = client.post(
        "/field-agent/capture",
        json={
            "property_name": "New Block", "unit_count": 4, "estimated_rent_min": 6000, "estimated_rent_max": 9000,
            "manager_contact": "+254700999888",
            "gps_lat": -1.32, "gps_lng": 36.86, "photos": ["a.jpg", "b.jpg", "c.jpg"],
        },
        headers=auth_headers(agent_token),
    ).json()
    assert capture["status"] == "under_review"

    admin_token = register_and_login(client, "+254733000004", role="admin")
    review = client.post(
        f"/admin/field-agent/captures/{capture['id']}/review?approve=true",
        headers=auth_headers(admin_token),
    )
    assert review.status_code == 200
    assert review.json()["status"] == "approved"
    assert review.json()["reward_amount"] == 500

    earnings = client.get("/field-agent/earnings", headers=auth_headers(agent_token)).json()
    assert earnings["total_approved_captures"] == 1
    assert earnings["total_earned_kes"] == 500
    assert earnings["available_balance_kes"] == 500


def test_duplicate_capture_within_20m_of_approved_property_auto_rejected(client):
    # Create + approve a property at a known location.
    manager_token = register_and_login(client, "+254733000005", role="manager")
    property_id = client.post(
        "/properties",
        json={"name": "Existing Block", "type": "bedsitter_block", "lat": -1.300000, "lng": 36.800000},
        headers=auth_headers(manager_token),
    ).json()["id"]
    admin_token = register_and_login(client, "+254733000006", role="admin")
    client.post(f"/admin/properties/{property_id}/verify", json={"approve": True}, headers=auth_headers(admin_token))

    phone = "+254733000007"
    agent_token = register_and_login(client, phone, role="field_agent")
    _verify_agent_as_student(phone)

    # ~5m away (well within the 20m duplicate radius).
    capture = client.post(
        "/field-agent/capture",
        json={
            "property_name": "Existing Block Duplicate", "unit_count": 6,
            "estimated_rent_min": 5000, "estimated_rent_max": 7000,
            "gps_lat": -1.300040, "gps_lng": 36.800000,
            "photos": ["a.jpg", "b.jpg", "c.jpg"],
        },
        headers=auth_headers(agent_token),
    ).json()
    assert capture["status"] == "rejected"
    assert "20m" in capture["admin_notes"]


def test_payout_below_minimum_threshold_rejected(client):
    phone = "+254733000008"
    agent_token = register_and_login(client, phone, role="field_agent")
    resp = client.post("/field-agent/payout", json={"phone": phone}, headers=auth_headers(agent_token))
    assert resp.status_code == 400


def test_payout_above_threshold_succeeds_in_mock_mode(client):
    phone = "+254733000009"
    agent_token = register_and_login(client, phone, role="field_agent")
    _verify_agent_as_student(phone)

    capture = client.post(
        "/field-agent/capture",
        json={
            "property_name": "Payout Test Block", "unit_count": 2,
            "estimated_rent_min": 4000, "estimated_rent_max": 5000,
            "gps_lat": -1.5, "gps_lng": 37.0, "photos": ["a.jpg", "b.jpg", "c.jpg"],
        },
        headers=auth_headers(agent_token),
    ).json()
    admin_token = register_and_login(client, "+254733000010", role="admin")
    client.post(
        f"/admin/field-agent/captures/{capture['id']}/review?approve=true",
        headers=auth_headers(admin_token),
    )

    payout = client.post("/field-agent/payout", json={"phone": phone}, headers=auth_headers(agent_token))
    assert payout.status_code == 200
    assert payout.json()["status"] == "success"
    assert payout.json()["amount"] == 500

    earnings = client.get("/field-agent/earnings", headers=auth_headers(agent_token)).json()
    assert earnings["available_balance_kes"] == 0
