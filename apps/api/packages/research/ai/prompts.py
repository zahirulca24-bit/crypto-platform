from __future__ import annotations
import json
from typing import Any
from .schemas import PROMPT_VERSION

SYSTEM_PROMPT = """You are a research analyst for a crypto trading research platform.
You may only propose testable research ideas from the supplied persisted research context.
You cannot execute trades, submit Demo or Live orders, approve strategies, allocate capital, start bots,
override deterministic risk rules, or modify production strategy configuration.
Never claim guaranteed profit. Distinguish observed association from causality.
Every proposal requires deterministic historical validation before any candidate/governance step.
Return structured JSON only and never executable code, scripts, shell commands, or credentials."""

def build_generation_prompt(context: dict[str, Any], max_proposals: int) -> str:
    schema_hint = {
        "proposals": [{
            "proposal_type": "hypothesis_candidate", "title": "...", "summary": "...",
            "strategy_name": None, "symbol": None, "timeframe": None, "regime": None,
            "hypothesis_statement": "...", "rationale": "concise evidence summary",
            "feature_conditions": {}, "entry_conditions": {}, "exit_conditions": {}, "risk_conditions": {},
            "parameter_suggestions": {}, "supporting_evidence": {},
            "referenced_observation_ids": [], "referenced_outcome_ids": [],
            "referenced_hypothesis_ids": [], "referenced_experiment_ids": [],
            "model_confidence": 0.0, "research_priority": 0.0,
        }]
    }
    return (
        f"Prompt version: {PROMPT_VERSION}\nGenerate at most {max_proposals} candidate research proposals. "
        "Use only evidence identifiers present in context. Use cautious non-causal language.\n"
        f"Required JSON shape: {json.dumps(schema_hint, separators=(',', ':'))}\n"
        f"Research context: {json.dumps(context, sort_keys=True, separators=(',', ':'), default=str)}"
    )

STRATEGY_DISCOVERY_SYSTEM_PROMPT = """You are a crypto strategy research analyst. Produce one structured, NON-EXECUTABLE research blueprint from supplied persisted evidence only. Never provide Python, JavaScript, shell commands, function bodies, dynamic imports, or executable code. Never bypass risk/protection rules, credentials, orders, bots, Demo or Live governance. Use only supported indicators and deterministic rules that can later be replayed. Do not claim guaranteed profit. Return JSON only."""

def build_strategy_discovery_prompt(context: dict[str, Any]) -> str:
    from .schemas import ALLOWED_INDICATORS, BLUEPRINT_TYPES, STRATEGY_DISCOVERY_PROMPT_VERSION
    shape={"name":"...","description":"...","blueprint_type":"trend_following","base_strategy_name":None,"base_strategy_version":None,"symbol_scope":[],"timeframe_scope":[],"regime_scope":[],"feature_requirements":[],"indicator_requirements":["rsi","ema"],"entry_logic":{"all":[{"indicator":"rsi","operator":"<","value":35}],"any":[]},"exit_logic":{"take_profit_pct":2.0,"stop_loss_pct":1.0},"protection_logic":{"stop_loss_required":True},"risk_constraints":{"max_risk_per_trade_pct":1.0},"parameter_space":{"rsi_threshold":{"min":25,"max":40,"step":5}},"expected_behavior":{},"invalidation_conditions":{},"estimated_data_requirements":{}}
    return f"Discovery prompt version: {STRATEGY_DISCOVERY_PROMPT_VERSION}\nAllowed blueprint types: {sorted(BLUEPRINT_TYPES)}\nAllowed indicators: {sorted(ALLOWED_INDICATORS)}\nRequired JSON shape: {json.dumps(shape,separators=(',',':'))}\nResearch evidence: {json.dumps(context,sort_keys=True,separators=(',',':'),default=str)}"
