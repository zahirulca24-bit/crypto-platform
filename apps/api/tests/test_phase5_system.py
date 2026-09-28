import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.system import router as system_router
from services.system_capabilities import CapabilitiesService
from settings import (
    AppSettings,
    RuntimeMode,
    StartupConfigurationError,
    TradingMode,
)


def valid_production(**overrides):
    values = dict(
        runtime_mode=RuntimeMode.PRODUCTION,
        trading_mode=TradingMode.DISABLED,
        database_url="postgresql://app:nondefault@db.internal:5432/crypto",
        redis_url="rediss://cache.internal:6379/0",
        jwt_secret_key="production-secret-material-at-least-32-characters",
        cors_allow_origins=("https://crypto.example",),
    )
    values.update(overrides)
    return AppSettings(**values)


def test_safe_defaults_disable_live_trading():
    settings = AppSettings.from_env({})
    assert settings.runtime_mode is RuntimeMode.DEVELOPMENT
    assert settings.trading_mode is TradingMode.DISABLED
    assert settings.allow_live_trading is False
    settings.validate_startup()


@pytest.mark.parametrize("runtime_mode", [RuntimeMode.DEVELOPMENT, RuntimeMode.TEST, RuntimeMode.DEMO])
def test_nonproduction_runtime_modes_are_explicit_and_safe(runtime_mode):
    settings = AppSettings(runtime_mode=runtime_mode, trading_mode=TradingMode.DISABLED)
    assert settings.validate_startup().outcome == "accepted"


def test_demo_runtime_can_explicitly_enable_demo_order_capability():
    settings = AppSettings(runtime_mode=RuntimeMode.DEMO, trading_mode=TradingMode.DEMO)
    settings.validate_startup()
    caps = CapabilitiesService(settings).capabilities()
    assert caps.capabilities["demo_order_execution"].enabled is True
    assert caps.capabilities["live_order_execution"].enabled is False


def test_production_valid_configuration_accepts_disabled_trading():
    event = valid_production().validate_startup()
    assert event.outcome == "accepted"
    assert event.runtime_mode == "production"
    assert event.trading_mode == "disabled"


@pytest.mark.parametrize(
    "settings, expected_code",
    [
        (valid_production(debug=True), "production_debug_flags_enabled"),
        (valid_production(cors_allow_origins=("*",)), "production_wildcard_cors_forbidden"),
        (valid_production(database_url="sqlite:///unsafe.db"), "production_postgresql_required"),
        (valid_production(redis_url=""), "production_redis_required"),
        (valid_production(jwt_secret_key="short"), "production_jwt_secret_required"),
        (valid_production(trading_mode=TradingMode.DEMO), "production_demo_trading_forbidden"),
    ],
)
def test_production_misconfiguration_fails_closed(settings, expected_code):
    with pytest.raises(StartupConfigurationError) as exc:
        settings.validate_startup()
    assert expected_code in {reason.code for reason in exc.value.reasons}


def test_live_trading_requires_all_explicit_production_gates():
    settings = valid_production(trading_mode=TradingMode.LIVE, allow_live_trading=True)
    with pytest.raises(StartupConfigurationError) as exc:
        settings.validate_startup()
    assert "live_exchange_required" in {reason.code for reason in exc.value.reasons}

    enabled = valid_production(
        trading_mode=TradingMode.LIVE,
        allow_live_trading=True,
        live_exchange_id="kraken",
    )
    assert enabled.validate_startup().outcome == "accepted"


def test_startup_validation_log_is_audit_safe(caplog):
    secret = "do-not-log-this-production-secret-123456789"
    settings = valid_production(jwt_secret_key=secret, debug=True)
    with caplog.at_level(logging.ERROR, logger="crypto_platform.startup"):
        with pytest.raises(StartupConfigurationError):
            settings.validate_startup()
    output = "\n".join(record.getMessage() for record in caplog.records)
    assert secret not in output
    payload = json.loads(caplog.records[-1].getMessage())
    assert payload["event"] == "startup.configuration_validation"
    assert payload["outcome"] == "rejected"
    assert "production_debug_flags_enabled" in payload["reason_codes"]


def _system_client(settings: AppSettings) -> TestClient:
    app = FastAPI()
    app.state.settings = settings
    app.include_router(system_router)
    return TestClient(app)


def test_capabilities_endpoint_exposes_reasons_but_no_secrets():
    secret = "endpoint-secret-that-must-never-be-returned-123"
    settings = AppSettings(jwt_secret_key=secret, trading_mode=TradingMode.DISABLED)
    response = _system_client(settings).get("/v1/system/capabilities")
    assert response.status_code == 200
    data = response.json()
    serialized = response.text
    assert secret not in serialized
    assert "database_url" not in serialized
    assert "redis_url" not in serialized
    assert data["capabilities"]["demo_order_execution"]["enabled"] is False
    assert data["capabilities"]["demo_order_execution"]["reasons"][0]["code"] == "trading_mode_disabled"
    assert data["capabilities"]["direct_strategy_exchange_orders"]["enabled"] is False


def test_readiness_endpoint_reports_contract_without_connectivity_claims():
    response = _system_client(AppSettings()).get("/v1/system/readiness")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["checks"]["postgresql_authoritative"]["ready"] is True
    assert data["checks"]["risk_order_governance"]["ready"] is True
    assert "connected" not in response.text.lower()


def test_capability_contract_never_allows_strategy_direct_exchange_orders():
    for runtime_mode in RuntimeMode:
        for trading_mode in (TradingMode.DISABLED, TradingMode.DEMO):
            settings = AppSettings(runtime_mode=runtime_mode, trading_mode=trading_mode)
            caps = CapabilitiesService(settings).capabilities().capabilities
            assert caps["direct_strategy_exchange_orders"].enabled is False
            assert caps["live_order_execution"].enabled is False
