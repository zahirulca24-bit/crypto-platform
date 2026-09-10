from datetime import datetime, timezone, timedelta
from decimal import Decimal
import uuid
import pytest

from models import AIStrategyBlueprint, BlueprintValidationRun, BlueprintSimulatedTrade, MarketFeatureSnapshot, MarketRegimeSnapshot, OHLCVCandle, ResearchCandidateStrategy, DemoOrderModel, PositionModel, ResearchObservation
from packages.research.ai.validation import BlueprintValidationService, BlueprintValidationRequest, LogicInterpreter, VALIDATION_VERSION, EXECUTION_CONVENTION, canonical_hash


def seed_blueprint(db, status="accepted_for_validation", entry_logic=None, exit_logic=None, parameter_space=None):
    bp=AIStrategyBlueprint(name="RSI validation",description="research only",blueprint_type="multi_signal",status=status,
      base_strategy_name="momentum",base_strategy_version="1.0",symbol_scope=["BTC/USDT"],timeframe_scope=["1h"],regime_scope=["trending_bull"],
      feature_requirements=["rsi"],indicator_requirements=["rsi"],entry_logic=entry_logic or {"all":[{"indicator":"rsi","operator":"<","value":40}],"any":[]},
      exit_logic=exit_logic or {"take_profit_pct":0.5,"stop_loss_pct":0.5,"max_holding_candles":3},protection_logic={"stop_loss_required":True},risk_constraints={"max_risk_per_trade_pct":1},
      parameter_space=parameter_space or {},expected_behavior={},invalidation_conditions={},evidence_summary={},evidence_scope={},estimated_complexity="low",estimated_data_requirements={},readiness_score=Decimal("0.8"),warnings=[],blocking_reasons=[],provider="fake",model_name="fake",prompt_version="1.0.0",blueprint_version="1.0.0",configuration={},configuration_hash=uuid.uuid4().hex+uuid.uuid4().hex,parent_blueprint_id=None)
    db.add(bp);db.commit();db.refresh(bp);return bp


def seed_market(db,n=36,both_hit=False,include_future_unclosed=False):
    start=datetime(2026,1,1,tzinfo=timezone.utc); rows=[]
    for i in range(n):
        base=Decimal("100")+Decimal(i%5)
        # Signal every fourth candle; following entry candle usually wins unless both_hit requested.
        is_signal=i%4==0
        o=base; high=o*(Decimal("1.02") if both_hit or i%4==1 else Decimal("1.003")); low=o*(Decimal("0.98") if both_hit else Decimal("0.997")); close=o*(Decimal("1.001"))
        c=OHLCVCandle(exchange="binance",symbol="BTC/USDT",timeframe="1h",open_time=start+timedelta(hours=i),open=o,high=high,low=low,close=close,volume=Decimal("1000"),is_closed=True)
        db.add(c);db.flush()
        f=MarketFeatureSnapshot(candle_id=c.id,exchange="binance",symbol="BTC/USDT",timeframe="1h",candle_open_time=c.open_time,feature_version="1.0.0",configuration={},configuration_hash=(f"{i:064x}"[-64:]),rsi=Decimal("30" if is_signal else "60"),ema_fast=close,ema_slow=o,volatility=Decimal("0.01"),atr=Decimal("1"),momentum=Decimal("0.01"),created_at=c.open_time)
        db.add(f);db.flush()
        r=MarketRegimeSnapshot(feature_snapshot_id=f.id,exchange="binance",symbol="BTC/USDT",timeframe="1h",candle_open_time=c.open_time,regime="trending_bull",confidence_score=Decimal("0.8"),regime_version="1.0.0",configuration={},configuration_hash=(f"{i+1000:064x}"[-64:]),supporting_signals={},reason="test",previous_regime="trending_bull",current_regime="trending_bull",changed=False,transition_reason=None)
        db.add(r);rows.append((c,f,r))
    if include_future_unclosed:
        c=OHLCVCandle(exchange="binance",symbol="BTC/USDT",timeframe="1h",open_time=start+timedelta(hours=n),open=Decimal("1"),high=Decimal("9999"),low=Decimal("0.01"),close=Decimal("9999"),volume=Decimal("999999"),is_closed=False);db.add(c)
    db.commit();return rows


