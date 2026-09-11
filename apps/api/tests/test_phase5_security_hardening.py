from pathlib import Path
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet

from exchange.credential_security import CredentialCipher, CredentialEncryptionUnavailable, api_key_fingerprint
from packages.observability.logging import redact
from security import configure_security, create_access_token, decode_access_token
from security_policies import AuthorizationPolicy, UserRole, is_authorized
from settings import AppSettings

ROOT = Path(__file__).resolve().parents[3] if len(Path(__file__).resolve().parents) > 3 else Path(__file__).resolve().parent.parent
API = ROOT / "apps" / "api" if (ROOT / "apps" / "api").exists() else ROOT
WEB = ROOT / "apps" / "web"


def test_explicit_sensitive_authorization_policies_are_least_privilege():
    assert is_authorized(UserRole.TRADER, AuthorizationPolicy.TRADING_COMMAND)
    assert not is_authorized(UserRole.RESEARCHER, AuthorizationPolicy.TRADING_COMMAND)
    assert is_authorized(UserRole.OPERATOR, AuthorizationPolicy.SAFETY_COMMAND)
    assert not is_authorized(UserRole.TRADER, AuthorizationPolicy.SAFETY_COMMAND)
    assert is_authorized(UserRole.ADMIN, AuthorizationPolicy.EXCHANGE_CREDENTIAL_CHANGE)
    assert not is_authorized(UserRole.OPERATOR, AuthorizationPolicy.EXCHANGE_CREDENTIAL_CHANGE)
    assert is_authorized(UserRole.ADMIN, AuthorizationPolicy.PRODUCTION_MODE_CHANGE)
    assert not is_authorized(UserRole.TRADER, AuthorizationPolicy.PRODUCTION_MODE_CHANGE)


def test_credential_ciphertext_and_fingerprint_do_not_expose_plaintext():
    key = Fernet.generate_key().decode("ascii")
    cipher = CredentialCipher(key)
    secret = "ULTRA_PRIVATE_EXCHANGE_SECRET_123456"
    api_key = "LIVE_API_KEY_abcdef123456"
    encrypted = cipher.encrypt(secret)
    assert secret.encode() not in encrypted
    assert cipher.decrypt(encrypted) == secret
    fingerprint = api_key_fingerprint(api_key)
    assert api_key not in fingerprint
    assert fingerprint.startswith("sha256:")
    assert len(fingerprint) == len("sha256:") + 16


def test_missing_encryption_key_fails_closed():
    with pytest.raises(CredentialEncryptionUnavailable):
        CredentialCipher("")


def test_secret_redaction_covers_exchange_and_auth_material():
    secret = "TOP_SECRET_999"
    value = redact({
        "api_key": "abc",
        "api_secret": secret,
        "authorization": "Bearer token.value",
        "nested": {"password": "pw"},
        "message": f"api_key=abc secret={secret} token=xyz",
    })
    rendered = repr(value)
    assert secret not in rendered and "token.value" not in rendered
    assert "abc" not in value["api_key"]
    assert "[REDACTED]" in rendered


def test_production_cors_and_public_environment_secret_names_fail_validation():
    base = {
        "RUNTIME_MODE": "production",
        "TRADING_MODE": "disabled",
        "DATABASE_URL": "postgresql://prod_user:prod_password@db.internal:5432/platform",
        "REDIS_URL": "rediss://cache.internal:6379/0",
        "JWT_SECRET_KEY": "x" * 48,
        "CORS_ALLOW_ORIGINS": "*",
        "NEXT_PUBLIC_EXCHANGE_API_KEY": "must-never-be-public",
    }
    settings = AppSettings.from_env(base)
    codes = {r.code for r in settings.validation_reasons()}
    assert "production_wildcard_cors_forbidden" in codes
    assert "production_https_cors_required" in codes
    assert "public_environment_secret_name_forbidden" in codes


