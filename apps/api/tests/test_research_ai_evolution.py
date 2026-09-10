from decimal import Decimal
import copy
import pytest
from models import AIStrategyVariant, AIStrategyEvolutionRun, ChampionChallengerComparison, ResearchCandidateStrategy, DemoOrderModel, PositionModel, ResearchObservation, BlueprintValidationRun
from packages.research.ai.evolution import StrategyEvolutionService, EvolutionRunRequest, CompareRequest, GENERATION_VERSION, COMPARISON_VERSION, canonical_hash
from packages.research.ai.validation import BlueprintValidationService, BlueprintValidationRequest
from test_research_ai_validation import seed_blueprint, seed_market, low_gates


def source(monkeypatch,db,passed=True):
    low_gates(monkeypatch);seed_market(db,40);bp=seed_blueprint(db)
    v=BlueprintValidationService(db).validate(bp.id,BlueprintValidationRequest(validation_fraction=.25))
    row=db.get(BlueprintValidationRun,v.id);row.passed=passed;row.status='completed';db.commit();return bp,row


def test_variant_generation_from_passing_validation(monkeypatch,db_session):
    bp,val=source(monkeypatch,db_session);svc=StrategyEvolutionService(db_session);run=svc.create_run(EvolutionRunRequest(source_blueprint_id=bp.id,source_validation_id=val.id,requested_variants=4));assert run.status=='completed' and run.generated_variants>0; assert svc.list_variants(blueprint=bp.id)


def test_failed_source_requires_diagnostic_optin(monkeypatch,db_session):
    bp,val=source(monkeypatch,db_session,False);svc=StrategyEvolutionService(db_session)
    with pytest.raises(ValueError):svc.create_run(EvolutionRunRequest(source_blueprint_id=bp.id,source_validation_id=val.id))
    r=svc.create_run(EvolutionRunRequest(source_blueprint_id=bp.id,source_validation_id=val.id,allow_failed_source=True));assert r.status=='completed'


def test_neighboring_parameter_and_complexity_reduction(monkeypatch,db_session):
    bp,val=source(monkeypatch,db_session);val.parameter_set={'rsi_threshold':40};db_session.commit();svc=StrategyEvolutionService(db_session);svc.create_run(EvolutionRunRequest(source_blueprint_id=bp.id,source_validation_id=val.id,run_type='complexity_reduction',requested_variants=5));vs=svc.list_variants(blueprint=bp.id);assert any(v.variant_type=='parameter_variant' for v in vs)


def test_regime_filter_and_risk_tightening(monkeypatch,db_session):
    bp,val=source(monkeypatch,db_session);bp.risk_constraints={'max_risk_per_trade':2};bp.regime_scope=['trending_bull','ranging'];val.combined_metrics={**val.combined_metrics,'regime_performance':{'trending_bull':{'expectancy':2},'ranging':{'expectancy':-1}}};db_session.commit();svc=StrategyEvolutionService(db_session);svc.create_run(EvolutionRunRequest(source_blueprint_id=bp.id,source_validation_id=val.id,requested_variants=10));vs=svc.list_variants(blueprint=bp.id);assert any(v.variant_type=='regime_filter_variant' for v in vs);rv=next(v for v in vs if v.variant_type=='risk_constraint_variant');assert rv.risk_constraints['max_risk_per_trade']<2


def test_mutation_budget_and_safety_rejections(monkeypatch,db_session):
    bp,val=source(monkeypatch,db_session);svc=StrategyEvolutionService(db_session);base={'symbol_scope':bp.symbol_scope,'timeframe_scope':bp.timeframe_scope,'regime_scope':bp.regime_scope,'feature_requirements':bp.feature_requirements,'indicator_requirements':['made_up_indicator'],'entry_logic':bp.entry_logic,'exit_logic':bp.exit_logic,'protection_logic':bp.protection_logic,'risk_constraints':bp.risk_constraints,'parameter_values':{},'parameter_space_reference':{}}
    with pytest.raises(ValueError):svc._validate_mutation(bp,base)
    x=copy.deepcopy(base);x['indicator_requirements']=bp.indicator_requirements;x['entry_logic']={'all':[{'indicator':'rsi','operator':'<','value':'future candle'}],'any':[]}
    with pytest.raises(ValueError):svc._validate_mutation(bp,x)
    x=copy.deepcopy(base);x['indicator_requirements']=bp.indicator_requirements;x['risk_constraints']={'note':'bypass risk'}
    with pytest.raises(ValueError):svc._validate_mutation(bp,x)
    x=copy.deepcopy(base);x['indicator_requirements']=bp.indicator_requirements;x['entry_logic']={'all':[{'indicator':'rsi','operator':'<','value':'eval(1)'}],'any':[]}
    with pytest.raises(ValueError):svc._validate_mutation(bp,x)


