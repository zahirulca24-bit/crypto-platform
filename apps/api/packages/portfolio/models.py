from __future__ import annotations
from datetime import datetime, timezone
from decimal import Decimal
from pydantic import BaseModel, ConfigDict, Field
from packages.risk.models import RiskDecision, RiskPolicy, StrategyOrderProposal
class EquitySnapshot(BaseModel):
    model_config=ConfigDict(extra="forbid")
    equity:Decimal=Field(gt=0); cash_balance:Decimal=Field(ge=0); peak_equity:Decimal=Field(gt=0)
    source:str=Field(default="accounting",max_length=32)
    observed_at:datetime=Field(default_factory=lambda:datetime.now(timezone.utc))
class PortfolioExposure(BaseModel):
    equity:Decimal; cash_balance:Decimal; reserved_capital:Decimal; available_capital:Decimal
    position_exposure:Decimal; portfolio_exposure:Decimal; symbol_exposure:dict[str,Decimal]; strategy_exposure:dict[str,Decimal]
    open_positions:int; daily_realized_pnl:Decimal; total_drawdown:Decimal
class CapitalAllocationView(BaseModel):
    risk_decision_id:str; symbol:str; strategy_key:str; reserved_notional:Decimal; status:str
class PortfolioRiskEvaluationRequest(BaseModel):
    model_config=ConfigDict(extra="forbid")
    proposal:StrategyOrderProposal; policy:RiskPolicy=Field(default_factory=RiskPolicy)
class PortfolioRiskResult(BaseModel):
    decision:RiskDecision; exposure:PortfolioExposure
