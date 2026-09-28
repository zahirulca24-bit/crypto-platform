import pytest
from models import ShadowResearchSession,ShadowResearchTrade,ResearchCandidateHandoff,ResearchCandidateStrategy,CandidatePromotionEvaluation,DemoOrderModel,PositionModel,TradeOutcome,ResearchObservation,AIStrategyVariant
from packages.research.ai.shadow import ShadowResearchService,ShadowSessionCreateRequest,HandoffCreateRequest,SESSION_VERSION,HANDOFF_VERSION,canonical_hash
from packages.research.ai.validation import BlueprintValidationService,BlueprintValidationRequest
from packages.research.candidates import ResearchCandidateService,PromotionEvaluateRequest
from packages.research.ai.evolution import StrategyEvolutionService,EvolutionRunRequest
from test_research_ai_validation import seed_market,seed_blueprint,low_gates


def source(monkeypatch,db,n=40):
    low_gates(monkeypatch);monkeypatch.setenv('AI_SHADOW_MIN_TRADES','1');monkeypatch.setenv('AI_SHADOW_MIN_READINESS_SCORE','0');monkeypatch.setenv('AI_SHADOW_MAX_DRIFT','1');seed_market(db,n);bp=seed_blueprint(db);val=BlueprintValidationService(db).validate(bp.id,BlueprintValidationRequest(validation_fraction=0));assert val.passed;return bp,val


def test_shadow_session_creation_and_version(monkeypatch,db_session):
    bp,val=source(monkeypatch,db_session);s=ShadowResearchService(db_session).create_session(ShadowSessionCreateRequest(source_type='blueprint',blueprint_id=bp.id));assert s.session_version==SESSION_VERSION and s.status=='created' and s.blueprint_id==bp.id


def test_shadow_requires_accepted_passing_source(monkeypatch,db_session):
    low_gates(monkeypatch);seed_market(db_session,20);bp=seed_blueprint(db_session,status='draft')
    with pytest.raises(ValueError):ShadowResearchService(db_session).create_session(ShadowSessionCreateRequest(source_type='blueprint',blueprint_id=bp.id))


def test_shadow_process_closed_candles_bounded_and_idempotent(monkeypatch,db_session):
    monkeypatch.setenv('AI_SHADOW_MAX_CANDLES_PER_PROCESS','8');bp,val=source(monkeypatch,db_session,30);svc=ShadowResearchService(db_session);s=svc.create_session(ShadowSessionCreateRequest(source_type='blueprint',blueprint_id=bp.id));a=svc.process(s.id);assert a.observed_candle_count==8 and a.status=='running';count=db_session.query(ShadowResearchTrade).count();b=svc.process(s.id);assert b.observed_candle_count==16 and db_session.query(ShadowResearchTrade).count()>=count
    # No duplicate event key exists and all trades are research-only records.
    keys=[(x.session_id,x.signal_time,x.entry_time,x.parameter_set_hash) for x in db_session.query(ShadowResearchTrade).all()];assert len(keys)==len(set(keys));assert db_session.query(DemoOrderModel).count()==0 and db_session.query(PositionModel).count()==0 and db_session.query(TradeOutcome).count()==0


def test_shadow_reuses_next_candle_and_costs(monkeypatch,db_session):
    bp,val=source(monkeypatch,db_session,30);svc=ShadowResearchService(db_session);s=svc.create_session(ShadowSessionCreateRequest(source_type='blueprint',blueprint_id=bp.id));svc.process(s.id);rows=svc.trades(s.id);assert rows;assert rows[0].signal_time<rows[0].entry_time and rows[0].simulated_fees>0 and rows[0].simulated_slippage>0


def test_shadow_pause_resume_complete_and_observations(monkeypatch,db_session):
    bp,val=source(monkeypatch,db_session);svc=ShadowResearchService(db_session);s=svc.create_session(ShadowSessionCreateRequest(source_type='blueprint',blueprint_id=bp.id));svc.process(s.id);assert svc.pause(s.id).status=='paused';assert svc.resume(s.id).status=='running';assert svc.complete(s.id).status=='completed';events={x.event_type for x in db_session.query(ResearchObservation)};assert {'ai_shadow_session_created','ai_shadow_session_processed','ai_shadow_session_completed','ai_shadow_drift_evaluated'}<=events


def test_drift_and_readiness_deterministic(monkeypatch,db_session):
    bp,val=source(monkeypatch,db_session);svc=ShadowResearchService(db_session);s=svc.create_session(ShadowSessionCreateRequest(source_type='blueprint',blueprint_id=bp.id));a=svc.process(s.id);assert 0<=float(a.drift_metrics['drift_score'])<=1 and 0<=float(a.readiness_score)<=1


def test_variant_shadow_source(monkeypatch,db_session):
    bp,val=source(monkeypatch,db_session);es=StrategyEvolutionService(db_session);es.create_run(EvolutionRunRequest(source_blueprint_id=bp.id,source_validation_id=val.id,requested_variants=1));v=es.list_variants(blueprint=bp.id)[0];vr=es.validate_variant(v.id,BlueprintValidationRequest(validation_fraction=0));row=db_session.get(AIStrategyVariant,v.id);row.status='validated';db_session.commit();s=ShadowResearchService(db_session).create_session(ShadowSessionCreateRequest(source_type='variant',variant_id=v.id));assert s.variant_id==v.id