def test_variant_hash_idempotency_and_run_bounds(monkeypatch,db_session):
    monkeypatch.setenv('AI_EVOLUTION_MAX_VARIANTS_PER_GENERATION','2');bp,val=source(monkeypatch,db_session);svc=StrategyEvolutionService(db_session);req=EvolutionRunRequest(source_blueprint_id=bp.id,source_validation_id=val.id,requested_variants=10);a=svc.create_run(req);b=svc.create_run(req);assert a.id==b.id and a.requested_variants==2 and len(a.configuration_hash)==64;assert db_session.query(AIStrategyEvolutionRun).count()==1


def test_variant_validation_reuses_p404(monkeypatch,db_session):
    bp,val=source(monkeypatch,db_session);svc=StrategyEvolutionService(db_session);svc.create_run(EvolutionRunRequest(source_blueprint_id=bp.id,source_validation_id=val.id,requested_variants=1));v=svc.list_variants(blueprint=bp.id)[0];r=svc.validate_variant(v.id,BlueprintValidationRequest(validation_fraction=.25));assert r.configuration['source_variant_id']==str(v.id);assert svc.variant_validations(v.id)[0].id==r.id


def fake_validation(db,bp,score,expectancy,pf,dd,stability=.8,quality=.8,overfit=.2,cost=.1,tag='x'):
    base=db.query(BlueprintValidationRun).filter_by(blueprint_id=bp.id).first();r=BlueprintValidationRun(blueprint_id=bp.id,validation_type='historical_backtest',status='completed',validation_version='1.0.0',symbol_scope=['BTC/USDT'],timeframe_scope=['1h'],regime_scope=['trending_bull'],data_start=base.data_start,data_end=base.data_end,train_start=base.train_start,train_end=base.train_end,validation_start=base.validation_start,validation_end=base.validation_end,configuration={**base.configuration,'data_scope':{'candle_ids':['same']},'fee_bps':10,'slippage_bps':5,'execution_convention':'signal_close_next_candle_open','intrabar_conflict_policy':'stop_first','gates':{}},configuration_hash=(tag*64)[:64],parameter_set={},parameter_set_hash=(tag*64)[:64],parameter_results=[],sample_size=40,signal_count=10,simulated_trade_count=10,train_metrics={'trade_count':10,'expectancy':expectancy},validation_metrics={'trade_count':10,'expectancy':expectancy,'profit_factor':pf,'max_drawdown':dd},combined_metrics={'trade_count':10,'expectancy':expectancy,'profit_factor':pf,'max_drawdown':dd},robustness_metrics={},execution_cost_metrics={'cost_drag':cost},score=Decimal(str(score)),stability_score=Decimal(str(stability)),data_quality_score=Decimal(str(quality)),overfit_risk_score=Decimal(str(overfit)),passed=True,failure_reasons=[],warnings=[]);db.add(r);db.commit();db.refresh(r);return r


def test_fair_comparison_and_challenger_win(monkeypatch,db_session):
    monkeypatch.setenv('AI_EVOLUTION_MIN_CHALLENGER_IMPROVEMENT','0.01');bp,src=source(monkeypatch,db_session);svc=StrategyEvolutionService(db_session);svc.create_run(EvolutionRunRequest(source_blueprint_id=bp.id,source_validation_id=src.id,requested_variants=1));v=svc.list_variants(blueprint=bp.id)[0];champ=fake_validation(db_session,bp,.5,1,1.1,10,tag='a');chal=fake_validation(db_session,bp,.8,3,1.8,5,.9,.9,.1,.05,tag='b');c=svc.compare(CompareRequest(challenger_variant_id=v.id,challenger_validation_id=chal.id,champion_validation_id=champ.id));assert c.challenger_wins and svc.champion(bp.id).id==v.id


