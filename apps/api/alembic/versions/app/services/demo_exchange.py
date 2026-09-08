import os
from decimal import Decimal
from typing import Optional, List, Dict, Any

from exchange.demo_adapter import CCXTDemoExchangeAdapter
from schemas import (
    DemoExchangeVerifyRequest,
    DemoExchangeVerifyResponse,
    DemoAccountSummaryResponse,
    ExchangeCapabilities,
    BalanceItem,
    PositionItem,
)


def get_demo_connector(
    exchange_id: Optional[str] = None,
    api_key: Optional[str] = None,
    api_secret: Optional[str] = None,
    password: Optional[str] = None,
) -> CCXTDemoExchangeAdapter:
    env_exchange = os.getenv("DEMO_EXCHANGE", "binance")
    env_key = os.getenv("DEMO_API_KEY", "")
    env_secret = os.getenv("DEMO_API_SECRET", "")
    env_password = os.getenv("DEMO_API_PASSWORD")

    final_exchange = (exchange_id or env_exchange).lower()
    final_key = api_key if api_key is not None else env_key
    final_secret = api_secret if api_secret is not None else env_secret
    final_password = password if password is not None else env_password

    return CCXTDemoExchangeAdapter(
        exchange_id=final_exchange,
        api_key=final_key,
        api_secret=final_secret,
        password=final_password,
        is_demo=True,
    )


def verify_demo_credentials_service(
    request: Optional[DemoExchangeVerifyRequest] = None,
) -> DemoExchangeVerifyResponse:
    req = request or DemoExchangeVerifyRequest()
    try:
        connector = get_demo_connector(
            exchange_id=req.exchange,
            api_key=req.api_key,
            api_secret=req.api_secret,
            password=req.password,
        )
        capabilities_dict = connector.get_capabilities()
        capabilities = ExchangeCapabilities(**capabilities_dict)

        # Execute safe read-only credential check
        is_valid = connector.verify_credentials()
        return DemoExchangeVerifyResponse(
            exchange=connector.exchange_id,
            environment="demo",
            is_valid=is_valid,
            capabilities=capabilities,
            message="Demo credentials successfully verified."
            if is_valid
            else "Credential verification failed.",
        )
    except Exception as e:
        # Fallback for unconfigured or invalid credentials without exposing secrets
        exchange_id = (
            req.exchange or os.getenv("DEMO_EXCHANGE", "binance")
        ).lower()

        # Generate default capabilities structure if initialization failed
        capabilities = ExchangeCapabilities(
            supports_spot=True,
            supports_futures=False,
            supports_fetch_balance=True,
            supports_fetch_positions=False,
            supports_client_order_ids=True,
            supports_reduce_only=False,
            supports_native_stop_loss=False,
            supports_native_take_profit=False,
            supports_oco=False,
        )

        msg = str(e)
        # Ensure credentials are stripped
        if req.api_secret and req.api_secret in msg:
            msg = msg.replace(req.api_secret, "***MASKED_SECRET***")

        return DemoExchangeVerifyResponse(
            exchange=exchange_id,
            environment="demo",
            is_valid=False,
            capabilities=capabilities,
            message=f"Credential verification failed: {msg}",
        )


def get_demo_account_summary_service() -> DemoAccountSummaryResponse:
    connector = get_demo_connector()
    capabilities_dict = connector.get_capabilities()
    capabilities = ExchangeCapabilities(**capabilities_dict)

    raw_balance = connector.fetch_balance()

    # Parse CCXT balance dictionary into BalanceItem list
    balances: List[BalanceItem] = []
    ignored_keys = {"info", "free", "used", "total", "datetime", "timestamp"}

    for currency, val in raw_balance.items():
        if currency in ignored_keys or not isinstance(val, dict):
            continue

        free_val = Decimal(str(val.get("free", 0) or 0))
        used_val = Decimal(str(val.get("used", 0) or 0))
        total_val = Decimal(str(val.get("total", 0) or 0))

        if total_val > 0 or free_val > 0 or used_val > 0:
            balances.append(
                BalanceItem(
                    currency=currency,
                    free=free_val,
                    used=used_val,
                    total=total_val,
                )
            )

    # Parse positions if supported
    positions: List[PositionItem] = []
    if capabilities.supports_fetch_positions:
        raw_positions = connector.fetch_positions()
        for pos in raw_positions:
            contracts = Decimal(str(pos.get("contracts", 0) or 0))
            if contracts > 0:
                positions.append(
                    PositionItem(
                        symbol=pos.get("symbol", ""),
                        side=pos.get("side", "long"),
                        contracts=contracts,
                        entry_price=Decimal(str(pos["entryPrice"]))
                        if pos.get("entryPrice") is not None
                        else None,
                        unrealized_pnl=Decimal(str(pos["unrealizedPnl"]))
                        if pos.get("unrealizedPnl") is not None
                        else None,
                    )
                )

    return DemoAccountSummaryResponse(
        exchange=connector.exchange_id,
        environment="demo",
        balances=balances,
        positions=positions,
        capabilities=capabilities,
    )
