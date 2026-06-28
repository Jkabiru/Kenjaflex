from tests.conftest import auth_headers, register_and_login


def _setup_paid_search(client, hunter_token, manager_token, admin_token):
    """Create and approve a property, run a search, unlock it. Returns search_id."""
    property_id = client.post(
        "/properties",
        json={"name": "Dispute Test Block", "type": "bedsitter_block", "lat": -1.30, "lng": 36.80},
        headers=auth_headers(manager_token),
    ).json()["id"]
    client.post(f"/admin/properties/{property_id}/verify", json={"approve": True}, headers=auth_headers(admin_token))
    client.post(
        f"/properties/{property_id}/units",
        json={"type": "bedsitter", "rent": 6000},
        headers=auth_headers(manager_token),
    )

    search_id = client.post(
        "/search",
        json={
            "commute_lat": -1.286, "commute_lng": 36.817,
            "max_commute_minutes": 60, "unit_type": "bedsitter",
            "max_rent_kes": 8000, "amenities": [], "commute_mode": "matatu",
        },
        headers=auth_headers(hunter_token),
    ).json()["search_id"]

    hunter_phone = client.get("/auth/me", headers=auth_headers(hunter_token)).json()["phone"]
    client.post(
        f"/search/{search_id}/unlock",
        json={"phone": hunter_phone},
        headers=auth_headers(hunter_token),
    )
    return search_id