def low_gates(monkeypatch):
    monkeypatch.setenv("AI_VALIDATION_MIN_TRADES","1");monkeypatch.setenv("AI_VALIDATION_MIN_PROFIT_FACTOR","0");monkeypatch.setenv("AI_VALIDATION_MIN_STABILITY","0");monkeypatch.setenv("AI_VALIDATION_MIN_DATA_QUALITY","0");monkeypatch.setenv("AI_VALIDATION_MAX_OVERFIT_RISK","1");monkeypatch.setenv("AI_VALIDATION_MAX_DRAWDOWN","100000");monkeypatch.setenv("AI_VALIDATION_MAX_EXECUTION_COST_DRAG","10");monkeypatch.setenv("AI_VALIDATION_MIN_EXPECTANCY","-100000")


def test_accepted_blueprint_validates_and_nonaccepted_blocks(monkeypatch,db_session):
    low_gates(monkeypatch);seed_market(db_session);bp=seed_blueprint(db_session);r=BlueprintValidationService(db_session).validate(bp.id,BlueprintValidationRequest());assert r.status=="completed" and r.validation_version==VALIDATION_VERSION and r.sample_size==36
    other=seed_blueprint(db_session,status="review_required")
    with pytest.raises(ValueError):BlueprintValidationService(db_session).validate(other.id,BlueprintValidationRequest())


def test_rule_interpreter_all_any_and_operators(db_session):
    records=seed_market(db_session,3); li=LogicInterpreter(); cur=records[1]; prev=records[0]
    assert li.group({"all":[{"indicator":"rsi","operator":">=","value":50},{"indicator":"close","operator":"!=","value":0}],"any":[{"indicator":"volume","operator":">","value":1}]},cur,prev,{})
    assert not li.group({"all":[{"indicator":"rsi","operator":"<","value":10}],"any":[]},cur,prev,{})


def test_crosses_above_and_below(db_session):
    rec=seed_market(db_session,2); li=LogicInterpreter(); rec[0][1].ema_fast=Decimal("99");rec[0][1].ema_slow=Decimal("100");rec[1][1].ema_fast=Decimal("101");rec[1][1].ema_slow=Decimal("100");db_session.commit()
    assert li.rule({"indicator":"ema_fast","operator":"crosses_above","reference":"ema_slow"},rec[1],rec[0],{})
    rec[0][1].ema_fast=Decimal("101");rec[1][1].ema_fast=Decimal("99");db_session.commit();assert li.rule({"indicator":"ema_fast","operator":"crosses_below","reference":"ema_slow"},rec[1],rec[0],{})


def test_closed_candle_only_and_no_future_leakage(monkeypatch,db_session):
    low_gates(monkeypatch);seed_market(db_session,20,include_future_unclosed=True);bp=seed_blueprint(db_session);r=BlueprintValidationService(db_session).validate(bp.id,BlueprintValidationRequest());assert r.sample_size==20;assert len(r.configuration["data_scope"]["candle_ids"])==20


def test_next_candle_execution_and_signal_metadata(monkeypatch,db_session):
    low_gates(monkeypatch);seed_market(db_session,20);bp=seed_blueprint(db_session);svc=BlueprintValidationService(db_session);r=svc.validate(bp.id,BlueprintValidationRequest(validation_fraction=0));trades=svc.trades(r.id);assert trades
    t=trades[0];assert datetime.fromisoformat(t.context["signal_time"]) < t.entry_time; assert t.context["execution_convention"]==EXECUTION_CONVENTION


def test_intrabar_both_tp_sl_uses_stop_first(monkeypatch,db_session):
    low_gates(monkeypatch);seed_market(db_session,12,both_hit=True);bp=seed_blueprint(db_session);svc=BlueprintValidationService(db_session);r=svc.validate(bp.id,BlueprintValidationRequest(validation_fraction=0));t=svc.trades(r.id)[0];assert t.exit_reason=="stop_loss" and t.net_pnl<0


