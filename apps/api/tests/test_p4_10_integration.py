from __future__ import annotations
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from database import Base
import models  # noqa: F401
from packages.research.integration import EXPECTED_MIGRATION_HEAD, ResearchIntegrationService
from packages.research.ai.service import AIResearchService
from packages.research.ai.monitoring import ResearchMonitoringService

ROOT = Path(__file__).resolve().parents[3]
API = ROOT / "apps" / "api"
VERSIONS = API / "alembic" / "versions"
PHASE2 = {
    "strategy_decisions", "risk_decisions", "demo_orders", "positions", "applied_order_fills",
    "position_protections", "bot_runtime_state", "bot_commands", "bot_journal",
}
REQUIRED = PHASE2 | {
    "research_observations", "market_feature_snapshots", "market_regime_snapshots", "trade_outcomes",
    "research_hypotheses", "research_experiments", "research_candidate_strategies", "candidate_promotion_evaluations",
    "ai_research_proposals", "ai_research_runs", "ai_proposal_reviews", "ai_strategy_blueprints",
    "blueprint_validation_runs", "blueprint_simulated_trades", "ai_strategy_evolution_runs", "ai_strategy_variants",
    "champion_challenger_comparisons", "strategy_regime_profiles", "research_strategy_portfolios",
    "shadow_research_sessions", "shadow_research_trades", "research_candidate_handoffs",
    "research_monitoring_policies", "research_trigger_events", "adaptive_research_jobs", "research_monitor_worker_status",
    "demo_strategy_manifests", "strategy_runtime_compatibility_checks", "demo_runtime_releases",
}

def test_single_alembic_head_and_repaired_graph():
    out = subprocess.check_output([sys.executable, "-m", "alembic", "heads"], cwd=API, env={**os.environ, "PYTHONPATH": str(API)}, text=True)
    assert out.strip() == f"{EXPECTED_MIGRATION_HEAD} (head)"
    m5 = (VERSIONS / "005_create_research_observations.py").read_text()
    m8 = (VERSIONS / "008_create_trade_outcomes.py").read_text()
    m4 = (VERSIONS / "004a_create_phase2_authoritative_schema.py").read_text()
    assert "004_phase2_authoritative" in m5
    assert '"positions"' in m4
    assert 'ForeignKey("positions.id"' in m8

def test_phase2_orm_tables_have_canonical_migration_columns():
    historical = (VERSIONS / "004a_create_phase2_authoritative_schema.py").read_text()
    for table in PHASE2:
        assert f'"{table}"' in historical
        orm = Base.metadata.tables[table]
        for column in orm.columns:
            assert f'"{column.name}"' in historical

def test_forward_compatibility_revision_is_non_destructive():
    source = (VERSIONS / "021_phase2_schema_compatibility.py").read_text()
    assert 'down_revision = "020_demo_strategy_manifests"' in source
    assert "if not _exists" in source
    assert "DROP TABLE" not in source.upper()

def test_empty_database_research_and_monitoring_states(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path/'empty.db'}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        overview = ResearchIntegrationService(db).overview()
        pipeline = ResearchIntegrationService(db).pipeline_status()
        monitor = ResearchMonitoringService(db).monitor_status()
        assert overview["counts"]["observations"] == 0
        assert pipeline["counts"]["candidates"] == 0
        assert monitor["enabled_policy_count"] == 0
    finally:
        db.close()

def test_phase4_integration_health_is_execution_free(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path/'health.db'}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine); db = Session()
    try:
        result = ResearchIntegrationService(db).phase4_integration_health()
        assert result["database_connected"] is True
        assert result["expected_migration_head"] == EXPECTED_MIGRATION_HEAD
        assert result["postgresql_authoritative"] is True
        assert result["trading_execution_authority"] is False
        assert all(result["modules"].values())
    finally: db.close()

def test_gemini_not_configured_health(monkeypatch, tmp_path):
    monkeypatch.delenv("GOOGLE_AI_API_KEY", raising=False)
    engine = create_engine(f"sqlite:///{tmp_path/'ai.db'}"); Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    try:
        health = AIResearchService(db).health()
        assert health.configured is False
        assert not hasattr(health, "api_key")
    finally: db.close()

