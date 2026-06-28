import os

os.environ["DATABASE_URL"] = "sqlite:///./test_kejaflix.db"
os.environ["OTP_DEBUG_ECHO"] = "true"
os.environ["MPESA_MOCK_MODE"] = "true"
os.environ["JWT_SECRET"] = "test-secret"

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.database import Base, engine
from app.main import app

get_settings.cache_clear()


@pytest.fixture(autouse=True)
def fresh_db():
    """Recreate all tables before every test for full isolation."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture
def client():
    return TestClient(app)


def register_and_login(client: TestClient, phone: str, role: str = "hunter", name: str = "Test User") -> str:
    """Registers a user, verifies via the debug-echoed OTP, and returns a
    bearer access token."""
    resp = client.post("/auth/register", json={"phone": phone, "name": name, "role": role})
    assert resp.status_code == 200, resp.text
    otp = resp.json()["debug_otp"]

    resp = client.post("/auth/verify-otp", json={"phone": phone, "code": otp})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
