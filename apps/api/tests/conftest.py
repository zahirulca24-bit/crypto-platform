import pytest
from sqlalchemy import text
from database import SessionLocal
from models import OHLCVCandle, StrategyDecision, RiskDecisionModel, DemoOrderModel, PositionModel, AppliedOrderFillModel, PositionProtectionModel, BotRuntimeStateModel, BotCommandModel, BotJournalModel, ResearchObservation, MarketFeatureSnapshot, MarketRegimeSnapshot, TradeOutcome, ResearchHypothesis, ResearchExperiment, ResearchCandidateStrategy, CandidatePromotionEvaluation, AIResearchProposal, AIResearchRun, AIProposalReview, AIStrategyBlueprint, BlueprintValidationRun, BlueprintSimulatedTrade, AIStrategyVariant, AIStrategyEvolutionRun, ChampionChallengerComparison, StrategyRegimeProfile, ResearchStrategyPortfolio, ShadowResearchSession, ShadowResearchTrade, ResearchCandidateHandoff, ResearchMonitoringPolicy, ResearchTriggerEvent, AdaptiveResearchJob, ResearchMonitorWorkerStatus

@pytest.fixture
def db_session():
    db = SessionLocal()
    # Clean Phase 2 / research tables
    db.query(ResearchTriggerEvent).update({ResearchTriggerEvent.research_job_id: None}, synchronize_session=False)
    db.query(AdaptiveResearchJob).delete()
    db.query(ResearchTriggerEvent).delete()
    db.query(ResearchMonitoringPolicy).delete()
    db.query(ResearchMonitorWorkerStatus).delete()
    db.query(ResearchCandidateHandoff).delete()
    db.query(ShadowResearchTrade).delete()
    db.query(ShadowResearchSession).delete()
    db.query(ResearchStrategyPortfolio).delete()
    db.query(StrategyRegimeProfile).delete()
    db.query(ChampionChallengerComparison).delete()
    db.query(AIStrategyEvolutionRun).update({AIStrategyEvolutionRun.champion_before: None, AIStrategyEvolutionRun.champion_after: None}, synchronize_session=False)
    db.query(AIStrategyVariant).delete()
    db.query(AIStrategyEvolutionRun).delete()
    db.query(BlueprintSimulatedTrade).delete()
    db.query(BlueprintValidationRun).delete()
    db.query(AIStrategyBlueprint).delete()
    db.query(AIProposalReview).delete()
    db.query(AIResearchRun).delete()
    db.query(AIResearchProposal).delete()
    db.query(CandidatePromotionEvaluation).delete()
    db.query(ResearchCandidateStrategy).delete()
    db.query(ResearchExperiment).delete()
    db.query(ResearchHypothesis).delete()
    db.query(TradeOutcome).delete()
    db.query(MarketRegimeSnapshot).delete()
    db.query(MarketFeatureSnapshot).delete()
    db.query(ResearchStrategyPortfolio).delete()
    db.query(StrategyRegimeProfile).delete()
    db.query(ResearchObservation).delete()
    db.query(OHLCVCandle).delete()
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