def test_incompatible_scope_blocks_comparison(monkeypatch,db_session):
    bp,src=source(monkeypatch,db_session);svc=StrategyEvolutionService(db_session);svc.create_run(EvolutionRunRequest(source_blueprint_id=bp.id,source_validation_id=src.id,requested_variants=1));v=svc.list_variants(blueprint=bp.id)[0];a=fake_validation(db_session,bp,.5,1,1,10,tag='a');b=fake_validation(db_session,bp,.6,2,1.2,8,tag='b');b.configuration={**b.configuration,'fee_bps':99};db_session.commit()
    with pytest.raises(ValueError):svc.compare(CompareRequest(challenger_variant_id=v.id,challenger_validation_id=b.id,champion_validation_id=a.id))


def test_microscopic_and_overfit_heavy_challenger_rejected(monkeypatch,db_session):
    monkeypatch.setenv('AI_EVOLUTION_MIN_CHALLENGER_IMPROVEMENT','0.2');bp,src=source(monkeypatch,db_session);svc=StrategyEvolutionService(db_session);svc.create_run(EvolutionRunRequest(source_blueprint_id=bp.id,source_validation_id=src.id,requested_variants=2));v=svc.list_variants(blueprint=bp.id)[0];a=fake_validation(db_session,bp,.7,2,1.5,7,tag='a');b=fake_validation(db_session,bp,.71,2.05,1.51,6.9,.8,.8,.9,.1,tag='b');c=svc.compare(CompareRequest(challenger_variant_id=v.id,challenger_validation_id=b.id,champion_validation_id=a.id));assert not c.challenger_wins and c.decision=='champion_retained'


def test_tradeoff_can_win_without_raw_pnl_authority(monkeypatch,db_session):
    monkeypatch.setenv('AI_EVOLUTION_MIN_CHALLENGER_IMPROVEMENT','0.01');bp,src=source(monkeypatch,db_session);svc=StrategyEvolutionService(db_session);svc.create_run(EvolutionRunRequest(source_blueprint_id=bp.id,source_validation_id=src.id,requested_variants=1));v=svc.list_variants(blueprint=bp.id)[0];a=fake_validation(db_session,bp,.45,2.0,1.2,35,.4,.8,.5,.2,tag='a');b=fake_validation(db_session,bp,.75,1.8,1.5,5,.95,.9,.1,.03,tag='b');c=svc.compare(CompareRequest(challenger_variant_id=v.id,challenger_validation_id=b.id,champion_validation_id=a.id));assert c.challenger_wins and c.drawdown_difference<0


def test_lifecycle_events_and_research_only_safety(monkeypatch,db_session):
    bp,val=source(monkeypatch,db_session);svc=StrategyEvolutionService(db_session);svc.create_run(EvolutionRunRequest(source_blueprint_id=bp.id,source_validation_id=val.id,requested_variants=1));events={x.event_type for x in db_session.query(ResearchObservation).all()};assert 'ai_strategy_evolution_started' in events and 'ai_strategy_variant_generated' in events and 'ai_strategy_evolution_completed' in events
    forbidden=('submit_order','place_order','start_bot','stop_bot','bypass_risk','decrypt_credentials','approve_candidate','approve_demo','approve_live')
    assert all(not hasattr(svc,x) for x in forbidden);assert db_session.query(ResearchCandidateStrategy).count()==0 and db_session.query(DemoOrderModel).count()==0 and db_session.query(PositionModel).count()==0


def test_versions_and_canonical_hash():
    assert GENERATION_VERSION=='1.0.0' and COMPARISON_VERSION=='1.0.0';assert canonical_hash({'a':1,'b':2})==canonical_hash({'b':2,'a':1})

class FakeEvolutionProvider:
    provider_name='fake'; model_name='fake-evolution'; configured=True
    def __init__(self): self.calls=0
    def analyze_research_context(self,*,context,prompt):
        self.calls+=1
        return {'variants':[{'variant_type':'combined_variant','changes':{'regime_scope':['trending_bull']},'summary':{'source':'ai_suggestion'}}]}
    def health_check(self): return {'configured':True}


