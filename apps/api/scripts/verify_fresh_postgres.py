"""Destructive integration verifier for a dedicated fresh PostgreSQL test database.

Requires P4_FRESH_POSTGRES_URL whose database name contains ``test``. The script
resets only that database's public schema, runs Alembic from zero to head, and
asserts the canonical table inventory. It never stamps Alembic state.
"""
from __future__ import annotations
import os, subprocess, sys
from pathlib import Path
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

EXPECTED_HEAD = "021_phase2_schema_compatibility"
REQUIRED_TABLES = {
    "users", "ohlcv_candles", "symbol_selection_runs", "symbol_selection_results",
    "strategy_decisions", "risk_decisions", "demo_orders", "positions",
    "applied_order_fills", "position_protections", "bot_runtime_state", "bot_commands", "bot_journal",
    "research_observations", "market_feature_snapshots", "market_regime_snapshots", "trade_outcomes",
    "research_hypotheses", "research_experiments", "research_candidate_strategies", "candidate_promotion_evaluations",
    "ai_research_proposals", "ai_research_runs", "ai_proposal_reviews", "ai_strategy_blueprints",
    "blueprint_validation_runs", "blueprint_simulated_trades", "ai_strategy_evolution_runs", "ai_strategy_variants",
    "champion_challenger_comparisons", "strategy_regime_profiles", "research_strategy_portfolios",
    "shadow_research_sessions", "shadow_research_trades", "research_candidate_handoffs",
    "research_monitoring_policies", "research_trigger_events", "adaptive_research_jobs", "research_monitor_worker_status",
    "demo_strategy_manifests", "strategy_runtime_compatibility_checks", "demo_runtime_releases",
}

def main() -> int:
    url = os.getenv("P4_FRESH_POSTGRES_URL", "").strip()
    if not url:
        print("SKIP: P4_FRESH_POSTGRES_URL is not configured")
        return 2
    parsed = make_url(url)
    if not parsed.drivername.startswith("postgresql"):
        raise SystemExit("P4_FRESH_POSTGRES_URL must be PostgreSQL")
    dbname = (parsed.database or "").lower()
    if "test" not in dbname:
        raise SystemExit("Refusing destructive reset: dedicated database name must contain 'test'")
    api_dir = Path(__file__).resolve().parents[1]
    engine = create_engine(url, pool_pre_ping=True)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    env = os.environ.copy(); env["DATABASE_URL"] = url
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=api_dir, env=env, check=True)
    with engine.connect() as conn:
        actual = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        tables = set(inspect(conn).get_table_names())
    missing = sorted(REQUIRED_TABLES - tables)
    if actual != EXPECTED_HEAD:
        raise SystemExit(f"unexpected migration head: {actual}")
    if missing:
        raise SystemExit("missing required tables: " + ", ".join(missing))
    print(f"PASS: fresh PostgreSQL upgraded from zero to {actual}; {len(REQUIRED_TABLES)} required tables verified")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
