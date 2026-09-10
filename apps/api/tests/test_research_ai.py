from __future__ import annotations
import json, os, uuid
from datetime import datetime, timezone
from decimal import Decimal
import httpx
import pytest
from pydantic import ValidationError
from models import AIResearchProposal, ResearchHypothesis, ResearchObservation, PositionModel, TradeOutcome
from packages.research.ai.gemini_provider import GeminiResearchProvider, AIProviderError, AIProviderResponseError
from packages.research.ai.provider import ResearchAIProvider
from packages.research.ai.safety import sanitize_context, validate_condition_safety
from packages.research.ai.schemas import GenerateProposalsRequest, ProposalBatch, StructuredProposal, PROPOSAL_VERSION, PROMPT_VERSION
from packages.research.ai.service import AIResearchService, ResearchContextBuilder, canonical_hash
from packages.research.models import ObservationCreate
from packages.research.service import ResearchObservationService

class FakeProvider:
    provider_name = "fake_research"
    model_name = "fake-1"
    configured = True
    temperature = 0.1
    max_output_tokens = 512
    def __init__(self, proposal=None): self.proposal=proposal or make_proposal(); self.calls=0
    def health_check(self): return {"configured":True,"provider":self.provider_name,"model":self.model_name}
    def generate_research_proposals(self, *, context, prompt, max_proposals):
        self.calls += 1
        return ProposalBatch(proposals=[self.proposal]), {"usage_metadata":{"promptTokenCount":10},"secret":"drop-me"}
    def analyze_research_context(self, *, context, prompt): return {"ok":True}

def make_proposal(**updates):
    data=dict(proposal_type="hypothesis_candidate",title="Test a trend filter",summary="Candidate research association requiring validation.",
        strategy_name="momentum",symbol="BTC/USDT",timeframe="1h",regime="trending_bull",
        hypothesis_statement="Observed trend context may be associated with improved outcomes and requires replay validation.",
        rationale="This is an observed association from bounded persisted research context, not a causal claim.",
        feature_conditions={"rsi_gte":50},entry_conditions={"regime":"trending_bull"},exit_conditions={},risk_conditions={},
        parameter_suggestions={"rsi_threshold":50},supporting_evidence={"requires_validation":True},
        referenced_observation_ids=[],referenced_outcome_ids=[],referenced_hypothesis_ids=[],referenced_experiment_ids=[],
        model_confidence=.62,research_priority=.7)
    data.update(updates); return StructuredProposal(**data)

def test_provider_protocol_surface():
    p=FakeProvider(); assert isinstance(p.provider_name,str); assert callable(p.generate_research_proposals); assert callable(p.health_check)

def test_gemini_configuration_loading(monkeypatch):
    monkeypatch.setenv("GOOGLE_AI_API_KEY","test-key"); monkeypatch.setenv("GOOGLE_AI_MODEL","gemini-test")
    p=GeminiResearchProvider(); assert p.configured is True; assert p.model_name=="gemini-test"

def test_invalid_gemini_configuration_is_safely_reported(monkeypatch, db_session):
    monkeypatch.setenv("GOOGLE_AI_API_KEY","x"); monkeypatch.setenv("GOOGLE_AI_TEMPERATURE","not-a-number")
    provider=GeminiResearchProvider(); health=AIResearchService(db_session,provider).health()
    assert health.configured is False
    with pytest.raises(AIProviderError,match="configuration is invalid"):
        provider.generate_research_proposals(context={},prompt="x",max_proposals=1)

def test_missing_api_key_health(monkeypatch, db_session):
    monkeypatch.delenv("GOOGLE_AI_API_KEY",raising=False); s=AIResearchService(db_session, GeminiResearchProvider(api_key=""))
    h=s.health(); assert h.configured is False; assert h.proposal_version==PROPOSAL_VERSION; assert h.prompt_version==PROMPT_VERSION
    with pytest.raises(Exception, match="not configured"): s.generate(GenerateProposalsRequest())

def test_ai_health_never_exposes_secret(monkeypatch, db_session):
    p=GeminiResearchProvider(api_key="super-secret-key",model_name="gemini-test"); h=AIResearchService(db_session,p).health().model_dump()
    assert "super-secret-key" not in json.dumps(h); assert "api_key" not in h

