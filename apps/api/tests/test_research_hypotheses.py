from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4
import inspect
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from database import Base
from models import MarketFeatureSnapshot, ResearchHypothesis, ResearchObservation, TradeOutcome
from packages.research.hypotheses import (
    HYPOTHESIS_VERSION, HypothesisGenerateRequest, ResearchHypothesisService,
    canonical_hash, confidence_score, priority_score,
)

@pytest.fixture
def hdb(tmp_path):
    engine=create_engine(f"sqlite:///{tmp_path/'hypotheses.db'}")
    Base.metadata.create_all(engine); S=sessionmaker(bind=engine); db=S()
    try: yield db
    finally: db.close(); engine.dispose()

def seed(hdb):
    base=datetime(2026,9,1,tzinfo=timezone.utc)
    rows=[]
    for i in range(12):
        symbol='BTC/USDT' if i<8 else 'ETH/USDT'
        regime='trending_bull' if i<6 else ('ranging' if i<10 else 'high_volatility')
        strategy='alpha' if i<9 else 'beta'
        rsi=Decimal('60') if i%2==0 else Decimal('40')
        fid=uuid4()
        f=MarketFeatureSnapshot(id=fid,candle_id=uuid4(),exchange='demo',symbol=symbol,timeframe='1h',candle_open_time=base+timedelta(hours=i),feature_version='1.0.0',configuration={},configuration_hash=f'{i+1:064x}',rsi=rsi)
        hdb.add(f)
        positive = regime=='trending_bull' or (rsi>=50 and i%3!=0)
        net=Decimal('12') if positive else Decimal('-8')
        gross=net+Decimal('2')
        row=TradeOutcome(source_position_id=uuid4(),exchange='demo',symbol=symbol,timeframe='1h',strategy_name=strategy,strategy_version='1.0',strategy_config_hash='a'*64,side='long',entry_time=base+timedelta(hours=i),exit_time=base+timedelta(hours=i,minutes=30),entry_price=Decimal('100'),exit_price=Decimal('101'),quantity=Decimal('1'),notional=Decimal('100'),gross_pnl=gross,net_pnl=net,fees=Decimal('1'),slippage=Decimal('1'),holding_time_seconds=Decimal('1800'),exit_reason='stop_loss' if net<0 else 'take_profit',mae=Decimal('3'),mfe=Decimal('5'),return_pct=net,risk_amount=Decimal('10'),r_multiple=net/Decimal('10'),regime_at_entry=regime,entry_feature_snapshot_id=fid,outcome_version='1.0.0',context={})
        hdb.add(row); rows.append(row)
    hdb.commit(); return rows

def generate(hdb, types=None, minimum=3):
    seed(hdb); return ResearchHypothesisService(hdb).generate(HypothesisGenerateRequest(minimum_sample=minimum,hypothesis_types=types))

def test_regime_performance_hypothesis_generation(hdb):
    r=generate(hdb,['regime_performance']); assert len(r)==1 and r[0].hypothesis_type=='regime_performance' and r[0].evidence_summary['baseline']

def test_symbol_performance_hypothesis(hdb):
    r=generate(hdb,['symbol_performance']); assert r and r[0].symbol in {'BTC/USDT','ETH/USDT'}

def test_feature_condition_hypothesis(hdb):
    r=generate(hdb,['feature_condition']); assert r[0].feature_conditions=={'rsi_gte':'50'}

def test_exit_behavior_hypothesis(hdb):
    r=generate(hdb,['exit_behavior']); assert r[0].exit_conditions['exit_reason']=='stop_loss'

def test_execution_quality_hypothesis(hdb):
    r=generate(hdb,['execution_quality']); assert Decimal(r[0].evidence_summary['cost_drag'])>0

def test_parameter_candidate_structure(hdb):
    r=generate(hdb,['parameter_candidate']); assert r[0].hypothesis_type=='parameter_candidate' and r[0].entry_conditions['rsi_gte']=='50'

def test_sample_size_threshold_behavior(hdb):
    r=generate(hdb,['regime_performance'],minimum=100)[0]; assert r.evidence_summary['evidence_status']=='insufficient' and r.confidence_score<Decimal('0.7')

def test_deterministic_confidence_score():
    a=confidence_score(10,5,Decimal('.5'),Decimal('.4'),Decimal('1')); b=confidence_score(10,5,Decimal('.5'),Decimal('.4'),Decimal('1')); assert a==b and 0<=a<=1

def test_deterministic_priority_score():
    a=priority_score(Decimal('.5'),Decimal('.7'),10,5,Decimal('.4'),Decimal('.8')); b=priority_score(Decimal('.5'),Decimal('.7'),10,5,Decimal('.4'),Decimal('.8')); assert a==b and 0<=a<=1

def test_evidence_baseline_preservation(hdb):
    r=generate(hdb,['regime_performance'])[0]; assert 'supporting_metrics' in r.evidence_summary and 'baseline' in r.evidence_summary and r.evidence_summary['causality_claimed'] is False

def test_hypothesis_deduplication_idempotency(hdb):
    seed(hdb); svc=ResearchHypothesisService(hdb); req=HypothesisGenerateRequest(minimum_sample=3,hypothesis_types=['regime_performance']); a=svc.generate(req); b=svc.generate(req); assert a[0].id==b[0].id and hdb.scalar(select(func.count()).select_from(ResearchHypothesis))==1

def test_retrieval_filtering(hdb):
    rows=generate(hdb,['regime_performance','execution_quality']); svc=ResearchHypothesisService(hdb); got=svc.list(hypothesis_type='execution_quality',min_confidence=Decimal('0')); assert len(got)==1 and svc.get(rows[0].id)

def test_status_transition(hdb):
    row=generate(hdb,['execution_quality'])[0]; changed=ResearchHypothesisService(hdb).set_status(row.id,'queued'); assert changed.status=='queued'

def test_research_observation_linkage(hdb):
    row=generate(hdb,['execution_quality'])[0]; obs=hdb.get(ResearchObservation,row.observation_event_id); assert obs.event_type=='hypothesis_proposed' and obs.context['hypothesis_id']==str(row.id)

def test_status_observation(hdb):
    row=generate(hdb,['execution_quality'])[0]; changed=ResearchHypothesisService(hdb).set_status(row.id,'testing'); obs=hdb.get(ResearchObservation,changed.observation_event_id); assert obs.event_type=='hypothesis_status_changed' and obs.context['status']=='testing'

def test_canonical_hash_order_independent():
    assert canonical_hash({'a':1,'b':2})==canonical_hash({'b':2,'a':1})

def test_engine_cannot_execute_trading_actions():
    forbidden={'place_order','submit_order','execute_order','approve_risk','open_position','close_position','decrypt_credentials','start_bot','promote_strategy','update_strategy_config'}
    assert set(dir(ResearchHypothesisService)).isdisjoint(forbidden)
    import packages.research.hypotheses as m
    src=inspect.getsource(m); assert 'ccxt' not in src and 'OpenAI' not in src and 'Gemini' not in src and 'packages.exchange.adapter' not in src

def test_engine_cannot_promote_strategy_directly():
    src=inspect.getsource(ResearchHypothesisService); assert 'StrategyConfig' not in src and 'BotRuntime' not in src

def test_hypothesis_version(): assert HYPOTHESIS_VERSION=='1.0.0'
