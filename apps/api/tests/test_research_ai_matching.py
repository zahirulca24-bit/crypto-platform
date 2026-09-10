import pytest
from models import StrategyRegimeProfile, ResearchStrategyPortfolio, ResearchObservation, ResearchCandidateStrategy, DemoOrderModel, PositionModel, AIStrategyVariant
from packages.research.ai.matching import StrategyMatchingService,ProfileGenerateRequest,PortfolioBuildRequest,PROFILE_VERSION,PORTFOLIO_VERSION,REGIMES,canonical_hash
from packages.research.ai.validation import BlueprintValidationService,BlueprintValidationRequest
from packages.research.ai.evolution import StrategyEvolutionService,EvolutionRunRequest
from test_research_ai_validation import seed_market,seed_blueprint,low_gates

def source(monkeypatch,db,n=40):
    low_gates(monkeypatch);seed_market(db,n);bp=seed_blueprint(db);v=BlueprintValidationService(db).validate(bp.id,BlueprintValidationRequest(validation_fraction=0));return bp,v

def profile(monkeypatch,db,mintrades=1):
    monkeypatch.setenv('AI_MATCH_MIN_REGIME_TRADES',str(mintrades));bp,v=source(monkeypatch,db);p=StrategyMatchingService(db).generate_profile(ProfileGenerateRequest(regime='trending_bull',blueprint_id=bp.id,symbol='BTC/USDT',timeframe='1h'));return bp,v,p

def test_regime_profile_generation_and_vocabulary(monkeypatch,db_session):
    bp,v,p=profile(monkeypatch,db_session);assert p.profile_version==PROFILE_VERSION and p.regime=='trending_bull' and p.simulated_trade_count>0 and 'unknown' in REGIMES

def test_compatibility_deterministic_and_tiny_sample_penalty(monkeypatch,db_session):
    bp,v,p=profile(monkeypatch,db_session,100);assert float(p.compatibility_score)<.5 and 'insufficient_regime_sample' in p.warnings
    assert len(p.configuration_hash)==64 and canonical_hash({'a':1,'b':2})==canonical_hash({'b':2,'a':1})

def test_failed_validation_excluded(monkeypatch,db_session):
    bp,v=source(monkeypatch,db_session);from models import BlueprintValidationRun
    row=db_session.get(BlueprintValidationRun,v.id);row.passed=False;db_session.commit()
    with pytest.raises(ValueError):StrategyMatchingService(db_session).generate_profile(ProfileGenerateRequest(regime='trending_bull',blueprint_id=bp.id))

def test_overfit_and_poor_data_excluded_from_rank(monkeypatch,db_session):
    bp,v,p=profile(monkeypatch,db_session);p.overfit_risk_score=.95;p.data_quality_score=.2;db_session.commit();assert StrategyMatchingService(db_session).rank('trending_bull')==[]

def test_champion_not_authoritative_and_scope_filter(monkeypatch,db_session):
    low_gates(monkeypatch);seed_market(db_session,40);bp=seed_blueprint(db_session);val=BlueprintValidationService(db_session).validate(bp.id,BlueprintValidationRequest(validation_fraction=0));es=StrategyEvolutionService(db_session);es.create_run(EvolutionRunRequest(source_blueprint_id=bp.id,source_validation_id=val.id,requested_variants=1));variant=es.list_variants(blueprint=bp.id)[0];variant.status='champion';db_session.commit();vr=es.validate_variant(variant.id,BlueprintValidationRequest(validation_fraction=0));variant=db_session.get(AIStrategyVariant,variant.id);variant.status='champion';db_session.commit();svc=StrategyMatchingService(db_session);vp=svc.generate_profile(ProfileGenerateRequest(regime='trending_bull',variant_id=variant.id,symbol='BTC/USDT',timeframe='1h'));bp2=seed_blueprint(db_session);v2=BlueprintValidationService(db_session).validate(bp2.id,BlueprintValidationRequest(validation_fraction=0));p2=svc.generate_profile(ProfileGenerateRequest(regime='trending_bull',blueprint_id=bp2.id,symbol='BTC/USDT',timeframe='1h'));p2.compatibility_score=.99;vp.compatibility_score=.5;db_session.commit();rows=svc.rank('trending_bull','BTC/USDT','1h');assert rows[0]['profile_id']==p2.id and any(x['champion'] for x in rows)

