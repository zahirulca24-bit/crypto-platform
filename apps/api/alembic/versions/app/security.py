import os
from datetime import datetime, timedelta, timezone
from typing import Optional, Any
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError

ph = PasswordHasher()

JWT_SECRET_KEY = os.getenv(
    "JWT_SECRET_KEY", "dev_secret_key_change_in_production_987654321"
)
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_ACCESS_TOKEN_EXPIRE_MINUTES = int(
    os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "30")
)


def validate_password(plain_password: str) -> None:
    """
    Validate basic password input constraints:
    - Minimum 8 characters
    - Maximum 128 characters
    - Reject empty password
    """
    if not plain_password:
        raise ValueError("Password cannot be empty.")
    if len(plain_password) < 8:
        raise ValueError("Password must be at least 8 characters long.")
    if len(plain_password) > 128:
        raise ValueError("Password must not exceed 128 characters.")


def hash_password(plain_password: str) -> str:
    """
    Hash a plaintext password using Argon2id.
    """
    validate_password(plain_password)
    return ph.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """
    Verify a plaintext password against an Argon2id password hash.
    Never logs or stores plaintext passwords.
    """
    if not plain_password or not password_hash:
        return False
    try:
        return ph.verify(password_hash, plain_password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def create_access_token(
    data: dict[str, Any],
    expires_delta: Optional[timedelta] = None,
) -> str:
    """
    Create a signed JWT access token with sub, type='access', iat, and exp claims.
    """
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update(
        {
            "type": "access",
            "iat": int(now.timestamp()),
            "exp": int(expire.timestamp()),
        }
    )

    encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> dict[str, Any]:
    """
    Decode and validate a JWT access token.
    Raises jwt.PyJWTError if invalid or expired.
    """
    payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
    if payload.get("type") != "access":
        raise jwt.PyJWTError("Invalid token type")
    return payload