def test_hunter_can_file_dispute_on_paid_search(client):
    hunter_token = register_and_login(client, "+254755000001", role="hunter")
    manager_token = register_and_login(client, "+254755000002", role="manager")
    admin_token = register_and_login(client, "+254755000003", role="admin")

    search_id = _setup_paid_search(client, hunter_token, manager_token, admin_token)

    resp = client.post(
        "/hunter/disputes",
        json={"search_id": search_id, "reason": "Listing was taken down after I matched"},
        headers=auth_headers(hunter_token),
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["search_id"] == search_id
    assert data["status"] == "pending"
    assert data["resolution"] is None
    assert data["amount"] == 250  # SEARCH_UNLOCK_FEE_KES


def test_duplicate_dispute_returns_409(client):
    hunter_token = register_and_login(client, "+254755000004", role="hunter")
    manager_token = register_and_login(client, "+254755000005", role="manager")
    admin_token = register_and_login(client, "+254755000006", role="admin")

    search_id = _setup_paid_search(client, hunter_token, manager_token, admin_token)
    client.post(
        "/hunter/disputes",
        json={"search_id": search_id, "reason": "First dispute"},
        headers=auth_headers(hunter_token),
    )
    resp = client.post(
        "/hunter/disputes",
        json={"search_id": search_id, "reason": "Second dispute"},
        headers=auth_headers(hunter_token),
    )
    assert resp.status_code == 409


def test_unpaid_search_cannot_be_disputed(client):
    hunter_token = register_and_login(client, "+254755000007", role="hunter")
    manager_token = register_and_login(client, "+254755000008", role="manager")
    admin_token = register_and_login(client, "+254755000009", role="admin")

    property_id = client.post(
        "/properties",
        json={"name": "Block X", "type": "bedsitter_block", "lat": -1.30, "lng": 36.80},
        headers=auth_headers(manager_token),
    ).json()["id"]
    client.post(f"/admin/properties/{property_id}/verify", json={"approve": True}, headers=auth_headers(admin_token))
    client.post(
        f"/properties/{property_id}/units",
        json={"type": "bedsitter", "rent": 6000},
        headers=auth_headers(manager_token),
    )

    search_id = client.post(
        "/search",
        json={
            "commute_lat": -1.286, "commute_lng": 36.817,
            "max_commute_minutes": 60, "unit_type": "bedsitter",
            "max_rent_kes": 8000, "amenities": [], "commute_mode": "matatu",
        },
        headers=auth_headers(hunter_token),
    ).json()["search_id"]

    resp = client.post(
        "/hunter/disputes",
        json={"search_id": search_id, "reason": "Not paid yet"},
        headers=auth_headers(hunter_token),
    )
    assert resp.status_code == 400


def test_hunter_cannot_dispute_another_hunters_search(client):
    hunter1_token = register_and_login(client, "+254755000010", role="hunter")
    hunter2_token = register_and_login(client, "+254755000011", role="hunter")
    manager_token = register_and_login(client, "+254755000012", role="manager")
    admin_token = register_and_login(client, "+254755000013", role="admin")

    search_id = _setup_paid_search(client, hunter1_token, manager_token, admin_token)

    resp = client.post(
        "/hunter/disputes",
        json={"search_id": search_id, "reason": "Not my search"},
        headers=auth_headers(hunter2_token),
    )
    assert resp.status_code == 404


def test_admin_can_approve_dispute_and_refund(client):
    hunter_token = register_and_login(client, "+254755000014", role="hunter")
    manager_token = register_and_login(client, "+254755000015", role="manager")
    admin_token = register_and_login(client, "+254755000016", role="admin")

    search_id = _setup_paid_search(client, hunter_token, manager_token, admin_token)
    dispute_id = client.post(
        "/hunter/disputes",
        json={"search_id": search_id, "reason": "0 usable results"},
        headers=auth_headers(hunter_token),
    ).json()["id"]

    resp = client.post(
        f"/admin/disputes/{dispute_id}/resolve",
        json={"approve": True},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "resolved"
    assert data["resolution"] == "refunded"


def test_admin_can_deny_dispute(client):
    hunter_token = register_and_login(client, "+254755000017", role="hunter")
    manager_token = register_and_login(client, "+254755000018", role="manager")
    admin_token = register_and_login(client, "+254755000019", role="admin")

    search_id = _setup_paid_search(client, hunter_token, manager_token, admin_token)
    dispute_id = client.post(
        "/hunter/disputes",
        json={"search_id": search_id, "reason": "Changed my mind"},
        headers=auth_headers(hunter_token),
    ).json()["id"]

    resp = client.post(
        f"/admin/disputes/{dispute_id}/resolve",
        json={"approve": False},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "resolved"
    assert data["resolution"] == "denied"


def test_resolving_already_resolved_dispute_returns_409(client):
    hunter_token = register_and_login(client, "+254755000020", role="hunter")
    manager_token = register_and_login(client, "+254755000021", role="manager")
    admin_token = register_and_login(client, "+254755000022", role="admin")

    search_id = _setup_paid_search(client, hunter_token, manager_token, admin_token)
    dispute_id = client.post(
        "/hunter/disputes",
        json={"search_id": search_id, "reason": "Test"},
        headers=auth_headers(hunter_token),
    ).json()["id"]
    client.post(f"/admin/disputes/{dispute_id}/resolve", json={"approve": False}, headers=auth_headers(admin_token))

    resp = client.post(
        f"/admin/disputes/{dispute_id}/resolve",
        json={"approve": True},
        headers=auth_headers(admin_token),
    )
    assert resp.status_code == 409


def test_admin_disputes_list_filters_by_status(client):
    hunter_token = register_and_login(client, "+254755000023", role="hunter")
    manager_token = register_and_login(client, "+254755000024", role="manager")
    admin_token = register_and_login(client, "+254755000025", role="admin")

    search_id = _setup_paid_search(client, hunter_token, manager_token, admin_token)
    client.post(
        "/hunter/disputes",
        json={"search_id": search_id, "reason": "Test"},
        headers=auth_headers(hunter_token),
    )

    pending = client.get("/admin/disputes?status=pending", headers=auth_headers(admin_token)).json()
    assert len(pending) == 1

    resolved = client.get("/admin/disputes?status=resolved", headers=auth_headers(admin_token)).json()
    assert resolved == []


def test_hunter_can_list_own_disputes(client):
    hunter_token = register_and_login(client, "+254755000026", role="hunter")
    manager_token = register_and_login(client, "+254755000027", role="manager")
    admin_token = register_and_login(client, "+254755000028", role="admin")

    search_id = _setup_paid_search(client, hunter_token, manager_token, admin_token)
    client.post(
        "/hunter/disputes",
        json={"search_id": search_id, "reason": "Bad results"},
        headers=auth_headers(hunter_token),
    )

    resp = client.get("/hunter/disputes", headers=auth_headers(hunter_token))
    assert resp.status_code == 200
    assert len(resp.json()) == 1