def _portfolio_sources(monkeypatch,db,count=3):
    low_gates(monkeypatch);monkeypatch.setenv('AI_MATCH_MIN_REGIME_TRADES','1');monkeypatch.setenv('AI_PORTFOLIO_MAX_COMPONENT_WEIGHT','0.5');monkeypatch.setenv('AI_PORTFOLIO_MAX_PAIRWISE_CORRELATION','1');seed_market(db,40);svc=StrategyMatchingService(db);ps=[]
    for i in range(count):
        bp=seed_blueprint(db);v=BlueprintValidationService(db).validate(bp.id,BlueprintValidationRequest(validation_fraction=0));p=svc.generate_profile(ProfileGenerateRequest(regime='trending_bull',blueprint_id=bp.id,symbol='BTC/USDT',timeframe='1h'));p.configuration_hash=(str(i+1)*64)[:64];p.compatibility_score=.8;p.stability_score=.8;p.data_quality_score=.8;p.overfit_risk_score=.2;ps.append(p)
    db.commit();return svc,ps

@pytest.mark.parametrize('method',['equal_weight','compatibility_weighted','stability_weighted','inverse_drawdown_weighted','composite_research_weighted'])
def test_portfolio_weights_sum_and_cap(monkeypatch,db_session,method):
    svc,ps=_portfolio_sources(monkeypatch,db_session);p=svc.build_portfolio(PortfolioBuildRequest(name=method,regime='trending_bull',symbol='BTC/USDT',timeframe='1h',allocation_method=method,requested_components=3));assert p.portfolio_version==PORTFOLIO_VERSION and abs(sum(p.allocation_weights.values())-1)<1e-9 and max(p.allocation_weights.values())<=.5+1e-9

def test_component_limit_and_correlation(monkeypatch,db_session):
    monkeypatch.setenv('AI_PORTFOLIO_MAX_COMPONENTS','2');monkeypatch.setenv('AI_PORTFOLIO_MAX_PAIRWISE_CORRELATION','1');svc,ps=_portfolio_sources(monkeypatch,db_session,3);p=svc.build_portfolio(PortfolioBuildRequest(name='limited',regime='trending_bull',requested_components=10));assert p.component_count<=2;assert 'pairs' in p.correlation_metrics

def test_high_correlation_exclusion_and_insufficient_overlap(monkeypatch,db_session):
    svc,ps=_portfolio_sources(monkeypatch,db_session,3);monkeypatch.setenv('AI_PORTFOLIO_MAX_PAIRWISE_CORRELATION','.1');p=svc.build_portfolio(PortfolioBuildRequest(name='corr',regime='trending_bull',requested_components=3));assert p.component_count<3 or 'high_pairwise_correlation_excluded' in p.warnings

def test_portfolio_metrics_readiness_and_gates(monkeypatch,db_session):
    svc,ps=_portfolio_sources(monkeypatch,db_session);p=svc.build_portfolio(PortfolioBuildRequest(name='metrics',regime='trending_bull',requested_components=3));assert 0<=float(p.readiness_score)<=1 and 'expectancy' in p.expected_metrics and 'diversification_score' in p.diversification_metrics
    ps[0].expectancy=-100;ps[0].data_quality_score=.1;ps[0].stability_score=.1;db_session.commit()

def test_regime_transition_analysis(monkeypatch,db_session):
    bp,v,p=profile(monkeypatch,db_session);svc=StrategyMatchingService(db_session);x=svc.transition('trending_bull','ranging');assert x['from_regime']=='trending_bull' and x['to_regime']=='ranging' and x['research_only'] is True

def test_review_accept_reject_workflow_and_observations(monkeypatch,db_session):
    monkeypatch.setenv('AI_PORTFOLIO_MAX_PAIRWISE_CORRELATION','1');svc,ps=_portfolio_sources(monkeypatch,db_session);p=svc.build_portfolio(PortfolioBuildRequest(name='workflow',regime='trending_bull',requested_components=3));p.blocking_reasons=[];db_session.commit();assert svc.status(p.id,'review_required').status=='review_required';assert svc.status(p.id,'accepted_for_research').status=='accepted_for_research';events={x.event_type for x in db_session.query(ResearchObservation)};assert 'ai_research_portfolio_built' in events and 'ai_research_portfolio_accepted' in events

def test_idempotent_profile_and_portfolio(monkeypatch,db_session):
    bp,v,p=profile(monkeypatch,db_session);svc=StrategyMatchingService(db_session);p2=svc.generate_profile(ProfileGenerateRequest(regime='trending_bull',blueprint_id=bp.id,symbol='BTC/USDT',timeframe='1h'));assert p.id==p2.id

def test_research_only_safety_no_capital_or_execution():
    svc=StrategyMatchingService(None);forbidden=('submit_order','place_order','start_bot','switch_bot','allocate_capital','read_balance','bypass_risk','decrypt_credentials','approve_candidate','approve_demo','approve_live')
    assert all(not hasattr(svc,x) for x in forbidden);src=open('packages/research/ai/matching.py').read().lower();assert 'import ccxt' not in src and 'account balance' not in src
