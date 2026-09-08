import uuid
from datetime import timedelta
import pytest
import jwt
from fastapi.testclient import TestClient
from main import app
from database import SessionLocal
from models import User
from security import (
    hash_password,
    decode_access_token,
    create_access_token,
    JWT_SECRET_KEY,
    JWT_ALGORITHM,
)

client = TestClient(app)


def test_successful_login():
    email = f"login_user_{uuid.uuid4().hex[:8]}@example.com"
    password = "CorrectPassword123"

    # Register user first
    reg_resp = client.post(
        "/v1/auth/register",
        json={"email": email, "password": password},
    )
    assert reg_resp.status_code == 201

    # Login
    login_resp = client.post(
        "/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert login_resp.status_code == 200
    data = login_resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["expires_in"] == 1800

    # Decode and verify JWT claims
    decoded = decode_access_token(data["access_token"])
    assert "sub" in decoded
    assert decoded["type"] == "access"
    assert "iat" in decoded
    assert "exp" in decoded

    # Verify DB last_login_at and failed_login_count
    db = SessionLocal()
    try:
        user_db = db.query(User).filter(User.email == email).first()
        assert user_db is not None
        assert user_db.last_login_at is not None
        assert user_db.failed_login_count == 0
    finally:
        db.close()


def test_wrong_password_increments_failed_login_count():
    email = f"wrong_pwd_{uuid.uuid4().hex[:8]}@example.com"
    password = "CorrectPassword123"

    client.post(
        "/v1/auth/register",
        json={"email": email, "password": password},
    )

    login_resp = client.post(
        "/v1/auth/login",
        json={"email": email, "password": "WrongPassword456"},
    )
    assert login_resp.status_code == 401

    db = SessionLocal()
    try:
        user_db = db.query(User).filter(User.email == email).first()
        assert user_db.failed_login_count == 1
    finally:
        db.close()


def test_unknown_email_rejected():
    login_resp = client.post(
        "/v1/auth/login",
        json={"email": "nonexistent_user_999@example.com", "password": "SomePassword123"},
    )
    assert login_resp.status_code == 401


def test_disabled_user_rejected():
    email = f"disabled_{uuid.uuid4().hex[:8]}@example.com"
    password = "CorrectPassword123"

    db = SessionLocal()
    try:
        user = User(
            email=email,
            password_hash=hash_password(password),
            status="disabled",
        )
        db.add(user)
        db.commit()
    finally:
        db.close()

    login_resp = client.post(
        "/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert login_resp.status_code == 401
    assert login_resp.json()["detail"] == "Account is disabled"


def test_locked_user_rejected():
    email = f"locked_{uuid.uuid4().hex[:8]}@example.com"
    password = "CorrectPassword123"

    db = SessionLocal()
    try:
        user = User(
            email=email,
            password_hash=hash_password(password),
            status="locked",
        )
        db.add(user)
        db.commit()
    finally:
        db.close()

    login_resp = client.post(
        "/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert login_resp.status_code == 401
    assert login_resp.json()["detail"] == "Account is locked"


def test_successful_login_resets_failed_login_count():
    email = f"reset_count_{uuid.uuid4().hex[:8]}@example.com"
    password = "CorrectPassword123"

    client.post(
        "/v1/auth/register",
        json={"email": email, "password": password},
    )

    # Failed attempt
    client.post(
        "/v1/auth/login",
        json={"email": email, "password": "WrongPassword456"},
    )

    db = SessionLocal()
    try:
        user_db = db.query(User).filter(User.email == email).first()
        assert user_db.failed_login_count == 1
    finally:
        db.close()

    # Successful attempt
    succ_resp = client.post(
        "/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert succ_resp.status_code == 200

    db = SessionLocal()
    try:
        user_db = db.query(User).filter(User.email == email).first()
        assert user_db.failed_login_count == 0
    finally:
        db.close()


def test_expired_and_invalid_token_decode():
    # Expired token
    expired_token = create_access_token(
        {"sub": "test_user_id"},
        expires_delta=timedelta(seconds=-10),
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(expired_token)

    # Invalid token string
    with pytest.raises(jwt.PyJWTError):
        decode_access_token("invalid.token.value")

