from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "apps" / "api" / "alembic" / "versions"


def _revision_graph():
    result = {}
    for path in MIGRATIONS.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        values = {}
        for node in tree.body:
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            else:
                continue
            for target in targets:
                if isinstance(target, ast.Name) and target.id in {"revision", "down_revision"}:
                    values[target.id] = ast.literal_eval(node.value)
        if values.get("revision"):
            result[values["revision"]] = (values.get("down_revision"), path)
    return result


def test_alembic_chain_has_one_head_and_phase2_repair_is_in_main_chain():
    graph = _revision_graph()
    parents = {parent for parent, _ in graph.values() if isinstance(parent, str)}
    heads = [revision for revision in graph if revision not in parents]
    assert heads == ["025_production_security_hardening"]
    chain = []
    current = heads[0]
    while current:
        chain.append(current)
        current = graph[current][0]
    chain.reverse()
    assert chain.index("004_phase2_authoritative") < chain.index("005_research_observations")
    assert chain.index("014_ai_strategy_blueprints") < chain.index("015_blueprint_validations")
    assert chain.index("018_shadow_research_handoffs") < chain.index("019_research_monitoring")


def test_compose_runs_real_api_worker_entrypoints():
    compose = (ROOT / "docker-compose.yml").read_text()
    assert 'command: ["python", "trading_worker.py"]' in compose
    assert 'command: ["python", "research_monitor_worker.py"]' in compose
    assert "services/trading-worker" not in compose
    assert "services/research-worker" not in compose


def test_live_trading_remains_disabled_by_default():
    settings = (ROOT / "apps" / "api" / "settings.py").read_text()
    compose = (ROOT / "docker-compose.yml").read_text()
    assert 'trading_mode: TradingMode = TradingMode.DISABLED' in settings
    assert 'TRADING_MODE: ${TRADING_MODE:-disabled}' in compose
    assert 'ALLOW_LIVE_TRADING: ${ALLOW_LIVE_TRADING:-false}' in compose


def test_env_example_has_blank_secret_placeholders():
    values = {}
    for raw in (ROOT / ".env.example").read_text().splitlines():
        if not raw or raw.lstrip().startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        values[key] = value
    for key in ("POSTGRES_PASSWORD", "JWT_SECRET_KEY", "DEMO_API_KEY", "DEMO_API_SECRET", "DEMO_API_PASSWORD", "CREDENTIAL_ENCRYPTION_KEY"):
        assert values.get(key) == ""


def test_strategy_research_and_frontend_do_not_import_execution_adapter_or_ccxt():
    targets = [ROOT / "apps" / "api" / "strategies.py", ROOT / "apps" / "api" / "packages" / "research", ROOT / "apps" / "web"]
    findings = []
    for target in targets:
        paths = [target] if target.is_file() else [p for p in target.rglob("*") if p.suffix in {".py", ".ts", ".tsx", ".js", ".mjs"}]
        for path in paths:
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
            if "import ccxt" in text or "execution_adapter" in text or ".create_order(" in text:
                findings.append(str(path.relative_to(ROOT)))
    assert findings == []


def test_research_monitor_has_no_trading_boundary_dependency():
    text = (ROOT / "apps" / "api" / "research_monitor_worker.py").read_text().lower()
    for forbidden in ("ccxt", "executiongateway", "execution_gateway", "demoorderengine", "create_order", "submit_order"):
        assert forbidden not in text
