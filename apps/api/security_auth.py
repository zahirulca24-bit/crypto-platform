"""Authentication principal resolution and FastAPI authorization dependencies."""
from __future__ import annotations

from uuid import UUID
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import get_db
from security import decode_access_token
from security_policies import AuthorizationPolicy, POLICY_ROLES, Principal, UserRole

bearer = HTTPBearer(auto_error=False)


def authorize(principal: Principal, policy: AuthorizationPolicy) -> Principal:
    if principal.role not in POLICY_ROLES[policy]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"code":"authorization_denied","policy":policy.value})
    return principal


def current_principal(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> Principal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail={"code":"authentication_required"}, headers={"WWW-Authenticate":"Bearer"})
    try:
        payload = decode_access_token(credentials.credentials)
        subject = UUID(str(payload.get("sub", "")))
    except (ValueError, TypeError, jwt.PyJWTError):
        raise HTTPException(status_code=401, detail={"code":"invalid_access_token"}, headers={"WWW-Authenticate":"Bearer"})
    from models import User
    user = db.execute(select(User).where(User.id == subject)).scalar_one_or_none()
    if user is None or user.status != "active":
        raise HTTPException(status_code=401, detail={"code":"inactive_or_unknown_user"})
    try: role = UserRole(user.role)
    except ValueError: raise HTTPException(status_code=403, detail={"code":"invalid_user_role"})
    return Principal(user_id=user.id, role=role, email=user.email)


def require_policy(policy: AuthorizationPolicy):
    def dependency(principal: Principal = Depends(current_principal)) -> Principal:
        return authorize(principal, policy)
    return dependency
