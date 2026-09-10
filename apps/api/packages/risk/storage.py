from __future__ import annotations
import json
from pathlib import Path
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import select

from .models import RiskDecision
from models import RiskDecisionModel
from packages.research.models import ObservationCreate
from packages.research.service import observe_best_effort

class RiskDecisionStore:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_fingerprint(self, fingerprint: str) -> RiskDecision | None:
        row = self.db.execute(select(RiskDecisionModel).where(RiskDecisionModel.request_fingerprint == fingerprint)).scalars().first()
        if row:
            return RiskDecision.model_validate(row.decision_json)
        return None

    def get(self, decision_id: str) -> RiskDecision | None:
        row = self.db.execute(select(RiskDecisionModel).where(RiskDecisionModel.id == (decision_id if isinstance(decision_id, UUID) else UUID(str(decision_id))))).scalars().first()
        if row:
            return RiskDecision.model_validate(row.decision_json)
        return None

    def save(self, fingerprint: str, decision: RiskDecision) -> RiskDecision:
        existing = self.get_by_fingerprint(fingerprint)
        if existing:
            return existing
        model = RiskDecisionModel(
            id=decision.id,
            request_fingerprint=fingerprint,
            decision_json=decision.model_dump(mode='json'),
            created_at=decision.created_at
        )
        self.db.add(model)
        self.db.commit()
        observe_best_effort(self.db, ObservationCreate(
            event_type="risk.approved" if decision.approved else "risk.rejected",
            source="risk_engine",
            symbol=decision.proposal.symbol,
            price=decision.proposal.price,
            side=decision.proposal.action.value,
            quantity=decision.approved_quantity,
            notional=decision.approved_notional,
            stop_loss=decision.proposal.stop_price,
            risk_approved=decision.approved,
            risk_rejection_reasons=decision.rejection_reasons,
            decision_context={
                "risk_decision_id": str(decision.id),
                "policy_snapshot": decision.policy_snapshot,
                "risk_amount": str(decision.risk_amount) if decision.risk_amount is not None else None,
            },
        ))
        return decision

    def list(self, limit: int = 100, offset: int = 0) -> list[RiskDecision]:
        rows = self.db.execute(select(RiskDecisionModel).order_by(RiskDecisionModel.created_at.desc()).offset(offset).limit(limit)).scalars().all()
        return [RiskDecision.model_validate(row.decision_json) for row in rows]