def test_ai_assisted_generation_uses_max_one_provider_call(monkeypatch,db_session):
    bp,val=source(monkeypatch,db_session); provider=FakeEvolutionProvider();svc=StrategyEvolutionService(db_session,provider=provider)
    r=svc.create_run(EvolutionRunRequest(source_blueprint_id=bp.id,source_validation_id=val.id,requested_variants=3,use_ai=True))
    assert r.status=='completed' and provider.calls==1
    assert any(v.generation_method=='ai_assisted' for v in svc.list_variants(blueprint=bp.id))


def test_generation_count_is_hard_bounded_to_one(monkeypatch,db_session):
    monkeypatch.setenv('AI_EVOLUTION_MAX_GENERATIONS_PER_REQUEST','99');bp,val=source(monkeypatch,db_session);r=StrategyEvolutionService(db_session).create_run(EvolutionRunRequest(source_blueprint_id=bp.id,source_validation_id=val.id,requested_variants=2));assert r.configuration['max_generations_per_request']==1


def test_existing_research_champion_is_replaced_only_when_challenger_wins(monkeypatch,db_session):
    monkeypatch.setenv('AI_EVOLUTION_MIN_CHALLENGER_IMPROVEMENT','0.01');bp,src=source(monkeypatch,db_session);svc=StrategyEvolutionService(db_session);svc.create_run(EvolutionRunRequest(source_blueprint_id=bp.id,source_validation_id=src.id,requested_variants=2));vs=svc.list_variants(blueprint=bp.id);old,new=vs[:2];old.status='champion';db_session.query(AIStrategyVariant).filter_by(id=old.id).update({'status':'champion'});db_session.commit();champ=fake_validation(db_session,bp,.4,.5,1.0,20,.4,.7,.5,.2,tag='c');chal=fake_validation(db_session,bp,.9,4,2.0,4,.95,.95,.1,.02,tag='d');result=svc.compare(CompareRequest(challenger_variant_id=new.id,challenger_validation_id=chal.id,champion_validation_id=champ.id,champion_variant_id=old.id));old_row=db_session.get(AIStrategyVariant,old.id);new_row=db_session.get(AIStrategyVariant,new.id);assert result.challenger_wins and new_row.status=='champion' and old_row.status=='challenger'


def test_champion_remains_when_challenger_loses(monkeypatch,db_session):
    monkeypatch.setenv('AI_EVOLUTION_MIN_CHALLENGER_IMPROVEMENT','0.2');bp,src=source(monkeypatch,db_session);svc=StrategyEvolutionService(db_session);svc.create_run(EvolutionRunRequest(source_blueprint_id=bp.id,source_validation_id=src.id,requested_variants=2));vs=svc.list_variants(blueprint=bp.id);old,new=vs[:2];db_session.query(AIStrategyVariant).filter_by(id=old.id).update({'status':'champion'});db_session.commit();champ=fake_validation(db_session,bp,.8,3,1.8,5,.9,.9,.1,.05,tag='e');chal=fake_validation(db_session,bp,.5,1,1.1,15,.5,.8,.4,.15,tag='f');result=svc.compare(CompareRequest(challenger_variant_id=new.id,challenger_validation_id=chal.id,champion_validation_id=champ.id,champion_variant_id=old.id));old_row=db_session.get(AIStrategyVariant,old.id);assert not result.challenger_wins and old_row.status=='champion'


def test_variant_filter_by_validation_passed(monkeypatch,db_session):
    bp,src=source(monkeypatch,db_session);svc=StrategyEvolutionService(db_session);svc.create_run(EvolutionRunRequest(source_blueprint_id=bp.id,source_validation_id=src.id,requested_variants=1));v=svc.list_variants(blueprint=bp.id)[0];r=svc.validate_variant(v.id,BlueprintValidationRequest(validation_fraction=0));rows=svc.list_variants(blueprint=bp.id,validation_passed=bool(r.passed));assert any(x.id==v.id for x in rows)
