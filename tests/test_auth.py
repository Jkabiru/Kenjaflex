from tests.conftest import auth_headers, register_and_login


def test_register_creates_user_and_sends_otp(client):
    resp = client.post("/auth/register", json={"phone": "+254700000001", "name": "Jane", "role": "hunter"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["message"] == "OTP sent"
    assert data["debug_otp"] is not None
    assert len(data["debug_otp"]) == 6


def test_verify_otp_with_wrong_code_fails(client):
    client.post("/auth/register", json={"phone": "+254700000002", "name": "Jane"})
    resp = client.post("/auth/verify-otp", json={"phone": "+254700000002", "code": "000000"})
    assert resp.status_code == 400


def test_verify_otp_with_correct_code_issues_token(client):
    token = register_and_login(client, "+254700000003")
    assert token

    resp = client.get("/auth/me", headers=auth_headers(token))
    assert resp.status_code == 200
    assert resp.json()["phone"] == "+254700000003"
    assert resp.json()["is_verified"] is True


def test_unauthenticated_request_is_rejected(client):
    resp = client.get("/auth/me")
    assert resp.status_code == 401


def test_role_gated_endpoint_rejects_wrong_role(client):
    hunter_token = register_and_login(client, "+254700000004", role="hunter")
    resp = client.post(
        "/properties",
        json={"name": "Test Apt", "type": "apartment_block", "lat": -1.28, "lng": 36.82},
        headers=auth_headers(hunter_token),
    )
    assert resp.status_code == 403
