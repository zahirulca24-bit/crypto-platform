from security_auth import current_principal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy.orm import Session

from database import get_db
from exchange.credential_security import ExchangeCredentialService, SecurityAuditStore
from security_auth import AuthorizationPolicy, Principal, require_policy

router = APIRouter(prefix="/v1/security", tags=["security"], dependencies=[Depends(current_principal)])
admin_policy = require_policy(AuthorizationPolicy.EXCHANGE_CREDENTIAL_CHANGE)

class CredentialInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    exchange_id: str = Field(min_length=1, max_length=32, pattern=r"^[a-z0-9_-]+$")
    environment: str = Field(pattern=r"^(demo|live)$")
    api_key: SecretStr = Field(min_length=1, max_length=512)
    api_secret: SecretStr = Field(min_length=1, max_length=512)
    password: SecretStr | None = Field(default=None, min_length=1, max_length=512)

class CredentialMetadataResponse(BaseModel):
    id: UUID
    exchange_id: str
    environment: str
    api_key_fingerprint: str
    validation_status: str
    validated_at: object | None
    created_at: object
    updated_at: object

class ValidationResponse(BaseModel):
    exchange_id: str
    environment: str
    api_key_fingerprint: str
    authenticated: bool
    can_trade: bool
    supports_client_order_id: bool
    withdrawal_supported_by_application: bool
    reason_codes: list[str]


def credential_service(request: Request, db: Session = Depends(get_db)):
    return ExchangeCredentialService(db, encryption_key=request.app.state.settings.credential_encryption_key, timeout_ms=request.app.state.settings.exchange_timeout_ms)

def audit_store(db: Session = Depends(get_db)): return SecurityAuditStore(db)

@router.post("/exchange-credentials/validate", response_model=ValidationResponse)
def validate_credentials(payload: CredentialInput, request: Request, principal: Principal = Depends(admin_policy), service: ExchangeCredentialService = Depends(credential_service), audit: SecurityAuditStore = Depends(audit_store)):
    try:
        result = service.validate_transient(exchange_id=payload.exchange_id, environment=payload.environment, api_key=payload.api_key.get_secret_value(), api_secret=payload.api_secret.get_secret_value(), password=payload.password.get_secret_value() if payload.password else None)
    except Exception:
        audit.record(actor_user_id=principal.user_id, action="exchange_credentials.validate", outcome="failed", target_type="exchange_credential", target_id=f"{payload.environment}:{payload.exchange_id}", request_id=getattr(request.state,"request_id",None), context={"exchange_id":payload.exchange_id,"environment":payload.environment})
        raise HTTPException(status_code=400, detail={"code":"credential_validation_failed"})
    audit.record(actor_user_id=principal.user_id, action="exchange_credentials.validate", outcome="success", target_type="exchange_credential", target_id=f"{payload.environment}:{payload.exchange_id}", request_id=getattr(request.state,"request_id",None), context={"exchange_id":payload.exchange_id,"environment":payload.environment,"api_key_fingerprint":result["api_key_fingerprint"]})
    return result

@router.put("/exchange-credentials", response_model=CredentialMetadataResponse)
def put_credentials(payload: CredentialInput, request: Request, principal: Principal = Depends(admin_policy), service: ExchangeCredentialService = Depends(credential_service), audit: SecurityAuditStore = Depends(audit_store)):
    try:
        meta = service.store_validated(actor_user_id=principal.user_id, exchange_id=payload.exchange_id, environment=payload.environment, api_key=payload.api_key.get_secret_value(), api_secret=payload.api_secret.get_secret_value(), password=payload.password.get_secret_value() if payload.password else None)
    except Exception:
        audit.record(actor_user_id=principal.user_id, action="exchange_credentials.change", outcome="failed", target_type="exchange_credential", target_id=f"{payload.environment}:{payload.exchange_id}", request_id=getattr(request.state,"request_id",None), context={"exchange_id":payload.exchange_id,"environment":payload.environment})
        raise HTTPException(status_code=400, detail={"code":"credential_change_failed"})
    audit.record(actor_user_id=principal.user_id, action="exchange_credentials.change", outcome="success", target_type="exchange_credential", target_id=str(meta.id), request_id=getattr(request.state,"request_id",None), context={"exchange_id":meta.exchange_id,"environment":meta.environment,"api_key_fingerprint":meta.api_key_fingerprint})
    return meta

@router.get("/exchange-credentials", response_model=list[CredentialMetadataResponse])
def list_credentials(principal: Principal = Depends(admin_policy), service: ExchangeCredentialService = Depends(credential_service)):
    return service.list_metadata()

@router.delete("/exchange-credentials/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_credentials(credential_id: UUID, request: Request, principal: Principal = Depends(admin_policy), service: ExchangeCredentialService = Depends(credential_service), audit: SecurityAuditStore = Depends(audit_store)):
    if not service.delete(credential_id): raise HTTPException(status_code=404, detail={"code":"credential_not_found"})
    audit.record(actor_user_id=principal.user_id, action="exchange_credentials.delete", outcome="success", target_type="exchange_credential", target_id=str(credential_id), request_id=getattr(request.state,"request_id",None), context={})

@router.get("/audit-events")
def audit_events(limit: int=Query(100,ge=1,le=500), offset:int=Query(0,ge=0), principal: Principal=Depends(admin_policy), audit: SecurityAuditStore=Depends(audit_store)):
    return [{"id":str(r.id),"action":r.action,"outcome":r.outcome,"target_type":r.target_type,"target_id":r.target_id,"request_id":r.request_id,"context":r.context_json,"created_at":r.created_at} for r in audit.list(limit,offset)]
