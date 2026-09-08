from unittest.mock import MagicMock, patch
import pytest
import ccxt
from fastapi.testclient import TestClient

from main import app
from exchange.demo_adapter import CCXTDemoExchangeAdapter

client = TestClient(app)


def create_mock_ccxt_exchange(
    has_positions: bool = True,
    auth_valid: bool = True,
    secret_str: str = "super_secret_key_12345",
):
    mock_exchange = MagicMock()
    mock_exchange.apiKey = "demo_key_98765"
    mock_exchange.secret = secret_str
    mock_exchange.has = {
        "fetchBalance": True,
        "fetchPositions": has_positions,
        "createOrder": True,
        "cancelOrder": True,
        "fetchOpenOrders": True,
        "fetchClosedOrders": True,
        "fetchMyTrades": True,
        "createOCOOrder": True,
        "stopLoss": True,
        "takeProfit": True,
        "reduceOnly": True,
    }
    mock_exchange.options = {"defaultType": "spot"}

    mock_exchange.set_sandbox_mode = MagicMock()
    mock_exchange.load_markets.return_value = {
        "BTC/USDT": {"symbol": "BTC/USDT", "base": "BTC", "quote": "USDT"}
    }

    if auth_valid:
        mock_exchange.fetch_balance.return_value = {
            "total": {"BTC": 1.5, "USDT": 10000.0},
            "free": {"BTC": 1.5, "USDT": 10000.0},
            "used": {"BTC": 0.0, "USDT": 0.0},
            "BTC": {"free": 1.5, "used": 0.0, "total": 1.5},
            "USDT": {"free": 10000.0, "used": 0.0, "total": 10000.0},
        }
        if has_positions:
            mock_exchange.fetch_positions.return_value = [
                {
                    "symbol": "BTC/USDT",
                    "side": "long",
                    "contracts": 0.5,
                    "entryPrice": 65000.0,
                    "unrealizedPnl": 250.0,
                }
            ]
        else:
            mock_exchange.fetch_positions.return_value = []
    else:
        mock_exchange.fetch_balance.side_effect = ccxt.AuthenticationError(
            f"Invalid API secret key: {secret_str}"
        )

    mock_exchange.milliseconds.return_value = 1700000000000
    return mock_exchange


def test_demo_mode_guard_rejects_production():
    """Verify production mode is strictly blocked."""
    with pytest.raises(ValueError, match="Production mode rejected"):
        CCXTDemoExchangeAdapter(exchange_id="binance", is_demo=False)


def test_demo_mode_guard_rejects_sandbox_failure():
    """Verify failure to set sandbox mode fails closed."""
    mock_exchange = MagicMock()
    mock_exchange.set_sandbox_mode.side_effect = Exception("Sandbox unavailable")
    with pytest.raises(RuntimeError, match="Production mode rejected"):
        CCXTDemoExchangeAdapter(
            exchange_id="binance", is_demo=True, exchange_instance=mock_exchange
        )


def test_capability_detection():
    """Verify structured capability flags detection."""
    mock_exchange = create_mock_ccxt_exchange(has_positions=True)
    adapter = CCXTDemoExchangeAdapter(
        exchange_id="binance", is_demo=True, exchange_instance=mock_exchange
    )
    capabilities = adapter.get_capabilities()

    assert capabilities["supports_spot"] is True
    assert capabilities["supports_futures"] is True
    assert capabilities["supports_fetch_balance"] is True
    assert capabilities["supports_fetch_positions"] is True
    assert capabilities["supports_client_order_ids"] is True
    assert capabilities["supports_reduce_only"] is True
    assert capabilities["supports_native_stop_loss"] is True
    assert capabilities["supports_native_take_profit"] is True
    assert capabilities["supports_oco"] is True


def test_credential_verification_success():
    """Verify valid credentials check."""
    mock_exchange = create_mock_ccxt_exchange(auth_valid=True)
    adapter = CCXTDemoExchangeAdapter(
        exchange_id="binance", is_demo=True, exchange_instance=mock_exchange
    )
    assert adapter.verify_credentials() is True


