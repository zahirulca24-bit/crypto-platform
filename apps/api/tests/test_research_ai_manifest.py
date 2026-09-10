import inspect
import pytest
from decimal import Decimal
from sqlalchemy import select

from models import DemoRuntimeRelease, DemoStrategyManifest, ResearchObservation, ResearchTriggerEvent, ResearchMonitoringPolicy, StrategyRuntimeCompatibilityCheck
from packages.research.ai.manifest import DemoManifestService, CompileRequest, MANIFEST_VERSION, COMPATIBILITY_CHECK_VERSION, RELEASE_VERSION
from packages.research.ai.shadow import ShadowResearchService, HandoffCreateRequest
from packages.research.ai.validation import BlueprintValidationService, BlueprintValidationRequest
from packages.research.candidates import ResearchCandidateService, PromotionEvaluateRequest
from test_research_ai_shadow import source


def approved_source(monkeypatch,db):
    bp,val=source(monkeypatch,db,40)
    ss=ShadowResearchService(db);h=ss.create_handoff(HandoffCreateRequest(source_type='blueprint',validation_id=val.id));c=ss.create_candidate(h.id)
    cs=ResearchCandidateService(db)
    ev=cs.evaluate(c.id,PromotionEvaluateRequest(minimum_historical_sample=1,minimum_expectancy=Decimal('0'),minimum_profit_factor=Decimal('0'),maximum_drawdown=Decimal('999999999'),minimum_stability=Decimal('0'),minimum_data_quality=Decimal('0'),maximum_execution_cost_ratio=Decimal('999999999'),maximum_regime_concentration=Decimal('1')))
    assert ev.overall_passed
    cs.request_review(c.id);c=cs.approve_demo(c.id)
    return bp,val,h,c,ev


def test_unapproved_candidate_cannot_compile(monkeypatch,db_session):
    bp,val=source(monkeypatch,db_session);ss=ShadowResearchService(db_session);h=ss.create_handoff(HandoffCreateRequest(source_type='blueprint',validation_id=val.id));c=ss.create_candidate(h.id)
    with pytest.raises(ValueError):DemoManifestService(db_session).compile(CompileRequest(candidate_id=c.id))


def test_approved_candidate_compiles_with_lineage_and_idempotency(monkeypatch,db_session):
    bp,val,h,c,ev=approved_source(monkeypatch,db_session);svc=DemoManifestService(db_session);a=svc.compile(CompileRequest(candidate_id=c.id));b=svc.compile(CompileRequest(candidate_id=c.id))
    assert a.id==b.id and a.manifest_version==MANIFEST_VERSION and a.handoff_id==h.id and a.source_blueprint_id==bp.id and a.source_validation_id==val.id
    assert a.entry_logic==h.strategy_definition['entry_logic'] and a.parameter_values==h.parameter_values and len(a.configuration_hash)==64


def test_manifest_has_no_secret_fields(monkeypatch,db_session):
    *_,c,ev=approved_source(monkeypatch,db_session);m=DemoManifestService(db_session).compile(CompileRequest(candidate_id=c.id));blob=str(m.model_dump()).lower()
    assert 'api_key' not in blob and 'password' not in blob and 'credential' not in blob


def test_compatibility_passes_supported_contract(monkeypatch,db_session):
    *_,c,ev=approved_source(monkeypatch,db_session);svc=DemoManifestService(db_session);m=svc.compile(CompileRequest(candidate_id=c.id));chk=svc.check_compatibility(m.id)
    assert chk.check_version==COMPATIBILITY_CHECK_VERSION and chk.status=='passed' and chk.strategy_protocol_compatible and chk.protection_compatible and chk.risk_boundary_compatible
    assert float(chk.overall_score)>=.8


def test_unsupported_indicator_future_code_and_risk_relaxation_fail(monkeypatch,db_session):
    *_,c,ev=approved_source(monkeypatch,db_session);svc=DemoManifestService(db_session);m=svc.compile(CompileRequest(candidate_id=c.id));row=db_session.get(DemoStrategyManifest,m.id)
    row.indicator_requirements=['imaginary_indicator'];row.entry_logic={'all':[{'indicator':'rsi','operator':'>','value':'future next candle eval(x)'}]};row.risk_constraints={'max_risk':'disable risk limits'};db_session.commit()
    chk=svc.check_compatibility(m.id);assert chk.status=='failed';assert {'indicator_compatible','risk_boundary_compatible','deterministic_logic_compatible'}<=set(chk.blocking_reasons)


def test_runtime_contract_safe_and_orderproposal_boundary(monkeypatch,db_session):
    *_,c,ev=approved_source(monkeypatch,db_session);svc=DemoManifestService(db_session);m=svc.compile(CompileRequest(candidate_id=c.id));svc.check_compatibility(m.id);p=svc.runtime_contract(m.id);blob=str(p).lower()
    assert p['strategy_protocol_config']['contract']=='StrategyOrderProposal' and p['risk_engine_final_authority'] is True and p['execution_authority'] is False
    assert p['capital_allocation'] is None and p['bot_start_command'] is None and 'api_key' not in blob and 'encrypted' not in blob