def test_structured_proposal_validation_and_scores():
    p=make_proposal(); assert p.proposal_type=="hypothesis_candidate"; assert 0 <= p.model_confidence <= 1
    with pytest.raises(ValidationError): make_proposal(model_confidence=1.2)

def test_unsupported_proposal_type_rejected():
    with pytest.raises(ValidationError): make_proposal(proposal_type="approved_for_live")

def test_executable_condition_fields_rejected():
    with pytest.raises(ValueError,match="executable/code"): validate_condition_safety({"script":"rm -rf /"})

def test_gemini_malformed_model_response_rejected():
    def handler(request): return httpx.Response(200,json={"candidates":[{"content":{"parts":[{"text":"not-json"}]}}]})
    p=GeminiResearchProvider(api_key="x",model_name="test",transport=httpx.MockTransport(handler))
    with pytest.raises(AIProviderResponseError): p.generate_research_proposals(context={},prompt="x",max_proposals=1)

def test_gemini_unsupported_type_rejected():
    body={"proposals":[make_proposal().model_dump(mode="json") ]}; body["proposals"][0]["proposal_type"]="approved_for_live"
    def handler(request): return httpx.Response(200,json={"candidates":[{"content":{"parts":[{"text":json.dumps(body)}]}}]})
    p=GeminiResearchProvider(api_key="x",model_name="test",transport=httpx.MockTransport(handler))
    with pytest.raises(AIProviderResponseError): p.generate_research_proposals(context={},prompt="x",max_proposals=1)

def test_gemini_timeout_is_sanitized_failure():
    def handler(request): raise httpx.ReadTimeout("timed out",request=request)
    p=GeminiResearchProvider(api_key="x",model_name="test",transport=httpx.MockTransport(handler))
    with pytest.raises(AIProviderError,match="timed out|unavailable") as exc: p.generate_research_proposals(context={},prompt="x",max_proposals=1)
    assert "x" not in str(exc.value)

def test_secret_filtering_recursive():
    result=sanitize_context({"symbol":"BTC/USDT","api_key":"abc","nested":{"password":"p","safe":1},"jwt_secret":"x"})
    assert result=={"symbol":"BTC/USDT","nested":{"safe":1}}
    assert sanitize_context({"note":"api_key=abc123"})["note"]=="[REDACTED]"

def test_bounded_context_builder(db_session):
    svc=ResearchObservationService(db_session)
    for i in range(8): svc.record(ObservationCreate(event_type="test",source="unit",symbol="BTC/USDT",context={"n":i,"api_secret":"never"}))
    context=ResearchContextBuilder(db_session).build(GenerateProposalsRequest(context_limit=5,symbol="BTC/USDT"))
    assert len(context["observations"])==5; assert "api_secret" not in json.dumps(context)

def test_proposal_persistence_hash_and_deduplication(db_session):
    p=FakeProvider(); s=AIResearchService(db_session,p); req=GenerateProposalsRequest()
    a=s.generate(req)[0]; b=s.generate(req)[0]
    assert a.id==b.id; assert len(a.configuration_hash)==64; assert p.calls==2
    assert db_session.query(AIResearchProposal).count()==1

def test_evidence_reference_scope_and_observation_event(db_session):
    obs=ResearchObservationService(db_session).record(ObservationCreate(event_type="trade_outcome",source="unit",symbol="BTC/USDT"))
    proposal=make_proposal(referenced_observation_ids=[obs.event_id])
    row=AIResearchService(db_session,FakeProvider(proposal)).generate(GenerateProposalsRequest(symbol="BTC/USDT"))[0]
    assert str(obs.event_id) in row.referenced_observation_ids
    lifecycle=db_session.query(ResearchObservation).filter(ResearchObservation.event_type=="ai_proposal_generated").one()
    assert lifecycle.context["proposal_id"]==str(row.id)


