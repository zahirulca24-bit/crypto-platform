import pytest
from sqlalchemy import text
from database import SessionLocal
from models import OHLCVCandle, StrategyDecision, RiskDecisionModel, DemoOrderModel, PositionModel, AppliedOrderFillModel, PositionProtectionModel, BotRuntimeStateModel, BotCommandModel, BotJournalModel

@pytest.fixture
def db_session():
    db = SessionLocal()
    # Clean Phase 2 tables
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
