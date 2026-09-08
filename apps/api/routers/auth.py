from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import select

from database import get_db
from models import User
from schemas import RegisterRequest, UserResponse, LoginRequest, TokenResponse
from security import (
    hash_password,
    validate_password,
    verify_password,
    create_access_token,
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES,
)

router = APIRouter(prefix="/v1/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
def register(request: RegisterRequest, db: Session = Depends(get_db)):
    normalized_email = request.email.strip().lower()

    # Validate password using security utility
    try:
        validate_password(request.password)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        )

    # Check for duplicate email
    existing_user = db.execute(
        select(User).where(User.email == normalized_email)
    ).scalar_one_or_none()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    # Hash password using Argon2id
    hashed_pwd = hash_password(request.password)

    # Create user record
    user = User(
        email=normalized_email,
        password_hash=hashed_pwd,
        display_name=request.display_name,
        timezone=request.timezone or "UTC",
        base_currency=request.base_currency or "USDT",
        status="active",
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    return user


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
)
def login(request: LoginRequest, db: Session = Depends(get_db)):
    normalized_email = request.email.strip().lower()

    user = db.execute(
        select(User).where(User.email == normalized_email)
    ).scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if user.status == "disabled":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is disabled",
        )

    if user.status == "locked":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is locked",
        )

    if not verify_password(request.password, user.password_hash):
        user.failed_login_count += 1
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    # Reset failed login count and update last_login_at
    user.failed_login_count = 0
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()

    access_token = create_access_token({"sub": str(user.id)})
    expires_in = JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=expires_in,
    )
