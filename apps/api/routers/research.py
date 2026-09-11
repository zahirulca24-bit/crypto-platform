from security_auth import current_principal
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from packages.research.models import ObservationRead, ResearchSummary
from packages.research.service import ResearchObservationService

router = APIRouter(prefix="/v1/research", tags=["Research"], dependencies=[Depends(current_principal)])


def get_research_service(db: Session = Depends(get_db)) -> ResearchObservationService:
    return ResearchObservationService(db)


@router.get("/observations", response_model=list[ObservationRead])
def list_observations(
    event_type: str | None = Query(default=None),
    symbol: str | None = Query(default=None),
    strategy: str | None = Query(default=None),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    service: ResearchObservationService = Depends(get_research_service),
):
    return service.list(event_type=event_type, symbol=symbol, strategy=strategy, start=start, end=end, limit=limit, offset=offset)


@router.get("/observations/{event_id}", response_model=ObservationRead)
def get_observation(event_id: UUID, service: ResearchObservationService = Depends(get_research_service)):
    observation = service.get(event_id)
    if observation is None:
        raise HTTPException(status_code=404, detail="Research observation not found")
    return observation


@router.get("/summary", response_model=ResearchSummary)
def research_summary(
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    service: ResearchObservationService = Depends(get_research_service),
):
    return service.summary(start=start, end=end)

from packages.research.features import FeatureGenerateRequest, FeatureSnapshotRead, MarketFeatureService


def get_market_feature_service(db: Session = Depends(get_db)) -> MarketFeatureService:
    return MarketFeatureService(db)


@router.post("/features/generate", response_model=FeatureSnapshotRead)
def generate_features(
    request: FeatureGenerateRequest,
    service: MarketFeatureService = Depends(get_market_feature_service),
):
    try:
        return service.generate(request)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/features", response_model=list[FeatureSnapshotRead])
def list_features(
    symbol: str | None = Query(default=None),
    timeframe: str | None = Query(default=None),
    feature_version: str | None = Query(default=None),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    service: MarketFeatureService = Depends(get_market_feature_service),
):
    return service.list(symbol=symbol, timeframe=timeframe, feature_version=feature_version,
                        start=start, end=end, limit=limit, offset=offset)