def test_outcome_evidence_reference_is_preserved(db_session):
    now=datetime.now(timezone.utc); pid=uuid.uuid4()
    db_session.add(PositionModel(id=pid,symbol="BTC/USDT",status="closed",position_json={},opened_at=now,updated_at=now)); db_session.commit()
    out=TradeOutcome(source_position_id=pid,exchange="binance",symbol="BTC/USDT",timeframe="1h",bot_id=None,strategy_name="momentum",strategy_version="1",strategy_config_hash="a"*64,side="long",entry_time=now,exit_time=now,entry_price=Decimal("100"),exit_price=Decimal("101"),quantity=Decimal("1"),notional=Decimal("100"),gross_pnl=Decimal("1"),net_pnl=Decimal("0.9"),fees=Decimal("0.1"),slippage=Decimal("0"),holding_time_seconds=Decimal("60"),exit_reason="strategy_exit",tp_price=None,sl_price=None,mae=Decimal("-0.2"),mfe=Decimal("1.2"),return_pct=Decimal("0.9"),risk_amount=None,r_multiple=None,regime_at_entry="trending_bull",regime_at_exit="trending_bull",outcome_version="1.0.0",context={})
    db_session.add(out); db_session.commit(); db_session.refresh(out)
    proposal=make_proposal(referenced_outcome_ids=[out.id])
    row=AIResearchService(db_session,FakeProvider(proposal)).generate(GenerateProposalsRequest(symbol="BTC/USDT"))[0]
    assert str(out.id) in row.referenced_outcome_ids
    assert str(out.id) in row.data_scope["reference_ids"]["outcomes"]

def test_reference_outside_context_is_rejected(db_session):
    proposal=make_proposal(referenced_observation_ids=[uuid.uuid4()])
    with pytest.raises(ValueError,match="outside the bounded data scope"):
        AIResearchService(db_session,FakeProvider(proposal)).generate(GenerateProposalsRequest())

def test_proposal_status_workflow_and_observation(db_session):
    s=AIResearchService(db_session,FakeProvider()); row=s.generate(GenerateProposalsRequest())[0]
    changed=s.set_status(row.id,"accepted_for_research"); assert changed.status=="accepted_for_research"
    assert db_session.query(ResearchObservation).filter(ResearchObservation.event_type=="ai_proposal_status_changed").count()==1
    with pytest.raises(ValueError): s.set_status(row.id,"approved_for_demo")

def test_explicit_proposal_to_hypothesis_conversion_preserves_provenance(db_session):
    s=AIResearchService(db_session,FakeProvider()); p=s.generate(GenerateProposalsRequest())[0]
    with pytest.raises(ValueError): s.create_hypothesis(p.id)
    s.set_status(p.id,"accepted_for_research"); h=s.create_hypothesis(p.id)
    assert isinstance(h,ResearchHypothesis); assert h.status=="proposed"; assert h.confidence_score==0
    assert h.configuration["ai_proposal_id"]==str(p.id); assert h.evidence_summary["requires_validation"] is True
    reread=s.get(p.id); assert reread.status=="converted"; assert reread.converted_hypothesis_id==h.id
    assert s.create_hypothesis(p.id).id==h.id

def test_conversion_lifecycle_observation(db_session):
    s=AIResearchService(db_session,FakeProvider()); p=s.generate(GenerateProposalsRequest())[0]; s.set_status(p.id,"accepted_for_research"); h=s.create_hypothesis(p.id)
    obs=db_session.query(ResearchObservation).filter(ResearchObservation.event_type=="ai_proposal_converted_to_hypothesis").one()
    assert obs.context["hypothesis_id"]==str(h.id)

def test_proposal_retrieval_filtering(db_session):
    s=AIResearchService(db_session,FakeProvider()); row=s.generate(GenerateProposalsRequest())[0]
    assert s.get(row.id).id==row.id
    assert [x.id for x in s.list(provider="fake_research",symbol="btc/usdt",status="generated")]==[row.id]
    assert s.list(provider="other")==[]

def test_canonical_hash_is_deterministic():
    assert canonical_hash({"b":2,"a":1})==canonical_hash({"a":1,"b":2})

def test_ai_service_has_no_execution_or_promotion_capabilities(db_session):
    s=AIResearchService(db_session,FakeProvider())
    forbidden=("submit_order","place_order","create_demo_trade","approve_candidate","approve_live","start_bot","stop_bot","decrypt_credentials","bypass_risk","create_candidate")
    assert all(not hasattr(s,name) for name in forbidden)

def test_prompt_does_not_store_or_request_chain_of_thought(db_session):
    row=AIResearchService(db_session,FakeProvider()).generate(GenerateProposalsRequest())[0]
    blob=json.dumps(row.model_dump(mode="json")).lower()
    assert "chain-of-thought" not in blob and "private reasoning" not in blob

def test_versions():
    assert PROPOSAL_VERSION=="1.0.0"; assert PROMPT_VERSION=="1.0.0"