def test_fees_and_slippage_are_applied(monkeypatch,db_session):
    low_gates(monkeypatch);monkeypatch.setenv("AI_BACKTEST_FEE_BPS","10");monkeypatch.setenv("AI_BACKTEST_SLIPPAGE_BPS","5");seed_market(db_session,20);bp=seed_blueprint(db_session);svc=BlueprintValidationService(db_session);r=svc.validate(bp.id,BlueprintValidationRequest(validation_fraction=0));t=svc.trades(r.id)[0];assert t.simulated_fees>0 and t.simulated_slippage>0;assert t.net_pnl<t.gross_pnl


def test_simulated_trades_isolated_from_authoritative_ledger(monkeypatch,db_session):
    low_gates(monkeypatch);seed_market(db_session,20);bp=seed_blueprint(db_session);before=(db_session.query(DemoOrderModel).count(),db_session.query(PositionModel).count());r=BlueprintValidationService(db_session).validate(bp.id,BlueprintValidationRequest(validation_fraction=0));assert db_session.query(BlueprintSimulatedTrade).filter_by(validation_run_id=r.id).count()>0;assert (db_session.query(DemoOrderModel).count(),db_session.query(PositionModel).count())==before


def test_parameter_enumeration_hash_and_limit(monkeypatch,db_session):
    svc=BlueprintValidationService(db_session);bp=seed_blueprint(db_session,parameter_space={"rsi_threshold":{"min":30,"max":40,"step":5},"x":{"values":[1,2]}});sets=svc._parameter_sets(bp,20);assert len(sets)==6 and canonical_hash(sets[0])==canonical_hash(dict(reversed(list(sets[0].items()))))
    with pytest.raises(ValueError):svc._parameter_sets(bp,5)


def test_chronological_train_validation_no_overlap(monkeypatch,db_session):
    low_gates(monkeypatch);seed_market(db_session,40);bp=seed_blueprint(db_session);r=BlueprintValidationService(db_session).validate(bp.id,BlueprintValidationRequest(validation_fraction=.25));assert r.train_start<r.train_end<r.validation_start<=r.validation_end


def test_parameter_selection_uses_training_only(monkeypatch,db_session):
    low_gates(monkeypatch);seed_market(db_session,32);bp=seed_blueprint(db_session,parameter_space={"rsi_threshold":{"values":[35,45]}});r=BlueprintValidationService(db_session).validate(bp.id,BlueprintValidationRequest(validation_fraction=.25));assert r.parameter_results and all("training_score" in x and "train_metrics" in x for x in r.parameter_results);assert "validation_metrics" not in r.parameter_results[0]


def test_walk_forward_chronological(monkeypatch,db_session):
    low_gates(monkeypatch);seed_market(db_session,40);bp=seed_blueprint(db_session);r=BlueprintValidationService(db_session).validate(bp.id,BlueprintValidationRequest(validation_type="walk_forward_validation",validation_fraction=.25));segs=r.robustness_metrics["walk_forward_segments"];assert segs;assert all(datetime.fromisoformat(x["train_end"])<datetime.fromisoformat(x["validation_start"]) for x in segs)


def test_metrics_expectancy_profit_factor_drawdown_mae_mfe():
    t=[{"net_pnl":Decimal("10"),"gross_pnl":Decimal("12"),"return_pct":Decimal("1"),"simulated_fees":Decimal("1"),"simulated_slippage":Decimal("1"),"mae":Decimal("-2"),"mfe":Decimal("15"),"holding_time_seconds":10,"entry_regime":"x"},{"net_pnl":Decimal("-5"),"gross_pnl":Decimal("-4"),"return_pct":Decimal("-.5"),"simulated_fees":Decimal(".5"),"simulated_slippage":Decimal(".5"),"mae":Decimal("-6"),"mfe":Decimal("2"),"holding_time_seconds":20,"entry_regime":"x"}];m=BlueprintValidationService.metrics(t);assert m["expectancy"]==2.5 and m["profit_factor"]==2 and m["max_drawdown"]==5 and m["average_mae"]==-4 and m["average_mfe"]==8.5


