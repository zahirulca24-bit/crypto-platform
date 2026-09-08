"""Idempotent TP/SL creation and reconciliation for demo positions only."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from decimal import Decimal
from typing import Protocol

from packages.positions.models import Position, PositionStatus

from .models import PositionProtection, ProtectionRequest, ProtectionStatus
from .storage import ProtectionStore


class ProtectionExchange(Protocol):
    def submit(self, position: Position, kind: str, price: Decimal, client_order_id: str) -> str: ...
    def exists(self, order_id: str) -> bool: ...


class DemoProtectionExchange:
    """In-memory demo adapter. It cannot authenticate to, or withdraw from, any venue."""

    def __init__(self) -> None:
        self.order_ids: set[str] = set()

    def submit(self, position: Position, kind: str, price: Decimal, client_order_id: str) -> str:
        order_id = f"demo-protection-{kind.lower()}-{client_order_id}"
        self.order_ids.add(order_id)
        return order_id

    def exists(self, order_id: str) -> bool:
        return order_id in self.order_ids


class ProtectionService:
    def __init__(self, position_store, protection_store: ProtectionStore, exchange: ProtectionExchange | None = None, trading_mode: str = "demo") -> None:
        self.position_store = position_store
        self.protection_store = protection_store
        self.exchange = exchange or DemoProtectionExchange()
        self.trading_mode = trading_mode.lower()

    @staticmethod
    def _client_order_id(position_id, kind: str) -> str:
        return hashlib.sha256(f"{position_id}:{kind}".encode()).hexdigest()[:32]

    def ensure(self, request: ProtectionRequest) -> PositionProtection:
        if self.trading_mode != "demo":
            raise RuntimeError("Protection is available only in demo trading mode")
        position = self.position_store.get(request.position_id)
        if position is None:
            raise LookupError("Position does not exist")
        if position.status != PositionStatus.OPEN or position.quantity <= 0:
            return self.protection_store.save(PositionProtection(position_id=position.id, tp_price=request.tp_price, sl_price=request.sl_price, protection_status=ProtectionStatus.NOT_REQUIRED, last_verified_at=datetime.now(timezone.utc)))
        if request.tp_price <= 0 or request.sl_price <= 0:
            raise ValueError("TP and SL prices must be positive")
        if position.side.value == "long" and not (request.tp_price > position.current_price > request.sl_price):
            raise ValueError("Long positions require TP above and SL below the current price")
        if position.side.value == "short" and not (request.tp_price < position.current_price < request.sl_price):
            raise ValueError("Short positions require TP below and SL above the current price")

        protection = self.protection_store.get(position.id) or PositionProtection(
            position_id=position.id, tp_price=request.tp_price, sl_price=request.sl_price, protection_status=ProtectionStatus.MISSING,
        )
        # Existing persisted prices win during retries, preventing a different retry body from changing protection.
        try:
            if not protection.tp_order_id or not self.exchange.exists(protection.tp_order_id):
                protection.tp_order_id = self.exchange.submit(position, "TP", protection.tp_price, self._client_order_id(position.id, "TP"))
            if not protection.sl_order_id or not self.exchange.exists(protection.sl_order_id):
                protection.sl_order_id = self.exchange.submit(position, "SL", protection.sl_price, self._client_order_id(position.id, "SL"))
            protection.protection_status = ProtectionStatus.PROTECTED
            protection.error_reason = None
        except Exception as exc:
            protection.protection_status = ProtectionStatus.PARTIAL if protection.tp_order_id or protection.sl_order_id else ProtectionStatus.ERROR
            protection.error_reason = str(exc)
        protection.last_verified_at = datetime.now(timezone.utc)
        return self.protection_store.save(protection)

    def detect_missing(self, position_id) -> PositionProtection | None:
        protection = self.protection_store.get(position_id)
        if protection is None:
            return None
        tp_ok = bool(protection.tp_order_id and self.exchange.exists(protection.tp_order_id))
        sl_ok = bool(protection.sl_order_id and self.exchange.exists(protection.sl_order_id))
        protection.last_verified_at = datetime.now(timezone.utc)
        if not (tp_ok and sl_ok):
            protection.protection_status = ProtectionStatus.MISSING
            protection.error_reason = "TP or SL order is missing from demo exchange"
        else:
            protection.protection_status = ProtectionStatus.PROTECTED
            protection.error_reason = None
        return self.protection_store.save(protection)

    def reconcile(self) -> list[PositionProtection]:
        recovered: list[PositionProtection] = []
        for position in self.position_store.list(limit=500):
            if position.status != PositionStatus.OPEN:
                continue
            protection = self.protection_store.get(position.id)
            if protection is None:
                continue  # no prices exist to safely invent protection after a restart
            checked = self.detect_missing(position.id)
            if checked and checked.protection_status == ProtectionStatus.MISSING:
                checked = self.ensure(ProtectionRequest(position_id=position.id, tp_price=checked.tp_price, sl_price=checked.sl_price))
            if checked:
                recovered.append(checked)
        return recovered
