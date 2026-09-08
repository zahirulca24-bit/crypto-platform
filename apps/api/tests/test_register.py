import uuid
import pytest
from fastapi.testclient import TestClient
from main import app
from database import SessionLocal
from models import User

client = TestClient(app)


def test_successful_registration():
    unique_email = f"user_{uuid.uuid4().hex[:8]}@example.com"
    payload = {
        "email": unique_email,
        "password": "ValidPassword123",
        "display_name": "Test User",
        "timezone": "UTC",
        "base_currency": "USDT",
    }
    response = client.post("/v1/auth/register", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == unique_email
    assert data["display_name"] == "Test User"
    assert data["timezone"] == "UTC"
    assert data["base_currency"] == "USDT"
    assert data["status"] == "active"
    assert "id" in data
    assert "created_at" in data

    # Verify sensitive fields are NOT in response
    assert "password_hash" not in data
    assert "password" not in data
    assert "mfa_secret_encrypted" not in data

    # Verify DB row created and password hash stored securely
    db = SessionLocal()
    try:
        user_db = db.query(User).filter(User.email == unique_email).first()
        assert user_db is not None
        assert user_db.password_hash != "ValidPassword123"
        assert user_db.password_hash.startswith("$argon2id$")
    finally:
        db.close()


def test_duplicate_email_rejected():
    email = f"dup_{uuid.uuid4().hex[:8]}@example.com"
    payload = {
        "email": email,
        "password": "ValidPassword123",
    }
    resp1 = client.post("/v1/auth/register", json=payload)
    assert resp1.status_code == 201

    resp2 = client.post("/v1/auth/register", json=payload)
    assert resp2.status_code == 409
    assert resp2.json()["detail"] == "Email already registered"


def test_invalid_email_rejected():
    payload = {
        "email": "not-an-email",
        "password": "ValidPassword123",
    }
    response = client.post("/v1/auth/register", json=payload)
    assert response.status_code == 422


def test_short_password_rejected():
    payload = {
        "email": f"short_{uuid.uuid4().hex[:8]}@example.com",
        "password": "short",
    }
    response = client.post("/v1/auth/register", json=payload)
    assert response.status_code == 422


def test_health_endpoints_still_work():
    h_resp = client.get("/health")
    assert h_resp.status_code == 200
    assert h_resp.json() == {"status": "ok"}

    db_resp = client.get("/health/db")
    assert db_resp.status_code == 200
    assert db_resp.json() == {"status": "ok", "database": "connected"}