@router.get("/features/{snapshot_id}", response_model=FeatureSnapshotRead)
def get_features(snapshot_id: UUID, service: MarketFeatureService = Depends(get_market_feature_service)):
    snapshot = service.get(snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Feature snapshot not found")
    return snapshot

from packages.research.regimes import RegimeClassifyRequest, RegimeSnapshotRead, MarketRegimeService


def get_market_regime_service(db: Session = Depends(get_db)) -> MarketRegimeService:
    return MarketRegimeService(db)


@router.post("/regimes/classify", response_model=RegimeSnapshotRead)
def classify_regime(request: RegimeClassifyRequest, service: MarketRegimeService = Depends(get_market_regime_service)):
    try:
        return service.classify(request)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/regimes", response_model=list[RegimeSnapshotRead])
def list_regimes(
    symbol: str | None = Query(default=None),
    timeframe: str | None = Query(default=None),
    regime: str | None = Query(default=None),
    start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    service: MarketRegimeService = Depends(get_market_regime_service),
):
    return service.list(symbol=symbol, timeframe=timeframe, regime=regime, start=start, end=end, limit=limit, offset=offset)


@router.get("/regimes/current", response_model=RegimeSnapshotRead)
def current_regime(
    symbol: str = Query(..., min_length=1),
    timeframe: str = Query(..., min_length=1),
    exchange: str | None = Query(default=None),
    service: MarketRegimeService = Depends(get_market_regime_service),
):
    snapshot = service.current(symbol=symbol, timeframe=timeframe, exchange=exchange)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Current regime not found")
    return snapshot


@router.get("/regimes/{snapshot_id}", response_model=RegimeSnapshotRead)
def get_regime(snapshot_id: UUID, service: MarketRegimeService = Depends(get_market_regime_service)):
    snapshot = service.get(snapshot_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Regime snapshot not found")
    return snapshot

from packages.research.outcomes import OutcomeGenerateRequest, PerformanceRow, TradeOutcomeRead, TradeOutcomeService


def get_trade_outcome_service(db: Session = Depends(get_db)) -> TradeOutcomeService:
    return TradeOutcomeService(db)


@router.post("/outcomes/generate", response_model=TradeOutcomeRead)
def generate_outcome(request: OutcomeGenerateRequest, service: TradeOutcomeService = Depends(get_trade_outcome_service)):
    try:
        return service.generate(request)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/outcomes", response_model=list[TradeOutcomeRead])
def list_outcomes(
    symbol: str | None = Query(default=None), strategy: str | None = Query(default=None),
    regime: str | None = Query(default=None), timeframe: str | None = Query(default=None),
    start: datetime | None = Query(default=None), end: datetime | None = Query(default=None),
    exit_reason: str | None = Query(default=None), limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0), service: TradeOutcomeService = Depends(get_trade_outcome_service),
):
    return service.list(symbol=symbol, strategy=strategy, regime=regime, timeframe=timeframe, start=start, end=end,
                        exit_reason=exit_reason, limit=limit, offset=offset)


@router.get("/outcomes/{outcome_id}", response_model=TradeOutcomeRead)
def get_outcome(outcome_id: UUID, service: TradeOutcomeService = Depends(get_trade_outcome_service)):
    outcome = service.get(outcome_id)
    if outcome is None:
        raise HTTPException(status_code=404, detail="Trade outcome not found")
    return outcome


@router.get("/analytics/performance", response_model=list[PerformanceRow])
def performance_analytics(
    group_by: str = Query(default="symbol", pattern="^(symbol|strategy|strategy_version|regime|timeframe|exit_reason)$"),
    symbol: str | None = Query(default=None), strategy: str | None = Query(default=None),
    regime: str | None = Query(default=None), timeframe: str | None = Query(default=None),
    start: datetime | None = Query(default=None), end: datetime | None = Query(default=None),
    exit_reason: str | None = Query(default=None), service: TradeOutcomeService = Depends(get_trade_outcome_service),
):
    return service.performance(group_by=group_by, symbol=symbol, strategy=strategy, regime=regime, timeframe=timeframe,
                               start=start, end=end, exit_reason=exit_reason)

from decimal import Decimal
from packages.research.hypotheses import HypothesisGenerateRequest, HypothesisRead, ResearchHypothesisService, StatusPatch

def get_research_hypothesis_service(db: Session = Depends(get_db)) -> ResearchHypothesisService:
    return ResearchHypothesisService(db)

@router.post('/hypotheses/generate', response_model=list[HypothesisRead])
def generate_hypotheses(request: HypothesisGenerateRequest, service: ResearchHypothesisService = Depends(get_research_hypothesis_service)):
    try: return service.generate(request)
    except ValueError as exc: raise HTTPException(status_code=422, detail=str(exc)) from exc

@router.get('/hypotheses', response_model=list[HypothesisRead])
def list_hypotheses(
    hypothesis_type: str|None=Query(default=None), status: str|None=Query(default=None), strategy: str|None=Query(default=None),
    symbol: str|None=Query(default=None), timeframe: str|None=Query(default=None), regime: str|None=Query(default=None),
    minimum_confidence: Decimal|None=Query(default=None, ge=0, le=1), minimum_priority: Decimal|None=Query(default=None, ge=0, le=1),
    start: datetime|None=Query(default=None), end: datetime|None=Query(default=None), limit:int=Query(default=100,ge=1,le=1000), offset:int=Query(default=0,ge=0),
    service: ResearchHypothesisService=Depends(get_research_hypothesis_service)):
    return service.list(hypothesis_type=hypothesis_type,status=status,strategy=strategy,symbol=symbol,timeframe=timeframe,regime=regime,
        min_confidence=minimum_confidence,min_priority=minimum_priority,start=start,end=end,limit=limit,offset=offset)

@router.get('/hypotheses/{hypothesis_id}', response_model=HypothesisRead)
def get_hypothesis(hypothesis_id:UUID, service:ResearchHypothesisService=Depends(get_research_hypothesis_service)):
    row=service.get(hypothesis_id)
    if row is None: raise HTTPException(status_code=404,detail='Research hypothesis not found')
    return row

@router.patch('/hypotheses/{hypothesis_id}/status', response_model=HypothesisRead)
def patch_hypothesis_status(hypothesis_id:UUID, request:StatusPatch, service:ResearchHypothesisService=Depends(get_research_hypothesis_service)):
    try:return service.set_status(hypothesis_id,request.status)
    except LookupError as exc: raise HTTPException(status_code=404,detail=str(exc)) from exc
    except ValueError as exc: raise HTTPException(status_code=422,detail=str(exc)) from exc

from packages.research.experiments import ExperimentComparison, ExperimentRead, ExperimentRunRequest, ResearchExperimentService

def get_research_experiment_service(db: Session = Depends(get_db)) -> ResearchExperimentService:
    return ResearchExperimentService(db)

@router.post('/experiments/run', response_model=ExperimentRead)
def run_experiment(request: ExperimentRunRequest, service: ResearchExperimentService = Depends(get_research_experiment_service)):
    try: return service.run(request)
    except LookupError as exc: raise HTTPException(status_code=404,detail=str(exc)) from exc
    except ValueError as exc: raise HTTPException(status_code=422,detail=str(exc)) from exc

@router.get('/experiments', response_model=list[ExperimentRead])
def list_experiments(
    hypothesis_id: UUID|None=Query(default=None), experiment_type:str|None=Query(default=None), status:str|None=Query(default=None),
    strategy:str|None=Query(default=None), symbol:str|None=Query(default=None), timeframe:str|None=Query(default=None), passed:bool|None=Query(default=None),
    start:datetime|None=Query(default=None), end:datetime|None=Query(default=None), minimum_score:Decimal|None=Query(default=None,ge=0,le=1),
    limit:int=Query(default=100,ge=1,le=1000), offset:int=Query(default=0,ge=0), service:ResearchExperimentService=Depends(get_research_experiment_service)):
    return service.list(hypothesis_id=hypothesis_id,experiment_type=experiment_type,status=status,strategy=strategy,symbol=symbol,timeframe=timeframe,passed=passed,start=start,end=end,minimum_score=minimum_score,limit=limit,offset=offset)

@router.get('/experiments/{experiment_id}', response_model=ExperimentRead)
def get_experiment(experiment_id:UUID, service:ResearchExperimentService=Depends(get_research_experiment_service)):
    row=service.get(experiment_id)
    if row is None: raise HTTPException(status_code=404,detail='Research experiment not found')
    return row

@router.get('/experiments/{experiment_id}/comparison', response_model=ExperimentComparison)
def get_experiment_comparison(experiment_id:UUID, service:ResearchExperimentService=Depends(get_research_experiment_service)):
    row=service.comparison(experiment_id)
    if row is None: raise HTTPException(status_code=404,detail='Research experiment not found')
    return row

from packages.research.candidates import (
    CandidateCreateRequest, CandidateRead, PromotionEvaluateRequest, PromotionRead, ResearchCandidateService,
)

def get_research_candidate_service(db: Session = Depends(get_db)) -> ResearchCandidateService:
    return ResearchCandidateService(db)

@router.post('/candidates/create', response_model=CandidateRead)
def create_candidate(request: CandidateCreateRequest, service: ResearchCandidateService = Depends(get_research_candidate_service)):
    try: return service.create(request)
    except LookupError as exc: raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc: raise HTTPException(status_code=422, detail=str(exc)) from exc

@router.get('/candidates', response_model=list[CandidateRead])
def list_candidates(
    status:str|None=Query(default=None), base_strategy:str|None=Query(default=None), source_hypothesis:UUID|None=Query(default=None),
    source_experiment:UUID|None=Query(default=None), symbol:str|None=Query(default=None), timeframe:str|None=Query(default=None),
    regime:str|None=Query(default=None), minimum_experiment_score:Decimal|None=Query(default=None,ge=0,le=1),
    minimum_stability:Decimal|None=Query(default=None,ge=0,le=1), limit:int=Query(default=100,ge=1,le=1000),
    offset:int=Query(default=0,ge=0), service:ResearchCandidateService=Depends(get_research_candidate_service)):
    return service.list(status=status,base_strategy=base_strategy,source_hypothesis=source_hypothesis,source_experiment=source_experiment,
        symbol=symbol,timeframe=timeframe,regime=regime,minimum_experiment_score=minimum_experiment_score,
        minimum_stability=minimum_stability,limit=limit,offset=offset)

@router.get('/candidates/{candidate_id}', response_model=CandidateRead)
def get_candidate(candidate_id:UUID, service:ResearchCandidateService=Depends(get_research_candidate_service)):
    row=service.get(candidate_id)
    if row is None: raise HTTPException(status_code=404,detail='Research candidate not found')
    return row

@router.post('/candidates/{candidate_id}/evaluate', response_model=PromotionRead)
def evaluate_candidate(candidate_id:UUID, request:PromotionEvaluateRequest, service:ResearchCandidateService=Depends(get_research_candidate_service)):
    try:return service.evaluate(candidate_id,request)
    except LookupError as exc: raise HTTPException(status_code=404,detail=str(exc)) from exc
    except ValueError as exc: raise HTTPException(status_code=422,detail=str(exc)) from exc

@router.get('/candidates/{candidate_id}/promotion', response_model=PromotionRead)
def get_candidate_promotion(candidate_id:UUID, service:ResearchCandidateService=Depends(get_research_candidate_service)):
    row=service.promotion(candidate_id)
    if row is None: raise HTTPException(status_code=404,detail='Candidate promotion evaluation not found')
    return row

@router.post('/candidates/{candidate_id}/request-review', response_model=CandidateRead)
def request_candidate_review(candidate_id:UUID, service:ResearchCandidateService=Depends(get_research_candidate_service)):
    try:return service.request_review(candidate_id)
    except LookupError as exc: raise HTTPException(status_code=404,detail=str(exc)) from exc
    except ValueError as exc: raise HTTPException(status_code=422,detail=str(exc)) from exc

@router.post('/candidates/{candidate_id}/approve-demo', response_model=CandidateRead)
def approve_candidate_demo(candidate_id:UUID, service:ResearchCandidateService=Depends(get_research_candidate_service)):
    try:return service.approve_demo(candidate_id)
    except LookupError as exc: raise HTTPException(status_code=404,detail=str(exc)) from exc
    except ValueError as exc: raise HTTPException(status_code=422,detail=str(exc)) from exc

@router.post('/candidates/{candidate_id}/reject', response_model=CandidateRead)
def reject_candidate(candidate_id:UUID, service:ResearchCandidateService=Depends(get_research_candidate_service)):
    try:return service.reject(candidate_id)
    except LookupError as exc: raise HTTPException(status_code=404,detail=str(exc)) from exc
    except ValueError as exc: raise HTTPException(status_code=422,detail=str(exc)) from exc

# Phase 3 final integration/readiness endpoints.
from packages.research.integration import ResearchIntegrationService


def get_research_integration_service(db: Session = Depends(get_db)) -> ResearchIntegrationService:
    return ResearchIntegrationService(db)


@router.get('/overview')
def research_overview(
    activity_limit: int = Query(default=20, ge=1, le=100),
    service: ResearchIntegrationService = Depends(get_research_integration_service),
):
    return service.overview(activity_limit=activity_limit)


@router.get('/pipeline/status')
def research_pipeline_status(service: ResearchIntegrationService = Depends(get_research_integration_service)):
    return service.pipeline_status()


@router.get('/learning-journal')
def research_learning_journal(
    event_type: str | None = Query(default=None), symbol: str | None = Query(default=None),
    strategy: str | None = Query(default=None), start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None), limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    service: ResearchIntegrationService = Depends(get_research_integration_service),
):
    return service.learning_journal(event_type=event_type, symbol=symbol, strategy=strategy, start=start, end=end, limit=limit, offset=offset)


@router.get('/lineage/{entity_type}/{entity_id}')
def research_lineage(entity_type: str, entity_id: UUID, service: ResearchIntegrationService = Depends(get_research_integration_service)):
    try:
        return service.lineage(entity_type, entity_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get('/health')
def research_health(service: ResearchIntegrationService = Depends(get_research_integration_service)):
    try:
        return service.health()
    except Exception as exc:
        raise HTTPException(status_code=503, detail={"status": "error", "research": "unavailable", "error": str(exc)}) from exc
