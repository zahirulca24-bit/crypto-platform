from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from packages.research.models import ObservationRead, ResearchSummary
from packages.research.service import ResearchObservationService

router = APIRouter(prefix="/v1/research", tags=["Research"])


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

# Phase 4 AI research proposal endpoints. Research-only; no trading authority.
from packages.research.ai.gemini_provider import AIProviderError, AIProviderNotConfigured
from packages.research.ai.schemas import AIHealth, GenerateProposalsRequest, ProposalRead, ProposalStatusPatch
from packages.research.ai.service import AIResearchService


def get_ai_research_service(db: Session = Depends(get_db)) -> AIResearchService:
    return AIResearchService(db)


@router.get('/ai/health', response_model=AIHealth)
def ai_research_health(service: AIResearchService = Depends(get_ai_research_service)):
    return service.health()


@router.post('/ai/proposals/generate', response_model=list[ProposalRead])
def generate_ai_proposals(request: GenerateProposalsRequest, service: AIResearchService = Depends(get_ai_research_service)):
    try:
        return service.generate(request)
    except AIProviderNotConfigured as exc:
        raise HTTPException(status_code=503, detail={"code": "ai_not_configured", "message": str(exc)}) from exc
    except AIProviderError as exc:
        raise HTTPException(status_code=502, detail={"code": "ai_provider_error", "message": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get('/ai/proposals', response_model=list[ProposalRead])
def list_ai_proposals(
    provider: str | None = Query(default=None), model: str | None = Query(default=None), proposal_type: str | None = Query(default=None),
    status: str | None = Query(default=None), strategy: str | None = Query(default=None), symbol: str | None = Query(default=None),
    timeframe: str | None = Query(default=None), regime: str | None = Query(default=None), start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None), limit: int = Query(default=100, ge=1, le=1000), offset: int = Query(default=0, ge=0),
    service: AIResearchService = Depends(get_ai_research_service),
):
    return service.list(provider=provider, model=model, proposal_type=proposal_type, status=status, strategy=strategy, symbol=symbol,
                        timeframe=timeframe, regime=regime, start=start, end=end, limit=limit, offset=offset)


@router.get('/ai/proposals/{proposal_id}', response_model=ProposalRead)
def get_ai_proposal(proposal_id: UUID, service: AIResearchService = Depends(get_ai_research_service)):
    row = service.get(proposal_id)
    if row is None: raise HTTPException(status_code=404, detail='AI research proposal not found')
    return row


@router.patch('/ai/proposals/{proposal_id}/status', response_model=ProposalRead)
def patch_ai_proposal_status(proposal_id: UUID, request: ProposalStatusPatch, service: AIResearchService = Depends(get_ai_research_service)):
    try: return service.set_status(proposal_id, request.status)
    except LookupError as exc: raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc: raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post('/ai/proposals/{proposal_id}/create-hypothesis', response_model=HypothesisRead)
def convert_ai_proposal_to_hypothesis(proposal_id: UUID, service: AIResearchService = Depends(get_ai_research_service)):
    try:
        row = service.create_hypothesis(proposal_id)
        return ResearchHypothesisService._read(row)
    except LookupError as exc: raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc: raise HTTPException(status_code=422, detail=str(exc)) from exc

# Phase 4 AI research-cycle orchestration/review endpoints. Research governance only.
from packages.research.ai.orchestrator import AIResearchOrchestrator
from packages.research.ai.schemas import AIProposalReviewRead, AIResearchRunRead, ResearchRunRequest


def get_ai_research_orchestrator(db: Session = Depends(get_db)) -> AIResearchOrchestrator:
    return AIResearchOrchestrator(db)


@router.post('/ai/runs', response_model=AIResearchRunRead)
def run_ai_research_cycle(request: ResearchRunRequest, service: AIResearchOrchestrator = Depends(get_ai_research_orchestrator)):
    return service.run(request)


@router.get('/ai/runs', response_model=list[AIResearchRunRead])
def list_ai_research_runs(
    run_type: str | None = Query(default=None), status: str | None = Query(default=None), provider: str | None = Query(default=None),
    model: str | None = Query(default=None), symbol: str | None = Query(default=None), strategy: str | None = Query(default=None),
    timeframe: str | None = Query(default=None), regime: str | None = Query(default=None), start: datetime | None = Query(default=None),
    end: datetime | None = Query(default=None), limit: int = Query(default=100, ge=1, le=1000), offset: int = Query(default=0, ge=0),
    service: AIResearchOrchestrator = Depends(get_ai_research_orchestrator),
):
    return service.list_runs(run_type=run_type,status=status,provider=provider,model=model,symbol=symbol,strategy=strategy,timeframe=timeframe,regime=regime,start=start,end=end,limit=limit,offset=offset)


@router.get('/ai/runs/{run_id}', response_model=AIResearchRunRead)
def get_ai_research_run(run_id: UUID, service: AIResearchOrchestrator = Depends(get_ai_research_orchestrator)):
    row=service.get_run(run_id)
    if row is None: raise HTTPException(status_code=404, detail='AI research run not found')
    return row


@router.get('/ai/runs/{run_id}/proposals', response_model=list[ProposalRead])
def get_ai_research_run_proposals(run_id: UUID, service: AIResearchOrchestrator = Depends(get_ai_research_orchestrator)):
    if service.get_run(run_id) is None: raise HTTPException(status_code=404, detail='AI research run not found')
    return service.run_proposals(run_id)


@router.get('/ai/proposals/{proposal_id}/review', response_model=AIProposalReviewRead)
def get_ai_proposal_review(proposal_id: UUID, service: AIResearchOrchestrator = Depends(get_ai_research_orchestrator)):
    row=service.get_review(proposal_id)
    if row is None: raise HTTPException(status_code=404, detail='AI proposal review not found')
    return row


@router.post('/ai/proposals/{proposal_id}/request-review', response_model=ProposalRead)
def request_ai_proposal_review(proposal_id: UUID, service: AIResearchOrchestrator = Depends(get_ai_research_orchestrator)):
    try:return service.request_review(proposal_id)
    except LookupError as exc: raise HTTPException(status_code=404,detail=str(exc)) from exc
    except ValueError as exc: raise HTTPException(status_code=422,detail=str(exc)) from exc

# Phase 4 AI strategy discovery blueprint endpoints. Non-executable research metadata only.
from packages.research.ai.discovery import StrategyDiscoveryService
from packages.research.ai.schemas import BlueprintGenerateRequest, BlueprintRead

def get_ai_strategy_discovery_service(db: Session = Depends(get_db)) -> StrategyDiscoveryService:
    return StrategyDiscoveryService(db)

@router.post('/ai/blueprints/generate', response_model=BlueprintRead)
def generate_ai_strategy_blueprint(request: BlueprintGenerateRequest, service: StrategyDiscoveryService = Depends(get_ai_strategy_discovery_service)):
    try:return service.generate(request)
    except AIProviderNotConfigured as exc: raise HTTPException(status_code=503,detail={"code":"ai_not_configured","message":str(exc)}) from exc
    except AIProviderError as exc: raise HTTPException(status_code=502,detail={"code":"ai_provider_error","message":str(exc)}) from exc
    except LookupError as exc: raise HTTPException(status_code=404,detail=str(exc)) from exc
    except ValueError as exc: raise HTTPException(status_code=422,detail=str(exc)) from exc

@router.get('/ai/blueprints', response_model=list[BlueprintRead])
def list_ai_strategy_blueprints(
    blueprint_type:str|None=Query(default=None),status:str|None=Query(default=None),base_strategy:str|None=Query(default=None),
    symbol:str|None=Query(default=None),timeframe:str|None=Query(default=None),regime:str|None=Query(default=None),
    source_proposal:UUID|None=Query(default=None),source_hypothesis:UUID|None=Query(default=None),source_experiment:UUID|None=Query(default=None),
    minimum_readiness:Decimal|None=Query(default=None,ge=0,le=1),complexity:str|None=Query(default=None),limit:int=Query(default=100,ge=1,le=1000),offset:int=Query(default=0,ge=0),
    service:StrategyDiscoveryService=Depends(get_ai_strategy_discovery_service)):
    return service.list(blueprint_type=blueprint_type,status=status,base_strategy=base_strategy,symbol=symbol,timeframe=timeframe,regime=regime,source_proposal=source_proposal,source_hypothesis=source_hypothesis,source_experiment=source_experiment,minimum_readiness=minimum_readiness,complexity=complexity,limit=limit,offset=offset)

@router.get('/ai/blueprints/{blueprint_id}', response_model=BlueprintRead)
def get_ai_strategy_blueprint(blueprint_id:UUID,service:StrategyDiscoveryService=Depends(get_ai_strategy_discovery_service)):
    row=service.get(blueprint_id)
    if row is None: raise HTTPException(status_code=404,detail='AI strategy blueprint not found')
    return row

@router.get('/ai/blueprints/{blueprint_id}/readiness')
def get_ai_strategy_blueprint_readiness(blueprint_id:UUID,service:StrategyDiscoveryService=Depends(get_ai_strategy_discovery_service)):
    try:return service.readiness(blueprint_id)
    except LookupError as exc: raise HTTPException(status_code=404,detail=str(exc)) from exc

@router.post('/ai/blueprints/{blueprint_id}/request-review',response_model=BlueprintRead)
def request_ai_strategy_blueprint_review(blueprint_id:UUID,service:StrategyDiscoveryService=Depends(get_ai_strategy_discovery_service)):
    try:return service.request_review(blueprint_id)
    except LookupError as exc: raise HTTPException(status_code=404,detail=str(exc)) from exc
    except ValueError as exc: raise HTTPException(status_code=422,detail=str(exc)) from exc

@router.post('/ai/blueprints/{blueprint_id}/accept-for-validation',response_model=BlueprintRead)
def accept_ai_strategy_blueprint_for_validation(blueprint_id:UUID,service:StrategyDiscoveryService=Depends(get_ai_strategy_discovery_service)):
    try:return service.accept_for_validation(blueprint_id)
    except LookupError as exc: raise HTTPException(status_code=404,detail=str(exc)) from exc
    except ValueError as exc: raise HTTPException(status_code=422,detail=str(exc)) from exc

@router.post('/ai/blueprints/{blueprint_id}/reject',response_model=BlueprintRead)
def reject_ai_strategy_blueprint(blueprint_id:UUID,service:StrategyDiscoveryService=Depends(get_ai_strategy_discovery_service)):
    try:return service.reject(blueprint_id)
    except LookupError as exc: raise HTTPException(status_code=404,detail=str(exc)) from exc
    except ValueError as exc: raise HTTPException(status_code=422,detail=str(exc)) from exc

# Phase 4 deterministic blueprint validation/backtesting endpoints. Research simulation only.
from packages.research.ai.validation import BlueprintValidationRequest, BlueprintValidationService, ValidationRead, SimulatedTradeRead

def get_blueprint_validation_service(db: Session = Depends(get_db)) -> BlueprintValidationService:
    return BlueprintValidationService(db)

@router.post('/ai/blueprints/{blueprint_id}/validate', response_model=ValidationRead)
def validate_ai_strategy_blueprint(blueprint_id: UUID, request: BlueprintValidationRequest, service: BlueprintValidationService = Depends(get_blueprint_validation_service)):
    try: return service.validate(blueprint_id, request)
    except LookupError as exc: raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc: raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc: raise HTTPException(status_code=500, detail=str(exc)) from exc

@router.get('/ai/validations', response_model=list[ValidationRead])
def list_ai_blueprint_validations(
    blueprint: UUID|None=Query(default=None), validation_type: str|None=Query(default=None), status: str|None=Query(default=None),
    symbol: str|None=Query(default=None), timeframe: str|None=Query(default=None), regime: str|None=Query(default=None), passed: bool|None=Query(default=None),
    minimum_score: Decimal|None=Query(default=None, ge=0, le=1), maximum_overfit_risk: Decimal|None=Query(default=None, ge=0, le=1),
    start: datetime|None=Query(default=None), end: datetime|None=Query(default=None), limit: int=Query(default=100, ge=1, le=1000), offset: int=Query(default=0, ge=0),
    service: BlueprintValidationService = Depends(get_blueprint_validation_service)):
    return service.list(blueprint=blueprint, validation_type=validation_type, status=status, symbol=symbol, timeframe=timeframe, regime=regime, passed=passed, minimum_score=minimum_score, maximum_overfit_risk=maximum_overfit_risk, start=start, end=end, limit=limit, offset=offset)

@router.get('/ai/validations/{validation_id}', response_model=ValidationRead)
def get_ai_blueprint_validation(validation_id: UUID, service: BlueprintValidationService = Depends(get_blueprint_validation_service)):
    row=service.get(validation_id)
    if row is None: raise HTTPException(status_code=404, detail='Blueprint validation not found')
    return row

@router.get('/ai/validations/{validation_id}/trades', response_model=list[SimulatedTradeRead])
def get_ai_blueprint_validation_trades(validation_id: UUID, service: BlueprintValidationService = Depends(get_blueprint_validation_service)):
    try:return service.trades(validation_id)
    except LookupError as exc:raise HTTPException(status_code=404,detail=str(exc)) from exc

@router.get('/ai/validations/{validation_id}/parameters')
def get_ai_blueprint_validation_parameters(validation_id: UUID, service: BlueprintValidationService = Depends(get_blueprint_validation_service)):
    try:return service.parameters(validation_id)
    except LookupError as exc:raise HTTPException(status_code=404,detail=str(exc)) from exc

@router.get('/ai/validations/{validation_id}/robustness')
def get_ai_blueprint_validation_robustness(validation_id: UUID, service: BlueprintValidationService = Depends(get_blueprint_validation_service)):
    try:return service.robustness(validation_id)
    except LookupError as exc:raise HTTPException(status_code=404,detail=str(exc)) from exc

@router.get('/ai/blueprints/{blueprint_id}/validations', response_model=list[ValidationRead])
def get_ai_strategy_blueprint_validations(blueprint_id: UUID, service: BlueprintValidationService = Depends(get_blueprint_validation_service)):
    try:return service.blueprint_validations(blueprint_id)
    except LookupError as exc:raise HTTPException(status_code=404,detail=str(exc)) from exc

# Phase 4 strategy evolution / champion-challenger research endpoints.
from packages.research.ai.evolution import (
    StrategyEvolutionService, EvolutionRunRequest, EvolutionRunRead,
    VariantRead, CompareRequest, ComparisonRead,
)

def get_strategy_evolution_service(db: Session = Depends(get_db)) -> StrategyEvolutionService:
    return StrategyEvolutionService(db)

@router.post('/ai/evolution/runs', response_model=EvolutionRunRead)
def create_ai_strategy_evolution_run(request: EvolutionRunRequest, service: StrategyEvolutionService = Depends(get_strategy_evolution_service)):
    try:return service.create_run(request)
    except LookupError as exc:raise HTTPException(status_code=404,detail=str(exc)) from exc
    except ValueError as exc:raise HTTPException(status_code=422,detail=str(exc)) from exc

@router.get('/ai/evolution/runs', response_model=list[EvolutionRunRead])
def list_ai_strategy_evolution_runs(limit:int=Query(default=100,ge=1,le=1000),offset:int=Query(default=0,ge=0),service:StrategyEvolutionService=Depends(get_strategy_evolution_service)):
    return service.list_runs(limit=limit,offset=offset)

@router.get('/ai/evolution/runs/{run_id}', response_model=EvolutionRunRead)
def get_ai_strategy_evolution_run(run_id:UUID,service:StrategyEvolutionService=Depends(get_strategy_evolution_service)):
    row=service.get_run(run_id)
    if row is None:raise HTTPException(status_code=404,detail='AI strategy evolution run not found')
    return row

@router.get('/ai/variants', response_model=list[VariantRead])
def list_ai_strategy_variants(
    blueprint:UUID|None=Query(default=None),variant_type:str|None=Query(default=None),status:str|None=Query(default=None),symbol:str|None=Query(default=None),
    timeframe:str|None=Query(default=None),regime:str|None=Query(default=None),complexity:str|None=Query(default=None),generation_method:str|None=Query(default=None),validation_passed:bool|None=Query(default=None),
    limit:int=Query(default=100,ge=1,le=1000),offset:int=Query(default=0,ge=0),service:StrategyEvolutionService=Depends(get_strategy_evolution_service)):
    return service.list_variants(blueprint=blueprint,variant_type=variant_type,status=status,symbol=symbol,timeframe=timeframe,regime=regime,complexity=complexity,generation_method=generation_method,validation_passed=validation_passed,limit=limit,offset=offset)

@router.get('/ai/variants/{variant_id}', response_model=VariantRead)
def get_ai_strategy_variant(variant_id:UUID,service:StrategyEvolutionService=Depends(get_strategy_evolution_service)):
    row=service.get_variant(variant_id)
    if row is None:raise HTTPException(status_code=404,detail='AI strategy variant not found')
    return row

@router.post('/ai/variants/{variant_id}/validate', response_model=ValidationRead)
def validate_ai_strategy_variant(variant_id:UUID,request:BlueprintValidationRequest,service:StrategyEvolutionService=Depends(get_strategy_evolution_service)):
    try:return service.validate_variant(variant_id,request)
    except LookupError as exc:raise HTTPException(status_code=404,detail=str(exc)) from exc
    except ValueError as exc:raise HTTPException(status_code=422,detail=str(exc)) from exc

@router.get('/ai/variants/{variant_id}/validations', response_model=list[ValidationRead])
def get_ai_strategy_variant_validations(variant_id:UUID,service:StrategyEvolutionService=Depends(get_strategy_evolution_service)):
    try:return service.variant_validations(variant_id)
    except LookupError as exc:raise HTTPException(status_code=404,detail=str(exc)) from exc

@router.post('/ai/evolution/compare', response_model=ComparisonRead)
def compare_ai_strategy_champion_challenger(request:CompareRequest,service:StrategyEvolutionService=Depends(get_strategy_evolution_service)):
    try:return service.compare(request)
    except LookupError as exc:raise HTTPException(status_code=404,detail=str(exc)) from exc
    except ValueError as exc:raise HTTPException(status_code=422,detail=str(exc)) from exc

@router.get('/ai/evolution/comparisons', response_model=list[ComparisonRead])
def list_ai_strategy_comparisons(limit:int=Query(default=100,ge=1,le=1000),offset:int=Query(default=0,ge=0),service:StrategyEvolutionService=Depends(get_strategy_evolution_service)):
    return service.list_comparisons(limit=limit,offset=offset)

@router.get('/ai/evolution/comparisons/{comparison_id}', response_model=ComparisonRead)
def get_ai_strategy_comparison(comparison_id:UUID,service:StrategyEvolutionService=Depends(get_strategy_evolution_service)):
    row=service.get_comparison(comparison_id)
    if row is None:raise HTTPException(status_code=404,detail='Champion/challenger comparison not found')
    return row

@router.get('/ai/blueprints/{blueprint_id}/champion', response_model=VariantRead|None)
def get_ai_research_champion(blueprint_id:UUID,service:StrategyEvolutionService=Depends(get_strategy_evolution_service)):
    try:return service.champion(blueprint_id)
    except LookupError as exc:raise HTTPException(status_code=404,detail=str(exc)) from exc

from packages.research.ai.matching import StrategyMatchingService, ProfileGenerateRequest, PortfolioBuildRequest, ProfileRead, PortfolioRead

def get_strategy_matching_service(db:Session=Depends(get_db))->StrategyMatchingService:return StrategyMatchingService(db)

@router.post('/ai/matching/profiles/generate',response_model=ProfileRead)
def generate_strategy_regime_profile(request:ProfileGenerateRequest,service:StrategyMatchingService=Depends(get_strategy_matching_service)):
    try:return service.generate_profile(request)
    except LookupError as exc:raise HTTPException(status_code=404,detail=str(exc)) from exc
    except ValueError as exc:raise HTTPException(status_code=422,detail=str(exc)) from exc

@router.get('/ai/matching/profiles',response_model=list[ProfileRead])
def list_strategy_regime_profiles(regime:str|None=None,source_type:str|None=None,minimum_compatibility:float|None=Query(default=None,ge=0,le=1),service:StrategyMatchingService=Depends(get_strategy_matching_service)):
    return service.profiles(regime=regime,source_type=source_type,minimum_compatibility=minimum_compatibility)

@router.get('/ai/matching/rank')
def rank_strategies_for_regime(regime:str,symbol:str|None=None,timeframe:str|None=None,minimum_compatibility:float=Query(default=0,ge=0,le=1),minimum_stability:float=Query(default=0,ge=0,le=1),maximum_overfit_risk:float=Query(default=.7,ge=0,le=1),service:StrategyMatchingService=Depends(get_strategy_matching_service)):
    try:return service.rank(regime,symbol,timeframe,minimum_compatibility,maximum_overfit_risk,minimum_stability)
    except ValueError as exc:raise HTTPException(status_code=422,detail=str(exc)) from exc

@router.post('/ai/portfolios/build',response_model=PortfolioRead)
def build_research_portfolio(request:PortfolioBuildRequest,service:StrategyMatchingService=Depends(get_strategy_matching_service)):
    try:return service.build_portfolio(request)
    except ValueError as exc:raise HTTPException(status_code=422,detail=str(exc)) from exc

@router.get('/ai/portfolios',response_model=list[PortfolioRead])
def list_research_portfolios(status:str|None=None,regime:str|None=None,symbol:str|None=None,timeframe:str|None=None,blueprint:UUID|None=None,variant:UUID|None=None,minimum_compatibility:float|None=Query(default=None,ge=0,le=1),minimum_stability:float|None=Query(default=None,ge=0,le=1),maximum_overfit_risk:float|None=Query(default=None,ge=0,le=1),limit:int=Query(default=100,ge=1,le=1000),offset:int=Query(default=0,ge=0),service:StrategyMatchingService=Depends(get_strategy_matching_service)):
    return service.portfolios(status=status,regime=regime,symbol=symbol,timeframe=timeframe,blueprint=blueprint,variant=variant,minimum_compatibility=minimum_compatibility,minimum_stability=minimum_stability,maximum_overfit_risk=maximum_overfit_risk,limit=limit,offset=offset)

@router.get('/ai/portfolios/{portfolio_id}',response_model=PortfolioRead)
def get_research_portfolio(portfolio_id:UUID,service:StrategyMatchingService=Depends(get_strategy_matching_service)):
    row=service.portfolio(portfolio_id)
    if not row:raise HTTPException(status_code=404,detail='portfolio not found')
    return row

@router.get('/ai/portfolios/{portfolio_id}/evaluation')
def get_research_portfolio_evaluation(portfolio_id:UUID,service:StrategyMatchingService=Depends(get_strategy_matching_service)):
    p=service.portfolio(portfolio_id)
    if not p:raise HTTPException(status_code=404,detail='portfolio not found')
    return {'portfolio_id':p.id,'readiness_score':p.readiness_score,'expected_metrics':p.expected_metrics,'robustness_score':p.robustness_score,'data_quality_score':p.data_quality_score,'warnings':p.warnings,'blocking_reasons':p.blocking_reasons,'research_only':True}

@router.get('/ai/portfolios/{portfolio_id}/correlations')
def get_research_portfolio_correlations(portfolio_id:UUID,service:StrategyMatchingService=Depends(get_strategy_matching_service)):
    p=service.portfolio(portfolio_id)
    if not p:raise HTTPException(status_code=404,detail='portfolio not found')
    return p.correlation_metrics

@router.get('/ai/matching/regime-transition')
def get_regime_transition_analysis(from_regime:str,to_regime:str,symbol:str|None=None,timeframe:str|None=None,service:StrategyMatchingService=Depends(get_strategy_matching_service)):
    return service.transition(from_regime,to_regime,symbol,timeframe)

@router.post('/ai/portfolios/{portfolio_id}/request-review',response_model=PortfolioRead)
def request_portfolio_review(portfolio_id:UUID,service:StrategyMatchingService=Depends(get_strategy_matching_service)):
    try:return service.status(portfolio_id,'review_required')
    except LookupError as exc:raise HTTPException(status_code=404,detail=str(exc)) from exc
    except ValueError as exc:raise HTTPException(status_code=422,detail=str(exc)) from exc

@router.post('/ai/portfolios/{portfolio_id}/accept-research',response_model=PortfolioRead)
def accept_portfolio_research(portfolio_id:UUID,service:StrategyMatchingService=Depends(get_strategy_matching_service)):
    try:return service.status(portfolio_id,'accepted_for_research')
    except LookupError as exc:raise HTTPException(status_code=404,detail=str(exc)) from exc
    except ValueError as exc:raise HTTPException(status_code=422,detail=str(exc)) from exc

@router.post('/ai/portfolios/{portfolio_id}/reject',response_model=PortfolioRead)
def reject_portfolio_research(portfolio_id:UUID,service:StrategyMatchingService=Depends(get_strategy_matching_service)):
    try:return service.status(portfolio_id,'rejected')
    except LookupError as exc:raise HTTPException(status_code=404,detail=str(exc)) from exc
    except ValueError as exc:raise HTTPException(status_code=422,detail=str(exc)) from exc

# Phase 4 shadow research + controlled Phase-3 candidate handoff. Research-only.
from packages.research.ai.shadow import (
    ShadowResearchService, ShadowSessionCreateRequest, ShadowSessionRead, ShadowTradeRead,
    HandoffCreateRequest, HandoffRead,
)

def get_shadow_research_service(db:Session=Depends(get_db))->ShadowResearchService:return ShadowResearchService(db)

@router.post('/ai/shadow/sessions',response_model=ShadowSessionRead)
def create_shadow_session(request:ShadowSessionCreateRequest,service:ShadowResearchService=Depends(get_shadow_research_service)):
    try:return service.create_session(request)
    except LookupError as exc:raise HTTPException(status_code=404,detail=str(exc)) from exc
    except ValueError as exc:raise HTTPException(status_code=422,detail=str(exc)) from exc

@router.get('/ai/shadow/sessions',response_model=list[ShadowSessionRead])
def list_shadow_sessions(status:str|None=None,source_type:str|None=None,limit:int=Query(default=100,ge=1,le=1000),offset:int=Query(default=0,ge=0),service:ShadowResearchService=Depends(get_shadow_research_service)):
    return service.sessions(status=status,source_type=source_type,limit=limit,offset=offset)

@router.get('/ai/shadow/sessions/{session_id}',response_model=ShadowSessionRead)
def get_shadow_session(session_id:UUID,service:ShadowResearchService=Depends(get_shadow_research_service)):
    row=service.session(session_id)
    if not row:raise HTTPException(status_code=404,detail='shadow session not found')
    return row

@router.post('/ai/shadow/sessions/{session_id}/process',response_model=ShadowSessionRead)
def process_shadow_session(session_id:UUID,service:ShadowResearchService=Depends(get_shadow_research_service)):
    try:return service.process(session_id)
    except LookupError as exc:raise HTTPException(status_code=404,detail=str(exc)) from exc
    except ValueError as exc:raise HTTPException(status_code=422,detail=str(exc)) from exc

@router.post('/ai/shadow/sessions/{session_id}/pause',response_model=ShadowSessionRead)
def pause_shadow_session(session_id:UUID,service:ShadowResearchService=Depends(get_shadow_research_service)):
    try:return service.pause(session_id)
    except LookupError as exc:raise HTTPException(status_code=404,detail=str(exc)) from exc
    except ValueError as exc:raise HTTPException(status_code=422,detail=str(exc)) from exc

@router.post('/ai/shadow/sessions/{session_id}/resume',response_model=ShadowSessionRead)
def resume_shadow_session(session_id:UUID,service:ShadowResearchService=Depends(get_shadow_research_service)):
    try:return service.resume(session_id)
    except LookupError as exc:raise HTTPException(status_code=404,detail=str(exc)) from exc
    except ValueError as exc:raise HTTPException(status_code=422,detail=str(exc)) from exc

@router.post('/ai/shadow/sessions/{session_id}/complete',response_model=ShadowSessionRead)
def complete_shadow_session(session_id:UUID,service:ShadowResearchService=Depends(get_shadow_research_service)):
    try:return service.complete(session_id)
    except LookupError as exc:raise HTTPException(status_code=404,detail=str(exc)) from exc
    except ValueError as exc:raise HTTPException(status_code=422,detail=str(exc)) from exc

@router.get('/ai/shadow/sessions/{session_id}/trades',response_model=list[ShadowTradeRead])
def shadow_session_trades(session_id:UUID,service:ShadowResearchService=Depends(get_shadow_research_service)):
    if not service.session(session_id):raise HTTPException(status_code=404,detail='shadow session not found')
    return service.trades(session_id)

@router.get('/ai/shadow/sessions/{session_id}/drift')
def shadow_session_drift(session_id:UUID,service:ShadowResearchService=Depends(get_shadow_research_service)):
    row=service.session(session_id)
    if not row:raise HTTPException(status_code=404,detail='shadow session not found')
    return {'session_id':row.id,'drift_metrics':row.drift_metrics,'research_only':True}

@router.get('/ai/shadow/sessions/{session_id}/readiness')
def shadow_session_readiness(session_id:UUID,service:ShadowResearchService=Depends(get_shadow_research_service)):
    row=service.session(session_id)
    if not row:raise HTTPException(status_code=404,detail='shadow session not found')
    return {'session_id':row.id,'readiness_score':row.readiness_score,'blocking_reasons':row.blocking_reasons,'warnings':row.warnings,'message':'Demo readiness does not mean Demo activation.','research_only':True}

@router.post('/ai/handoffs',response_model=HandoffRead)
def create_candidate_handoff(request:HandoffCreateRequest,service:ShadowResearchService=Depends(get_shadow_research_service)):
    try:return service.create_handoff(request)
    except LookupError as exc:raise HTTPException(status_code=404,detail=str(exc)) from exc
    except ValueError as exc:raise HTTPException(status_code=422,detail=str(exc)) from exc

@router.get('/ai/handoffs',response_model=list[HandoffRead])
def list_candidate_handoffs(source_type:str|None=None,blueprint:UUID|None=None,variant:UUID|None=None,validation:UUID|None=None,shadow_session:UUID|None=None,status:str|None=None,minimum_readiness:Decimal|None=Query(default=None,ge=0,le=1),symbol:str|None=None,timeframe:str|None=None,regime:str|None=None,limit:int=Query(default=100,ge=1,le=1000),offset:int=Query(default=0,ge=0),service:ShadowResearchService=Depends(get_shadow_research_service)):
    return service.handoffs(source_type=source_type,blueprint=blueprint,variant=variant,validation=validation,shadow_session=shadow_session,status=status,minimum_readiness=minimum_readiness,symbol=symbol,timeframe=timeframe,regime=regime,limit=limit,offset=offset)

@router.get('/ai/handoffs/{handoff_id}',response_model=HandoffRead)
def get_candidate_handoff(handoff_id:UUID,service:ShadowResearchService=Depends(get_shadow_research_service)):
    row=service.handoff(handoff_id)
    if not row:raise HTTPException(status_code=404,detail='candidate handoff not found')
    return row

@router.get('/ai/handoffs/{handoff_id}/readiness')
def candidate_handoff_readiness(handoff_id:UUID,service:ShadowResearchService=Depends(get_shadow_research_service)):
    try:return service.readiness(handoff_id)
    except LookupError as exc:raise HTTPException(status_code=404,detail=str(exc)) from exc

@router.post('/ai/handoffs/{handoff_id}/create-candidate')
def create_candidate_from_handoff(handoff_id:UUID,service:ShadowResearchService=Depends(get_shadow_research_service)):
    try:return service.create_candidate(handoff_id)
    except LookupError as exc:raise HTTPException(status_code=404,detail=str(exc)) from exc
    except ValueError as exc:raise HTTPException(status_code=422,detail=str(exc)) from exc

@router.post('/ai/handoffs/{handoff_id}/reject',response_model=HandoffRead)
def reject_candidate_handoff(handoff_id:UUID,service:ShadowResearchService=Depends(get_shadow_research_service)):
    try:return service.reject_handoff(handoff_id)
    except LookupError as exc:raise HTTPException(status_code=404,detail=str(exc)) from exc
    except ValueError as exc:raise HTTPException(status_code=422,detail=str(exc)) from exc

# Phase 4 adaptive research monitoring. Research-only; no trading control.
from packages.research.ai.monitoring import (
    ResearchMonitoringService, MonitoringPolicyCreate, MonitoringPolicyPatch,
    MonitoringPolicyRead, TriggerRead, JobRead,
)

def get_research_monitoring_service(db:Session=Depends(get_db))->ResearchMonitoringService:return ResearchMonitoringService(db)

@router.post('/ai/monitoring/policies',response_model=MonitoringPolicyRead)
def create_monitoring_policy(request:MonitoringPolicyCreate,service:ResearchMonitoringService=Depends(get_research_monitoring_service)):
    try:return service.create_policy(request)
    except ValueError as exc:raise HTTPException(status_code=422,detail=str(exc)) from exc

@router.get('/ai/monitoring/policies',response_model=list[MonitoringPolicyRead])
def list_monitoring_policies(status:str|None=None,scope_type:str|None=None,symbol:str|None=None,timeframe:str|None=None,regime:str|None=None,strategy:str|None=None,limit:int=Query(default=100,ge=1,le=1000),offset:int=Query(default=0,ge=0),service:ResearchMonitoringService=Depends(get_research_monitoring_service)):
    return service.policies(status=status,scope_type=scope_type,symbol=symbol,timeframe=timeframe,regime=regime,strategy=strategy,limit=limit,offset=offset)

@router.get('/ai/monitoring/policies/{policy_id}',response_model=MonitoringPolicyRead)
def get_monitoring_policy(policy_id:UUID,service:ResearchMonitoringService=Depends(get_research_monitoring_service)):
    row=service.policy(policy_id)
    if not row:raise HTTPException(status_code=404,detail='monitoring policy not found')
    return row

@router.patch('/ai/monitoring/policies/{policy_id}',response_model=MonitoringPolicyRead)
def update_monitoring_policy(policy_id:UUID,request:MonitoringPolicyPatch,service:ResearchMonitoringService=Depends(get_research_monitoring_service)):
    try:return service.update_policy(policy_id,request)
    except LookupError as exc:raise HTTPException(status_code=404,detail=str(exc)) from exc
    except ValueError as exc:raise HTTPException(status_code=422,detail=str(exc)) from exc

@router.post('/ai/monitoring/policies/{policy_id}/evaluate',response_model=list[TriggerRead])
def evaluate_monitoring_policy(policy_id:UUID,service:ResearchMonitoringService=Depends(get_research_monitoring_service)):
    try:return service.evaluate(policy_id)
    except LookupError as exc:raise HTTPException(status_code=404,detail=str(exc)) from exc
    except ValueError as exc:raise HTTPException(status_code=422,detail=str(exc)) from exc

@router.post('/ai/monitoring/policies/{policy_id}/pause',response_model=MonitoringPolicyRead)
def pause_monitoring_policy(policy_id:UUID,service:ResearchMonitoringService=Depends(get_research_monitoring_service)):
    try:return service.pause(policy_id)
    except LookupError as exc:raise HTTPException(status_code=404,detail=str(exc)) from exc

@router.post('/ai/monitoring/policies/{policy_id}/resume',response_model=MonitoringPolicyRead)
def resume_monitoring_policy(policy_id:UUID,service:ResearchMonitoringService=Depends(get_research_monitoring_service)):
    try:return service.resume(policy_id)
    except LookupError as exc:raise HTTPException(status_code=404,detail=str(exc)) from exc

@router.get('/ai/monitoring/triggers',response_model=list[TriggerRead])
def list_monitoring_triggers(policy:UUID|None=None,trigger_type:str|None=None,status:str|None=None,symbol:str|None=None,timeframe:str|None=None,regime:str|None=None,strategy:str|None=None,minimum_severity:Decimal|None=Query(default=None,ge=0,le=1),start:datetime|None=None,end:datetime|None=None,limit:int=Query(default=100,ge=1,le=1000),offset:int=Query(default=0,ge=0),service:ResearchMonitoringService=Depends(get_research_monitoring_service)):
    return service.triggers(policy=policy,trigger_type=trigger_type,status=status,symbol=symbol,timeframe=timeframe,regime=regime,strategy=strategy,minimum_severity=minimum_severity,start=start,end=end,limit=limit,offset=offset)

@router.get('/ai/monitoring/triggers/{trigger_id}',response_model=TriggerRead)
def get_monitoring_trigger(trigger_id:UUID,service:ResearchMonitoringService=Depends(get_research_monitoring_service)):
    row=service.trigger(trigger_id)
    if not row:raise HTTPException(status_code=404,detail='research trigger not found')
    return row

@router.post('/ai/monitoring/triggers/{trigger_id}/queue-research',response_model=JobRead)
def queue_monitoring_trigger(trigger_id:UUID,job_type:str|None=None,service:ResearchMonitoringService=Depends(get_research_monitoring_service)):
    try:return service.queue_research(trigger_id,job_type)
    except LookupError as exc:raise HTTPException(status_code=404,detail=str(exc)) from exc
    except ValueError as exc:raise HTTPException(status_code=422,detail=str(exc)) from exc

@router.post('/ai/monitoring/triggers/{trigger_id}/acknowledge',response_model=TriggerRead)
def acknowledge_monitoring_trigger(trigger_id:UUID,service:ResearchMonitoringService=Depends(get_research_monitoring_service)):
    try:return service.acknowledge(trigger_id)
    except LookupError as exc:raise HTTPException(status_code=404,detail=str(exc)) from exc

@router.get('/ai/adaptive-jobs',response_model=list[JobRead])
def list_adaptive_research_jobs(status:str|None=None,job_type:str|None=None,limit:int=Query(default=100,ge=1,le=1000),offset:int=Query(default=0,ge=0),service:ResearchMonitoringService=Depends(get_research_monitoring_service)):
    return service.jobs(status=status,job_type=job_type,limit=limit,offset=offset)

@router.get('/ai/adaptive-jobs/{job_id}',response_model=JobRead)
def get_adaptive_research_job(job_id:UUID,service:ResearchMonitoringService=Depends(get_research_monitoring_service)):
    row=service.job(job_id)
    if not row:raise HTTPException(status_code=404,detail='adaptive research job not found')
    return row

@router.post('/ai/adaptive-jobs/{job_id}/cancel',response_model=JobRead)
def cancel_adaptive_research_job(job_id:UUID,service:ResearchMonitoringService=Depends(get_research_monitoring_service)):
    try:return service.cancel_job(job_id)
    except LookupError as exc:raise HTTPException(status_code=404,detail=str(exc)) from exc
    except ValueError as exc:raise HTTPException(status_code=422,detail=str(exc)) from exc

@router.get('/ai/monitoring/status')
def get_research_monitoring_status(service:ResearchMonitoringService=Depends(get_research_monitoring_service)):
    return service.monitor_status()

# Phase 4 demo manifest compiler/runtime compatibility governance bridge. No trading activation.
from packages.research.ai.manifest import (
    CompileRequest, CompatibilityRead, DemoManifestService, ManifestRead, ReleaseRead,
)

def get_demo_manifest_service(db:Session=Depends(get_db))->DemoManifestService:return DemoManifestService(db)

@router.post('/ai/demo-manifests/compile',response_model=ManifestRead)
def compile_demo_manifest(request:CompileRequest,service:DemoManifestService=Depends(get_demo_manifest_service)):
    try:return service.compile(request)
    except LookupError as exc:raise HTTPException(status_code=404,detail=str(exc)) from exc
    except ValueError as exc:raise HTTPException(status_code=422,detail=str(exc)) from exc

@router.get('/ai/demo-manifests',response_model=list[ManifestRead])
def list_demo_manifests(candidate:UUID|None=None,blueprint:UUID|None=None,variant:UUID|None=None,status:str|None=None,symbol:str|None=None,timeframe:str|None=None,regime:str|None=None,minimum_compatibility:Decimal|None=Query(default=None,ge=0,le=1),limit:int=Query(default=100,ge=1,le=1000),offset:int=Query(default=0,ge=0),service:DemoManifestService=Depends(get_demo_manifest_service)):
    return service.manifests(candidate=candidate,blueprint=blueprint,variant=variant,status=status,symbol=symbol,timeframe=timeframe,regime=regime,minimum_compatibility=minimum_compatibility,limit=limit,offset=offset)

@router.get('/ai/demo-manifests/{manifest_id}',response_model=ManifestRead)
def get_demo_manifest(manifest_id:UUID,service:DemoManifestService=Depends(get_demo_manifest_service)):
    row=service.manifest(manifest_id)
    if not row:raise HTTPException(status_code=404,detail='demo manifest not found')
    return row

@router.get('/ai/demo-manifests/{manifest_id}/lineage')
def get_demo_manifest_lineage(manifest_id:UUID,service:DemoManifestService=Depends(get_demo_manifest_service)):
    try:return service.lineage(manifest_id)
    except LookupError as exc:raise HTTPException(status_code=404,detail=str(exc)) from exc

@router.post('/ai/demo-manifests/{manifest_id}/check-compatibility',response_model=CompatibilityRead)
def check_demo_manifest_compatibility(manifest_id:UUID,service:DemoManifestService=Depends(get_demo_manifest_service)):
    try:return service.check_compatibility(manifest_id)
    except LookupError as exc:raise HTTPException(status_code=404,detail=str(exc)) from exc
    except ValueError as exc:raise HTTPException(status_code=422,detail=str(exc)) from exc

@router.get('/ai/demo-manifests/{manifest_id}/compatibility',response_model=CompatibilityRead|None)
def get_demo_manifest_compatibility(manifest_id:UUID,service:DemoManifestService=Depends(get_demo_manifest_service)):
    if not service.manifest(manifest_id):raise HTTPException(status_code=404,detail='demo manifest not found')
    return service.compatibility(manifest_id)

@router.get('/ai/demo-manifests/{manifest_id}/readiness')
def get_demo_manifest_readiness(manifest_id:UUID,service:DemoManifestService=Depends(get_demo_manifest_service)):
    try:return service.readiness(manifest_id)
    except LookupError as exc:raise HTTPException(status_code=404,detail=str(exc)) from exc

@router.get('/ai/demo-manifests/{manifest_id}/runtime-contract')
def get_demo_manifest_runtime_contract(manifest_id:UUID,service:DemoManifestService=Depends(get_demo_manifest_service)):
    try:return service.runtime_contract(manifest_id)
    except LookupError as exc:raise HTTPException(status_code=404,detail=str(exc)) from exc

@router.post('/ai/demo-manifests/{manifest_id}/request-review',response_model=ManifestRead)
def request_demo_manifest_review(manifest_id:UUID,service:DemoManifestService=Depends(get_demo_manifest_service)):
    try:return service.request_review(manifest_id)
    except LookupError as exc:raise HTTPException(status_code=404,detail=str(exc)) from exc
    except ValueError as exc:raise HTTPException(status_code=422,detail=str(exc)) from exc

@router.post('/ai/demo-manifests/{manifest_id}/release',response_model=ReleaseRead)
def release_demo_manifest(manifest_id:UUID,service:DemoManifestService=Depends(get_demo_manifest_service)):
    try:return service.release(manifest_id)
    except LookupError as exc:raise HTTPException(status_code=404,detail=str(exc)) from exc
    except ValueError as exc:raise HTTPException(status_code=422,detail=str(exc)) from exc

@router.post('/ai/demo-manifests/{manifest_id}/revoke',response_model=ManifestRead)
def revoke_demo_manifest(manifest_id:UUID,service:DemoManifestService=Depends(get_demo_manifest_service)):
    try:return service.revoke(manifest_id)
    except LookupError as exc:raise HTTPException(status_code=404,detail=str(exc)) from exc

@router.get('/ai/demo-releases',response_model=list[ReleaseRead])
def list_demo_runtime_releases(status:str|None=None,limit:int=Query(default=100,ge=1,le=1000),offset:int=Query(default=0,ge=0),service:DemoManifestService=Depends(get_demo_manifest_service)):
    return service.releases(status=status,limit=limit,offset=offset)

@router.get('/ai/demo-releases/{release_id}',response_model=ReleaseRead)
def get_demo_runtime_release(release_id:UUID,service:DemoManifestService=Depends(get_demo_manifest_service)):
    row=service.release_get(release_id)
    if not row:raise HTTPException(status_code=404,detail='demo runtime release not found')
    return row


@router.get('/ai/integration-health')
def get_phase4_integration_health(service: ResearchIntegrationService = Depends(get_research_integration_service)):
    return service.phase4_integration_health()
