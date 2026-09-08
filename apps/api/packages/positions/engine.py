"""Fill-driven, Decimal-only portfolio accounting."""

from __future__ import annotations

from decimal import Decimal

from packages.exchange.models import DemoOrder, OrderStatus

from .models import PortfolioSummary, Position, PositionSide, PositionStatus


ZERO = Decimal("0")


class PositionEngine:
    def __init__(self, store) -> None:
        self.store = store

    def apply_filled_order(self, order: DemoOrder) -> Position:
        if order.status != OrderStatus.FILLED or order.filled_quantity <= ZERO:
            raise ValueError("Only filled demo orders with a positive filled quantity affect positions")

        existing = self.store.get_open_for_symbol(order.symbol)
        if existing is None:
            candidate = Position(
                symbol=order.symbol,
                side=PositionSide.LONG if order.side == "BUY" else PositionSide.SHORT,
                quantity=order.filled_quantity,
                average_entry_price=order.price,
                current_price=order.price,
                fees=order.fee,
            )
        else:
            candidate = existing.model_copy(deep=True)
            self._apply(candidate, order)

        # Claiming first makes repeated fill delivery a no-op. The UUID is stable for a pre-existing position.
        if not self.store.claim_fill(order.id, candidate.id):
            applied = self.store.get_position_for_fill(order.id)
            if applied is None:  # pragma: no cover - impossible unless audit data was manually corrupted
                raise RuntimeError("Fill was claimed without an associated position")
            return applied
        return self.store.save(candidate)

    @staticmethod
    def _apply(position: Position, order: DemoOrder) -> None:
        incoming_side = PositionSide.LONG if order.side == "BUY" else PositionSide.SHORT
        quantity, price = order.filled_quantity, order.price
        position.current_price = price
        position.fees += order.fee
        if position.side == incoming_side:
            total = position.quantity + quantity
            position.average_entry_price = ((position.average_entry_price * position.quantity) + (price * quantity)) / total
            position.quantity = total
        elif quantity < position.quantity:
            PositionEngine._realize(position, quantity, price)
            position.quantity -= quantity
        elif quantity == position.quantity:
            PositionEngine._realize(position, quantity, price)
            position.quantity = ZERO
            position.status = PositionStatus.CLOSED
            position.unrealized_pnl = ZERO
        else:
            PositionEngine._realize(position, position.quantity, price)
            position.side = incoming_side
            position.quantity = quantity - position.quantity
            position.average_entry_price = price
            position.status = PositionStatus.OPEN
        if position.status == PositionStatus.OPEN:
            position.unrealized_pnl = PositionEngine._unrealized(position)

    @staticmethod
    def _realize(position: Position, quantity: Decimal, exit_price: Decimal) -> None:
        if position.side == PositionSide.LONG:
            position.realized_pnl += (exit_price - position.average_entry_price) * quantity
        else:
            position.realized_pnl += (position.average_entry_price - exit_price) * quantity

    @staticmethod
    def _unrealized(position: Position) -> Decimal:
        direction = Decimal("1") if position.side == PositionSide.LONG else Decimal("-1")
        return (position.current_price - position.average_entry_price) * position.quantity * direction

    def summary(self) -> PortfolioSummary:
        positions = self.store.list(limit=500)
        realized = sum((p.realized_pnl for p in positions), ZERO)
        unrealized = sum((p.unrealized_pnl for p in positions), ZERO)
        fees = sum((p.fees for p in positions), ZERO)
        return PortfolioSummary(open_positions=sum(p.status == PositionStatus.OPEN for p in positions), realized_pnl=realized, unrealized_pnl=unrealized, fees=fees, net_pnl=realized + unrealized - fees)
