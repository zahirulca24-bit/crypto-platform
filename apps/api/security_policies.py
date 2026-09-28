"""Pure authorization policy definitions (no database/runtime imports)."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from uuid import UUID

class UserRole(str, Enum):
    VIEWER="viewer"; RESEARCHER="researcher"; TRADER="trader"; OPERATOR="operator"; ADMIN="admin"

class AuthorizationPolicy(str, Enum):
    READ_AUTHENTICATED="read_authenticated"
    RESEARCH_MUTATION="research_mutation"
    TRADING_COMMAND="trading_command"
    SAFETY_COMMAND="safety_command"
    EXCHANGE_CREDENTIAL_CHANGE="exchange_credential_change"
    PRODUCTION_MODE_CHANGE="production_mode_change"
    OPERATIONS_MUTATION="operations_mutation"

POLICY_ROLES={
    AuthorizationPolicy.READ_AUTHENTICATED:frozenset(UserRole),
    AuthorizationPolicy.RESEARCH_MUTATION:frozenset({UserRole.RESEARCHER,UserRole.ADMIN}),
    AuthorizationPolicy.TRADING_COMMAND:frozenset({UserRole.TRADER,UserRole.OPERATOR,UserRole.ADMIN}),
    AuthorizationPolicy.SAFETY_COMMAND:frozenset({UserRole.OPERATOR,UserRole.ADMIN}),
    AuthorizationPolicy.EXCHANGE_CREDENTIAL_CHANGE:frozenset({UserRole.ADMIN}),
    AuthorizationPolicy.PRODUCTION_MODE_CHANGE:frozenset({UserRole.ADMIN}),
    AuthorizationPolicy.OPERATIONS_MUTATION:frozenset({UserRole.OPERATOR,UserRole.ADMIN}),
}

@dataclass(frozen=True)
class Principal:
    user_id: UUID
    role: UserRole
    email: str

def is_authorized(role: UserRole, policy: AuthorizationPolicy) -> bool:
    return role in POLICY_ROLES[policy]
