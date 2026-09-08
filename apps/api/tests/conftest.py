import pytest
from sqlalchemy import text
from database import SessionLocal
from models import OHLCVCandle, StrategyDecision, RiskDecisionModel, DemoOrderModel, PositionModel, AppliedOrderFillModel, PositionProtectionModel, BotRuntimeStateModel, BotCommandModel, BotJournalModel, ResearchObservation, MarketFeatureSnapshot, MarketRegimeSnapshot, TradeOutcome, ResearchHypothesis, ResearchExperiment, ResearchCandidateStrategy, CandidatePromotionEvaluation

@pytest.fixture
def db_session():
    db = SessionLocal()
    # Clean Phase 2 / research tables
    db.query(CandidatePromotionEvaluation).delete()
    db.query(ResearchCandidateStrategy).delete()
    db.query(ResearchExperiment).delete()
    db.query(ResearchHypothesis).delete()
    db.query(TradeOutcome).delete()
    db.query(MarketRegimeSnapshot).delete()
    db.query(MarketFeatureSnapshot).delete()
    db.query(ResearchObservation).delete()
    db.query(AppliedOrderFillModel).delete()
    db.query(PositionProtectionModel).delete()
    db.query(DemoOrderModel).delete()
    db.query(RiskDecisionModel).delete()
    db.query(PositionModel).delete()
    db.query(BotRuntimeStateModel).delete()
    db.query(BotCommandModel).delete()
    db.query(BotJournalModel).delete()
    db.commit()
    
    try:
        yield db
    finally:
        db.close()