def test_handoff_passing_validation_and_idempotency(monkeypatch,db_session):
    bp,val=source(monkeypatch,db_session);svc=ShadowResearchService(db_session);req=HandoffCreateRequest(source_type='blueprint',validation_id=val.id);a=svc.create_handoff(req);b=svc.create_handoff(req);assert a.id==b.id and a.handoff_version==HANDOFF_VERSION and a.status=='readiness_passed' and len(a.configuration_hash)==64


def test_failed_validation_blocks_handoff(monkeypatch,db_session):
    bp,val=source(monkeypatch,db_session);row=db_session.get(__import__('models').BlueprintValidationRun,val.id);row.passed=False;db_session.commit();h=ShadowResearchService(db_session).create_handoff(HandoffCreateRequest(source_type='blueprint',validation_id=val.id));assert h.status=='blocked' and 'passing_completed_validation_required' in h.blocking_reasons


def test_required_shadow_and_poor_shadow_block(monkeypatch,db_session):
    monkeypatch.setenv('AI_HANDOFF_REQUIRE_SHADOW','true');bp,val=source(monkeypatch,db_session);h=ShadowResearchService(db_session).create_handoff(HandoffCreateRequest(source_type='blueprint',validation_id=val.id));assert h.status=='blocked' and 'shadow_session_required' in h.blocking_reasons


def test_explicit_candidate_creation_reuses_phase3_and_starts_unapproved(monkeypatch,db_session):
    bp,val=source(monkeypatch,db_session);svc=ShadowResearchService(db_session);h=svc.create_handoff(HandoffCreateRequest(source_type='blueprint',validation_id=val.id));c=svc.create_candidate(h.id);c2=svc.create_candidate(h.id);assert c.id==c2.id and c.status=='draft';assert db_session.query(ResearchCandidateStrategy).count()==1 and db_session.query(CandidatePromotionEvaluation).count()==0
    assert svc.handoff(h.id).created_candidate_id==c.id


def test_phase3_promotion_still_required(monkeypatch,db_session):
    bp,val=source(monkeypatch,db_session);svc=ShadowResearchService(db_session);h=svc.create_handoff(HandoffCreateRequest(source_type='blueprint',validation_id=val.id));c=svc.create_candidate(h.id);cs=ResearchCandidateService(db_session);assert cs.promotion(c.id) is None
    with pytest.raises(ValueError):cs.approve_demo(c.id)


def test_handoff_readiness_label_and_reject(monkeypatch,db_session):
    bp,val=source(monkeypatch,db_session);svc=ShadowResearchService(db_session);h=svc.create_handoff(HandoffCreateRequest(source_type='blueprint',validation_id=val.id));r=svc.readiness(h.id);assert r['message']=='Demo readiness does not mean Demo activation.' and r['research_only'] is True;assert svc.reject_handoff(h.id).status=='rejected'


def test_safety_no_execution_or_live_capabilities():
    svc=ShadowResearchService(None);forbidden=('submit_order','place_order','start_bot','stop_bot','bypass_risk','decrypt_credentials','approve_demo','approve_live','activate_live','allocate_capital')
    assert all(not hasattr(svc,x) for x in forbidden);src=open('packages/research/ai/shadow.py').read().lower();assert 'import ccxt' not in src and 'eval(' not in src and 'exec(' not in src

def test_shadow_ignores_unclosed_future_candles(monkeypatch,db_session):
    low_gates(monkeypatch);monkeypatch.setenv('AI_SHADOW_MIN_TRADES','1');seed_market(db_session,20,include_future_unclosed=True);bp=seed_blueprint(db_session);val=BlueprintValidationService(db_session).validate(bp.id,BlueprintValidationRequest(validation_fraction=0));svc=ShadowResearchService(db_session);s=svc.create_session(ShadowSessionCreateRequest(source_type='blueprint',blueprint_id=bp.id));out=svc.process(s.id);assert out.last_processed_candle_time<=val.data_end


def test_shadow_conservative_intrabar_rule_reused(monkeypatch,db_session):
    low_gates(monkeypatch);monkeypatch.setenv('AI_SHADOW_MIN_TRADES','1');monkeypatch.setenv('AI_SHADOW_MIN_READINESS_SCORE','0');seed_market(db_session,20,both_hit=True);bp=seed_blueprint(db_session);val=BlueprintValidationService(db_session).validate(bp.id,BlueprintValidationRequest(validation_fraction=0));svc=ShadowResearchService(db_session);s=svc.create_session(ShadowSessionCreateRequest(source_type='blueprint',blueprint_id=bp.id));svc.process(s.id);rows=svc.trades(s.id);assert rows and rows[0].exit_reason=='stop_loss'


def test_handoff_quality_overfit_and_protection_blocks(monkeypatch,db_session):
    bp,val=source(monkeypatch,db_session);from models import BlueprintValidationRun
    monkeypatch.setenv('AI_VALIDATION_MIN_DATA_QUALITY','.6');monkeypatch.setenv('AI_VALIDATION_MAX_OVERFIT_RISK','.65')
    row=db_session.get(BlueprintValidationRun,val.id);row.data_quality_score=.1;row.overfit_risk_score=.95;bp.protection_logic={};bp.exit_logic={"take_profit_pct":1};db_session.commit();h=ShadowResearchService(db_session).create_handoff(HandoffCreateRequest(source_type='blueprint',validation_id=val.id));assert {'mandatory_protection_required','overfit_risk_too_high','data_quality_too_low'}<=set(h.blocking_reasons)