def test_scores_are_bounded_and_parameter_sensitivity():
    svc=BlueprintValidationService(None);m=svc.metrics([]);assert 0<=svc._validation_score(m,.5,.5,.5,.2)<=1;assert 0<=svc._stability(m,m,m,.5,[])<=1;assert 0<=svc._overfit(m,m,10,2,.5,.5,m)<=1;assert 0<=svc._parameter_sensitivity([{"training_score":.8},{"training_score":.79}])<=1


def test_pass_fail_gates_explicit(monkeypatch,db_session):
    seed_market(db_session,12,both_hit=True);bp=seed_blueprint(db_session);monkeypatch.setenv("AI_VALIDATION_MIN_TRADES","100");monkeypatch.setenv("AI_VALIDATION_MIN_EXPECTANCY","1");monkeypatch.setenv("AI_VALIDATION_MIN_PROFIT_FACTOR","2");monkeypatch.setenv("AI_VALIDATION_MIN_STABILITY",".99");monkeypatch.setenv("AI_VALIDATION_MIN_DATA_QUALITY",".99");monkeypatch.setenv("AI_VALIDATION_MAX_OVERFIT_RISK",".01");r=BlueprintValidationService(db_session).validate(bp.id,BlueprintValidationRequest(validation_fraction=0));assert not r.passed;assert "minimum_simulated_trades_not_met" in r.failure_reasons and "minimum_validation_expectancy_not_met" in r.failure_reasons


def test_configuration_hash_and_idempotent_validation(monkeypatch,db_session):
    low_gates(monkeypatch);seed_market(db_session,20);bp=seed_blueprint(db_session);svc=BlueprintValidationService(db_session);a=svc.validate(bp.id,BlueprintValidationRequest());b=svc.validate(bp.id,BlueprintValidationRequest());assert a.id==b.id and len(a.configuration_hash)==64 and db_session.query(BlueprintValidationRun).count()==1


def test_retrieval_parameters_robustness_and_filters(monkeypatch,db_session):
    low_gates(monkeypatch);seed_market(db_session,20);bp=seed_blueprint(db_session);svc=BlueprintValidationService(db_session);r=svc.validate(bp.id,BlueprintValidationRequest());assert svc.get(r.id).id==r.id;assert svc.parameters(r.id)["selected_parameter_set_hash"]==r.parameter_set_hash;assert "robustness_metrics" in svc.robustness(r.id);assert [x.id for x in svc.list(blueprint=bp.id,symbol="btc/usdt",timeframe="1h")]==[r.id];assert svc.blueprint_validations(bp.id)[0].id==r.id


def test_lifecycle_observations(monkeypatch,db_session):
    low_gates(monkeypatch);seed_market(db_session,20);bp=seed_blueprint(db_session);BlueprintValidationService(db_session).validate(bp.id,BlueprintValidationRequest());events={x.event_type for x in db_session.query(ResearchObservation).all()};assert {"ai_blueprint_validation_started","ai_blueprint_validation_completed"}<=events


def test_no_trading_execution_capability():
    svc=BlueprintValidationService(None);forbidden=("submit_order","place_order","start_bot","stop_bot","bypass_risk","decrypt_credentials","approve_candidate","approve_demo","approve_live","create_candidate")
    assert all(not hasattr(svc,x) for x in forbidden);src=open("packages/research/ai/validation.py").read().lower();assert "import ccxt" not in src and "eval(" not in src and "exec(" not in src