def test_credential_verification_failure_and_secret_masking():
    """Verify credential failure is safe and never exposes secrets."""
    secret_key = "TOP_SECRET_PHRASE_999"
    mock_exchange = create_mock_ccxt_exchange(auth_valid=False, secret_str=secret_key)
    adapter = CCXTDemoExchangeAdapter(
        exchange_id="binance", is_demo=True, exchange_instance=mock_exchange
    )

    with pytest.raises(ValueError) as exc_info:
        adapter.verify_credentials()

    err_msg = str(exc_info.value)
    assert secret_key not in err_msg
    assert "***MASKED_SECRET***" in err_msg or "Credential verification failed" in err_msg


def test_balance_fetch():
    """Verify balance fetching via adapter."""
    mock_exchange = create_mock_ccxt_exchange(auth_valid=True)
    adapter = CCXTDemoExchangeAdapter(
        exchange_id="binance", is_demo=True, exchange_instance=mock_exchange
    )
    balance = adapter.fetch_balance()
    assert "BTC" in balance
    assert balance["BTC"]["free"] == 1.5


def test_verify_endpoint_success():
    """Test POST /v1/exchange/demo/verify with mocked adapter."""
    mock_exchange = create_mock_ccxt_exchange(auth_valid=True)
    with patch(
        "services.demo_exchange.get_demo_connector"
    ) as mock_get_connector:
        adapter = CCXTDemoExchangeAdapter(
            exchange_id="binance", is_demo=True, exchange_instance=mock_exchange
        )
        mock_get_connector.return_value = adapter

        response = client.post(
            "/v1/exchange/demo/verify",
            json={"exchange": "binance", "api_key": "test_key", "api_secret": "test_secret"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["exchange"] == "binance"
        assert data["environment"] == "demo"
        assert data["is_valid"] is True
        assert data["capabilities"]["supports_spot"] is True
        # Verify secret non-exposure
        response_text = response.text
        assert "test_secret" not in response_text
        assert "api_secret" not in data


def test_verify_endpoint_failure_handled_safely():
    """Test POST /v1/exchange/demo/verify with invalid credentials."""
    mock_exchange = create_mock_ccxt_exchange(auth_valid=False, secret_str="SECRET_XYZ")
    with patch(
        "services.demo_exchange.get_demo_connector"
    ) as mock_get_connector:
        adapter = CCXTDemoExchangeAdapter(
            exchange_id="binance", is_demo=True, exchange_instance=mock_exchange
        )
        mock_get_connector.return_value = adapter

        response = client.post(
            "/v1/exchange/demo/verify",
            json={"exchange": "binance", "api_key": "bad_key", "api_secret": "SECRET_XYZ"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] is False
        assert "SECRET_XYZ" not in response.text


def test_account_summary_endpoint():
    """Test GET /v1/exchange/demo/account-summary."""
    mock_exchange = create_mock_ccxt_exchange(auth_valid=True, has_positions=True)
    with patch(
        "services.demo_exchange.get_demo_connector"
    ) as mock_get_connector:
        adapter = CCXTDemoExchangeAdapter(
            exchange_id="binance", is_demo=True, exchange_instance=mock_exchange
        )
        mock_get_connector.return_value = adapter

        response = client.get("/v1/exchange/demo/account-summary")
        assert response.status_code == 200
        data = response.json()
        assert data["exchange"] == "binance"
        assert data["environment"] == "demo"
        assert len(data["balances"]) >= 2
        assert any(b["currency"] == "BTC" and b["total"] == "1.5" for b in data["balances"])
        assert len(data["positions"]) == 1
        assert data["positions"][0]["symbol"] == "BTC/USDT"
        assert data["capabilities"]["supports_spot"] is True


def test_unsupported_positions_handled():
    """Test account summary when exchange does not support positions."""
    mock_exchange = create_mock_ccxt_exchange(auth_valid=True, has_positions=False)
    with patch(
        "services.demo_exchange.get_demo_connector"
    ) as mock_get_connector:
        adapter = CCXTDemoExchangeAdapter(
            exchange_id="binance", is_demo=True, exchange_instance=mock_exchange
        )
        mock_get_connector.return_value = adapter

        response = client.get("/v1/exchange/demo/account-summary")
        assert response.status_code == 200
        data = response.json()
        assert data["positions"] == []
        assert data["capabilities"]["supports_fetch_positions"] is False

