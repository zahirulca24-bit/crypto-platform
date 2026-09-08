"""Deterministic policy enforcement and position sizing."""

from __future__ import annotations

import hashlib
from decimal import Decimal, ROUND_DOWN

from .models import OrderAction, RiskDecision, RiskEvaluationRequest
from .storage import RiskDecisionStore


ZERO = Decimal("0")
QUANTITY_STEP = Decimal("0.00000001")


class RiskEngine:
    def __init__(self, store: RiskDecisionStore) -> None:
        self.store = store

    @staticmethod
    def _fingerprint(request: RiskEvaluationRequest) -> str:
        # Pydantic's JSON representation canonicalizes Decimal values and makes retries idempotent.
        return hashlib.sha256(request.model_dump_json(exclude={"proposal": {"id"}}).encode()).hexdigest()

    @staticmethod
    def _quantity(value: Decimal) -> Decimal:
        return value.quantize(QUANTITY_STEP, rounding=ROUND_DOWN)

    def evaluate(self, request: RiskEvaluationRequest) -> RiskDecision:
        fingerprint = self._fingerprint(request)
        previous = self.store.get_by_fingerprint(fingerprint)
        if previous:
            return previous

        proposal, portfolio, policy = request.proposal, request.portfolio, request.policy
        reasons: list[str] = []
        price = proposal.price
        if price <= ZERO:
            reasons.append("INVALID_PRICE")
        if proposal.stop_price is None or proposal.stop_price <= ZERO or proposal.stop_price == price:
            reasons.append("INVALID_PROPOSAL")
        if portfolio.available_balance < policy.minimum_available_balance:
            reasons.append("INSUFFICIENT_AVAILABLE_BALANCE")
        if portfolio.daily_pnl <= -policy.max_daily_loss:
            reasons.append("DAILY_LOSS_LIMIT_REACHED")
        if (portfolio.peak_equity is None) != (portfolio.current_equity is None):
            reasons.append("INVALID_PROPOSAL")
        elif portfolio.peak_equity is not None and portfolio.current_equity is not None:
            if portfolio.peak_equity - portfolio.current_equity >= policy.max_drawdown:
                reasons.append("DRAWDOWN_LIMIT_REACHED")

        if reasons:
            return self.store.save(fingerprint, self._rejected(request, reasons))

        by_symbol = {position.symbol.upper(): position for position in portfolio.positions}
        current_symbol = by_symbol.get(proposal.symbol)
        current_quantity = current_symbol.quantity if current_symbol else ZERO
        symbol_exposure = abs(current_quantity * price)
        total_exposure = sum((abs(p.quantity * p.mark_price) for p in portfolio.positions), ZERO)
        direction = Decimal("1") if proposal.action == OrderAction.BUY else Decimal("-1")
        risk_per_unit = abs(price - proposal.stop_price)

        # Every cap is translated into a quantity.  The smallest cap is the final trade size.
        caps: list[tuple[str, Decimal]] = [("RISK_PER_TRADE_LIMIT", policy.max_risk_per_trade / risk_per_unit)]
        # For a signed position c and direction d, abs(c + d*q) <= A has a
        # closed-form upper bound.  This also protects a reduction that would
        # otherwise cross through zero and open an oversized reverse position.
        def exposure_cap(limit: Decimal, base_exposure: Decimal) -> Decimal:
            allowed_position_quantity = (limit - base_exposure) / price
            if allowed_position_quantity < ZERO:
                return Decimal("-1")
            return allowed_position_quantity - (direction * current_quantity)

        caps.append(("MAX_POSITION_NOTIONAL", exposure_cap(policy.max_position_notional, ZERO)))
        caps.append(("MAX_SYMBOL_EXPOSURE", exposure_cap(policy.max_exposure_per_symbol, ZERO)))
        other_exposure = total_exposure - abs(current_quantity * (current_symbol.mark_price if current_symbol else price))
        caps.append(("MAX_TOTAL_PORTFOLIO_EXPOSURE", exposure_cap(policy.max_total_portfolio_exposure, other_exposure)))
        if proposal.action == OrderAction.BUY:
            caps.append(("INSUFFICIENT_AVAILABLE_BALANCE", portfolio.available_balance / price))

        opening_new_symbol = current_symbol is None or current_quantity == ZERO
        open_positions = sum(1 for p in portfolio.positions if p.quantity != ZERO)
        if opening_new_symbol and open_positions >= policy.max_open_positions:
            reasons.append("MAX_OPEN_POSITIONS_REACHED")

        cap_reason, raw_quantity = min(caps, key=lambda cap: cap[1])
        quantity = self._quantity(max(raw_quantity, ZERO))
        if quantity < policy.minimum_trade_quantity:
            reasons.append(cap_reason)
        if reasons:
            return self.store.save(fingerprint, self._rejected(request, reasons))

        notional = quantity * price
        decision = RiskDecision(
            proposal=proposal,
            approved=True,
            approved_quantity=quantity,
            approved_notional=notional,
            risk_amount=quantity * risk_per_unit,
            policy_snapshot=policy.model_dump(mode="json"),
        )
        return self.store.save(fingerprint, decision)

    @staticmethod
    def _rejected(request: RiskEvaluationRequest, reasons: list[str]) -> RiskDecision:
        return RiskDecision(
            proposal=request.proposal,
            approved=False,
            rejection_reasons=list(dict.fromkeys(reasons)),
            policy_snapshot=request.policy.model_dump(mode="json"),
        )