def test_production_rejects_plaintext_exchange_credentials_in_environment():
    settings = AppSettings.from_env({
        "RUNTIME_MODE": "production",
        "TRADING_MODE": "disabled",
        "DATABASE_URL": "postgresql://prod_user:prod_password@db.internal:5432/platform",
        "REDIS_URL": "rediss://cache.internal:6379/0",
        "JWT_SECRET_KEY": "x" * 48,
        "CORS_ALLOW_ORIGINS": "https://crypto.example",
        "LIVE_API_KEY": "must-not-be-used-in-production",
    })
    codes = {r.code for r in settings.validation_reasons()}
    assert "production_plaintext_exchange_env_forbidden" in codes


def test_frontend_next_public_surface_contains_no_backend_secret_names():
    findings = []
    files_to_check = list(WEB.rglob("*.ts")) + list(WEB.rglob("*.tsx"))
    if (ROOT / "docker-compose.yml").exists(): files_to_check.append(ROOT / "docker-compose.yml")
    if (ROOT / ".env.example").exists(): files_to_check.append(ROOT / ".env.example")
    
    for path in files_to_check:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for line in text.splitlines():
            if "NEXT_PUBLIC_" in line and any(word in line.upper() for word in ("SECRET", "PASSWORD", "TOKEN", "API_KEY", "DATABASE_URL", "REDIS_URL", "JWT_SECRET")):
                findings.append((str(path), line.strip()))
    assert findings == []


def test_dangerous_mutation_routes_reference_authorization_policies():
    phase2 = (API / "routers" / "phase2.py").read_text()
    assert "Depends(trading_policy)" in phase2
    assert "Depends(safety_policy)" in phase2
    assert "SecurityAuditStore" in phase2
    assert "@router.post('/v1/orders/demo/submit'" in phase2
    assert "@router.post('/v1/safety/halt'" in phase2
    assert "@router.post('/v1/safety/resume'" in phase2

    assert "Depends(credential_policy)" in (API / "routers" / "demo_exchange.py").read_text()
    assert "dependencies=[Depends(research_policy)]" in (API / "routers" / "research.py").read_text()
    assert "Depends(ops_policy)" in (API / "routers" / "market_data.py").read_text()


def test_credential_boundary_has_no_withdrawal_operation_and_no_plaintext_response_fields():
    execution = (API / "exchange" / "execution_adapter.py").read_text().lower()
    credential = (API / "exchange" / "credential_security.py").read_text().lower()
    router = (API / "routers" / "security_admin.py").read_text().lower()
    assert ".withdraw(" not in execution
    assert ".withdraw(" not in credential
    assert "def withdraw" not in execution
    assert "def withdraw" not in credential
    assert "api_secret:" not in router.split("class credentialmetadataresponse", 1)[1].split("class validationresponse", 1)[0]
    assert "api_key_fingerprint" in router


def test_live_execution_uses_encrypted_store_resolver_not_plaintext_env_names():
    adapter = (API / "exchange" / "execution_adapter.py").read_text()
    factory = (API / "packages" / "exchange" / "factory.py").read_text()
    credential = (API / "exchange" / "credential_security.py").read_text()
    assert "LIVE_API_KEY" not in adapter
    assert "LIVE_API_SECRET" not in adapter
    assert "credential_resolver" in factory
    assert "resolve_for_execution" in credential
    assert "self.cipher.decrypt" in credential


def test_credential_validation_is_read_only_before_explicit_store():
    source = (API / "exchange" / "credential_security.py").read_text()
    validate_body = source.split("def validate_transient", 1)[1].split("def store_validated", 1)[0]
    assert "self.db.add" not in validate_body
    assert "self.db.commit" not in validate_body
    assert "validate_account_capabilities" in validate_body


def test_request_body_limit_has_safe_default():
    settings = AppSettings()
    assert 16_384 <= settings.max_request_body_bytes <= 10_485_760


def test_jwt_helpers_bind_to_validated_application_settings():
    first = AppSettings(jwt_secret_key="a" * 48, jwt_algorithm="HS256")
    second = AppSettings(jwt_secret_key="b" * 48, jwt_algorithm="HS256")
    configure_security(first)
    token = create_access_token({"sub": str(uuid4())})
    assert decode_access_token(token)["type"] == "access"
    configure_security(second)
    with pytest.raises(Exception):
        decode_access_token(token)