def test_parameter_explosion_persists_sanitized_failed_run_and_event(monkeypatch,db_session):
    low_gates(monkeypatch);monkeypatch.setenv("AI_BLUEPRINT_MAX_PARAMETER_COMBINATIONS","2");seed_market(db_session,12);bp=seed_blueprint(db_session,parameter_space={"rsi_threshold":{"values":[30,35,40]}});r=BlueprintValidationService(db_session).validate(bp.id,BlueprintValidationRequest());assert r.status=="failed" and not r.passed;assert "parameter search space exceeds configured maximum" in r.failure_reasons[0];assert db_session.query(ResearchObservation).filter_by(event_type="ai_blueprint_validation_failed").count()==1


def test_future_dated_feature_snapshot_not_used(db_session):
    rec=seed_market(db_session,3);c,f,r=rec[0];f.candle_open_time=c.open_time+timedelta(days=1);db_session.commit();bp=seed_blueprint(db_session);records=BlueprintValidationService(db_session)._records(bp,BlueprintValidationRequest());assert records[0][1] is None and records[0][2] is None


def test_invalid_intrabar_policy_falls_back_to_conservative_stop_first(monkeypatch, db_session):
    low_gates(monkeypatch)
    monkeypatch.setenv("AI_BACKTEST_INTRABAR_CONFLICT_POLICY", "take_profit_first")
    seed_market(db_session, 12, both_hit=True)
    bp = seed_blueprint(db_session)
    svc = BlueprintValidationService(db_session)
    result = svc.validate(bp.id, BlueprintValidationRequest(validation_fraction=0))
    assert result.configuration["intrabar_conflict_policy"] == "stop_first"
    assert svc.trades(result.id)[0].exit_reason == "stop_loss"


def test_time_exit_uses_next_available_candle_open(monkeypatch, db_session):
    low_gates(monkeypatch)
    records = seed_market(db_session, 12)
    # Prevent TP/SL and force a one-candle holding period after the entry.
    bp = seed_blueprint(
        db_session,
        exit_logic={"take_profit_pct": 0, "stop_loss_pct": 0, "max_holding_candles": 1},
    )
    svc = BlueprintValidationService(db_session)
    result = svc.validate(bp.id, BlueprintValidationRequest(validation_fraction=0))
    trade = svc.trades(result.id)[0]
    entry_idx = next(i for i, row in enumerate(records) if row[0].open_time == trade.entry_time)
    expected_exit = records[entry_idx + 2][0]  # hold entry + one candle, then next open
    assert trade.exit_reason == "time_exit"
    assert trade.exit_time == expected_exit.open_time


def test_all_validation_gate_failure_reasons_are_explicit():
    svc = BlueprintValidationService(None)
    metrics = {"trade_count": 1, "expectancy": -1, "profit_factor": 0.5, "max_drawdown": 50}
    gates = {
        "minimum_trades": 10,
        "minimum_expectancy": 0,
        "minimum_profit_factor": 1.1,
        "maximum_drawdown": 10,
        "minimum_stability": 0.7,
        "minimum_data_quality": 0.8,
        "maximum_overfit_risk": 0.4,
        "maximum_execution_cost_drag": 0.2,
    }
    failures = set(svc._gate_failures(metrics, 0.2, 0.3, 0.9, 0.8, gates))
    assert failures == {
        "minimum_simulated_trades_not_met",
        "minimum_validation_expectancy_not_met",
        "minimum_profit_factor_not_met",
        "maximum_drawdown_exceeded",
        "minimum_stability_not_met",
        "minimum_data_quality_not_met",
        "maximum_overfit_risk_exceeded",
        "maximum_execution_cost_drag_exceeded",
    }


def test_passing_validation_does_not_create_candidate_or_demo_state(monkeypatch, db_session):
    low_gates(monkeypatch)
    seed_market(db_session, 20)
    bp = seed_blueprint(db_session)
    before_candidates = db_session.query(ResearchCandidateStrategy).count()
    result = BlueprintValidationService(db_session).validate(
        bp.id, BlueprintValidationRequest(validation_fraction=0)
    )
    assert result.status == "completed"
    assert db_session.query(ResearchCandidateStrategy).count() == before_candidates
    assert bp.status == "accepted_for_validation"
    assert not hasattr(BlueprintValidationService(db_session), "approve_demo")