def test_monitor_worker_is_separate_from_fastapi():
    worker = ROOT / "services" / "research-monitor-worker" / "main.py"
    main = (API / "main.py").read_text()
    source = worker.read_text()
    assert worker.exists() and "while True" in source
    assert "research-monitor-worker" not in main
    assert "while True" not in main

def test_frontend_public_env_has_no_backend_secrets():
    web_text = "\n".join(p.read_text(errors="ignore") for p in (ROOT / "apps" / "web").rglob("*") if p.is_file() and p.suffix in {".ts", ".tsx", ".js", ".jsx"})
    assert "NEXT_PUBLIC_API_BASE_URL" in web_text
    for secret in ("GOOGLE_AI_API_KEY", "DATABASE_URL", "JWT_SECRET", "EXCHANGE_API_SECRET"):
        assert f"NEXT_PUBLIC_{secret}" not in web_text

def test_p4_modules_have_no_execution_authority():
    ai = API / "packages" / "research" / "ai"
    text_all = "\n".join(p.read_text() for p in ai.glob("*.py"))
    for forbidden in ("import ccxt", ".create_order(", "decrypt_exchange"):
        assert forbidden not in text_all
    # Dynamic execution calls are prohibited; references in safety strings are fine.
    import ast
    for path in ai.glob("*.py"):
        tree = ast.parse(path.read_text())
        calls = {n.func.id for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        assert not ({"eval", "exec"} & calls)


def test_fake_provider_end_to_end_proposal_review(tmp_path):
    from packages.research.ai.orchestrator import AIResearchOrchestrator
    from packages.research.ai.schemas import ProposalBatch, ResearchRunRequest, StructuredProposal
    class FakeProvider:
        provider_name = "p4_10_fake"; model_name = "fake-model"; configured = True
        def __init__(self): self.calls = 0
        def generate_research_proposals(self, **kwargs):
            self.calls += 1
            proposal = StructuredProposal(
                proposal_type="hypothesis_candidate", title="bounded research smoke",
                summary="Research-only deterministic validation suggestion",
                hypothesis_statement="Persisted evidence should be deterministically tested before any governance step",
                rationale="P4-10 bounded fake-provider smoke", feature_conditions={"rsi":{"lte":55}},
                entry_conditions={"regime":"ranging"}, exit_conditions={"type":"strategy_exit"},
                risk_conditions={"max_risk_pct":1}, parameter_suggestions={"rsi_max":55},
                supporting_evidence={"fixture":True}, referenced_observation_ids=[], referenced_outcome_ids=[],
                referenced_hypothesis_ids=[], referenced_experiment_ids=[], model_confidence=0.5, research_priority=0.5,
            )
            return ProposalBatch(proposals=[proposal]), {"fixture": True}
        def analyze_research_context(self, **kwargs): return {}
        def health_check(self): return {"configured": True, "provider": self.provider_name, "model": self.model_name}
    engine = create_engine(f"sqlite:///{tmp_path/'e2e.db'}"); Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)(); provider = FakeProvider()
    try:
        svc = AIResearchOrchestrator(db, provider); run = svc.run(ResearchRunRequest(max_proposals=1))
        proposals = svc.run_proposals(run.id)
        assert run.status == "completed" and provider.calls == 1 and len(proposals) == 1
        assert svc.get_review(proposals[0].id) is not None
    finally: db.close()

def test_phase4_integration_health_route_registered():
    source = (API / "routers" / "research.py").read_text()
    assert "@router.get('/ai/integration-health')" in source

def test_fresh_postgres_upgrade_when_configured():
    url = os.getenv("P4_FRESH_POSTGRES_URL", "").strip()
    if not url:
        pytest.skip("P4_FRESH_POSTGRES_URL not configured")
    parsed = make_url(url)
    if not parsed.drivername.startswith("postgresql") or "test" not in (parsed.database or "").lower():
        pytest.skip("dedicated PostgreSQL test URL required")
    engine = create_engine(url, pool_pre_ping=True)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE")); conn.execute(text("CREATE SCHEMA public"))
    env = {**os.environ, "DATABASE_URL": url, "PYTHONPATH": str(API)}
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=API, env=env, check=True)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == EXPECTED_MIGRATION_HEAD
        assert not (REQUIRED - set(inspect(conn).get_table_names()))