def test_explicit_review_release_idempotent_and_no_activation(monkeypatch,db_session):
    *_,c,ev=approved_source(monkeypatch,db_session);svc=DemoManifestService(db_session);m=svc.compile(CompileRequest(candidate_id=c.id));svc.check_compatibility(m.id);review=svc.request_review(m.id);assert review.status=='review_required';r1=svc.release(m.id);r2=svc.release(m.id)
    assert r1.id==r2.id and r1.release_version==RELEASE_VERSION and r1.status=='ready';assert svc.manifest(m.id).status=='ready_for_demo_runtime';assert r1.safety_snapshot['starts_bot'] is False and r1.safety_snapshot['submits_order'] is False


def test_failed_compatibility_cannot_release(monkeypatch,db_session):
    *_,c,ev=approved_source(monkeypatch,db_session);svc=DemoManifestService(db_session);m=svc.compile(CompileRequest(candidate_id=c.id));row=db_session.get(DemoStrategyManifest,m.id);row.protection_logic={};db_session.commit();chk=svc.check_compatibility(m.id);assert chk.status=='failed'
    with pytest.raises(ValueError):svc.request_review(m.id)


def test_severe_monitoring_trigger_blocks_release(monkeypatch,db_session):
    *_,c,ev=approved_source(monkeypatch,db_session);svc=DemoManifestService(db_session);m=svc.compile(CompileRequest(candidate_id=c.id));svc.check_compatibility(m.id);svc.request_review(m.id)
    pol=ResearchMonitoringPolicy(name='candidate',policy_version='1.0.0',status='enabled',scope_type='candidate',symbol_scope=[],timeframe_scope=[],regime_scope=[],strategy_scope=[],candidate_id=c.id,trigger_rules={},thresholds={},minimum_sample_size=1,cooldown_seconds=1,configuration={},configuration_hash='1'*64);db_session.add(pol);db_session.flush()
    from datetime import datetime,timezone
    tr=ResearchTriggerEvent(policy_id=pol.id,trigger_type='candidate_staleness',status='detected',trigger_version='1.0.0',detected_at=datetime.now(timezone.utc),baseline_metrics={},current_metrics={},difference_metrics={},severity_score=Decimal('.95'),confidence_score=Decimal('.9'),evidence_scope={},trigger_reasons=[],warnings=[],configuration={},configuration_hash='2'*64);db_session.add(tr);db_session.commit()
    ready=svc.readiness(m.id);assert 'unresolved_severe_monitoring_trigger' in ready['blocking_reasons']
    with pytest.raises(ValueError):svc.release(m.id)


def test_revoke_only_metadata(monkeypatch,db_session):
    *_,c,ev=approved_source(monkeypatch,db_session);svc=DemoManifestService(db_session);m=svc.compile(CompileRequest(candidate_id=c.id));svc.check_compatibility(m.id);svc.request_review(m.id);r=svc.release(m.id);out=svc.revoke(m.id)
    assert out.status=='revoked';rr=db_session.get(DemoRuntimeRelease,r.id);assert rr.status=='revoked' and rr.revoked_at is not None


def test_observation_events(monkeypatch,db_session):
    *_,c,ev=approved_source(monkeypatch,db_session);svc=DemoManifestService(db_session);m=svc.compile(CompileRequest(candidate_id=c.id));svc.check_compatibility(m.id);svc.request_review(m.id);svc.release(m.id);svc.revoke(m.id);events={r.event_type for r in db_session.query(ResearchObservation)}
    assert {'ai_demo_manifest_compiled','ai_demo_manifest_compatibility_checked','ai_demo_manifest_review_requested','ai_demo_manifest_ready','ai_demo_runtime_release_created','ai_demo_runtime_release_revoked'}<=events


def test_source_safety_has_no_execution_dependencies():
    import packages.research.ai.manifest as mod
    src=inspect.getsource(mod).lower()
    for forbidden in ('import ccxt','create_order','submit_order','start_bot','stop_bot','decrypt_credentials','packages.exchange','packages.execution'):
        assert forbidden not in src
    import ast
    tree=ast.parse(inspect.getsource(mod)); calls=[n.func.id for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)]
    assert 'eval' not in calls and 'exec' not in calls


def test_router_api_inventory():
    from routers.research import router
    paths={(r.path,','.join(sorted(r.methods or []))) for r in router.routes}
    required=['/v1/research/ai/demo-manifests/compile','/v1/research/ai/demo-manifests','/v1/research/ai/demo-manifests/{manifest_id}','/v1/research/ai/demo-manifests/{manifest_id}/lineage','/v1/research/ai/demo-manifests/{manifest_id}/check-compatibility','/v1/research/ai/demo-manifests/{manifest_id}/compatibility','/v1/research/ai/demo-manifests/{manifest_id}/readiness','/v1/research/ai/demo-manifests/{manifest_id}/runtime-contract','/v1/research/ai/demo-manifests/{manifest_id}/request-review','/v1/research/ai/demo-manifests/{manifest_id}/release','/v1/research/ai/demo-manifests/{manifest_id}/revoke','/v1/research/ai/demo-releases','/v1/research/ai/demo-releases/{release_id}']
    assert all(any(p==x for p,_ in paths) for x in required)
