from __future__ import annotations
from datetime import datetime
from typing import Any, Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PROPOSAL_VERSION = "1.0.0"
PROMPT_VERSION = "1.0.0"
PROPOSAL_TYPES = {
    "hypothesis_candidate", "strategy_filter_candidate", "feature_combination_candidate",
    "parameter_candidate", "regime_candidate", "exit_improvement_candidate",
    "risk_research_candidate", "execution_quality_candidate",
}
PROPOSAL_STATUSES = {"generated", "review_required", "accepted_for_research", "rejected", "converted", "archived"}

class StructuredProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal_type: str
    title: str = Field(min_length=3, max_length=255)
    summary: str = Field(min_length=3, max_length=2000)
    strategy_name: str | None = Field(default=None, max_length=64)
    symbol: str | None = Field(default=None, max_length=64)
    timeframe: str | None = Field(default=None, max_length=16)
    regime: str | None = Field(default=None, max_length=32)
    hypothesis_statement: str = Field(min_length=3, max_length=4000)
    rationale: str = Field(min_length=3, max_length=4000)
    feature_conditions: dict[str, Any] = Field(default_factory=dict)
    entry_conditions: dict[str, Any] = Field(default_factory=dict)
    exit_conditions: dict[str, Any] = Field(default_factory=dict)
    risk_conditions: dict[str, Any] = Field(default_factory=dict)
    parameter_suggestions: dict[str, Any] = Field(default_factory=dict)
    supporting_evidence: dict[str, Any] = Field(default_factory=dict)
    referenced_observation_ids: list[UUID] = Field(default_factory=list, max_length=100)
    referenced_outcome_ids: list[UUID] = Field(default_factory=list, max_length=100)
    referenced_hypothesis_ids: list[UUID] = Field(default_factory=list, max_length=100)
    referenced_experiment_ids: list[UUID] = Field(default_factory=list, max_length=100)
    model_confidence: float | None = Field(default=None, ge=0, le=1)
    research_priority: float | None = Field(default=None, ge=0, le=1)

    @field_validator("proposal_type")
    @classmethod
    def valid_type(cls, value: str) -> str:
        if value not in PROPOSAL_TYPES:
            raise ValueError("unsupported proposal type")
        return value

    @field_validator("symbol")
    @classmethod
    def valid_symbol(cls, value: str | None) -> str | None:
        if value is None: return value
        value = value.strip().upper()
        if not value or len(value) > 64 or any(c.isspace() for c in value):
            raise ValueError("invalid symbol")
        return value

    @field_validator("timeframe")
    @classmethod
    def valid_timeframe(cls, value: str | None) -> str | None:
        if value is None: return value
        value = value.strip()
        if not value or not all(ch.isalnum() or ch in "_-" for ch in value):
            raise ValueError("invalid timeframe")
        return value

class ProposalBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposals: list[StructuredProposal] = Field(min_length=1, max_length=8)

class GenerateProposalsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    strategy: str | None = None
    symbol: str | None = None
    timeframe: str | None = None
    regime: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    max_proposals: int = Field(default=3, ge=1, le=8)
    context_limit: int = Field(default=25, ge=5, le=100)

class ProposalStatusPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str

class ProposalRead(BaseModel):
    id: UUID; provider: str; model_name: str; prompt_version: str
    proposal_type: str; title: str; summary: str
    strategy_name: str | None; symbol: str | None; timeframe: str | None; regime: str | None
    hypothesis_statement: str; rationale: str
    feature_conditions: dict[str, Any]; entry_conditions: dict[str, Any]; exit_conditions: dict[str, Any]; risk_conditions: dict[str, Any]
    parameter_suggestions: dict[str, Any]; supporting_evidence: dict[str, Any]
    referenced_observation_ids: list[Any]; referenced_outcome_ids: list[Any]; referenced_hypothesis_ids: list[Any]; referenced_experiment_ids: list[Any]
    data_scope: dict[str, Any]; model_confidence: float | None; research_priority: float | None
    raw_model_metadata: dict[str, Any]; status: str; proposal_version: str
    configuration: dict[str, Any]; configuration_hash: str; converted_hypothesis_id: UUID | None
    created_at: datetime; updated_at: datetime

class AIHealth(BaseModel):
    configured: bool
    provider: str
    configured_model: str
    proposal_version: str
    prompt_version: str
    research_only: bool = True

ORCHESTRATOR_VERSION = "1.0.0"
REVIEW_VERSION = "1.0.0"
RUN_TYPES = {"broad_scan","strategy_review","regime_review","symbol_review","performance_review","loss_review","execution_quality_review","parameter_discovery"}
RUN_STATUSES = {"queued","running","completed","failed","cancelled"}

class ResearchRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_type: str = "broad_scan"
    symbol: str | None = None
    timeframe: str | None = None
    regime: str | None = None
    strategy: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    recent_outcome_count: int = Field(default=50, ge=1, le=500)
    minimum_sample_size: int = Field(default=10, ge=1, le=10000)
    max_proposals: int | None = Field(default=None, ge=1, le=20)
    @field_validator("run_type")
    @classmethod
    def valid_run_type(cls,v):
        if v not in RUN_TYPES: raise ValueError("unsupported run type")
        return v
    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls,v): return v.strip().upper() if v else v

class AIResearchRunRead(BaseModel):
    id: UUID; run_type: str; status: str; provider: str; model_name: str; prompt_version: str; orchestrator_version: str
    symbol_scope: list[Any]; timeframe_scope: list[Any]; regime_scope: list[Any]; strategy_scope: list[Any]
    data_start: datetime | None; data_end: datetime | None; context_summary: dict[str,Any]; evidence_scope: dict[str,Any]
    proposals_requested: int; proposals_generated: int; proposals_accepted: int; proposals_suppressed: int; proposals_rejected: int
    run_metrics: dict[str,Any]; warnings: list[Any]; failure_reason: str | None; configuration: dict[str,Any]; configuration_hash: str
    started_at: datetime; completed_at: datetime | None; created_at: datetime

class AIProposalReviewRead(BaseModel):
    id: UUID; proposal_id: UUID; research_run_id: UUID; review_version: str
    evidence_score: float; novelty_score: float; testability_score: float; data_quality_score: float; safety_score: float; overall_score: float
    accepted_for_review: bool; suppressed: bool; rejection_reasons: list[Any]; warnings: list[Any]; review_metrics: dict[str,Any]
    configuration: dict[str,Any]; configuration_hash: str; created_at: datetime

BLUEPRINT_VERSION = "1.0.0"
STRATEGY_DISCOVERY_PROMPT_VERSION = "1.0.0"
BLUEPRINT_TYPES = {"trend_following","mean_reversion","breakout","momentum","regime_filtered","volatility_adaptive","multi_signal","exit_optimization","risk_adjusted_variant","execution_aware_variant"}
BLUEPRINT_STATUSES = {"draft","review_required","accepted_for_validation","rejected","archived"}
ALLOWED_INDICATORS = {"sma","ema","rsi","macd","macd_signal","macd_histogram","atr","volatility","momentum","roc","volume","spread","rolling_high_distance","rolling_low_distance","regime","selection_score","price","close"}
ALLOWED_OPERATORS = {"<","<=",">",">=","==","!=","crosses_above","crosses_below"}

class StrategyRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    indicator: str
    operator: str
    value: float | int | str | None = None
    reference: str | None = None
    lookback: int | None = Field(default=None, ge=1, le=500)
    confirmation: int | None = Field(default=None, ge=1, le=20)
    @field_validator("indicator")
    @classmethod
    def indicator_ok(cls,v):
        v=v.lower().strip()
        if v not in ALLOWED_INDICATORS: raise ValueError("unsupported indicator")
        return v
    @field_validator("operator")
    @classmethod
    def operator_ok(cls,v):
        if v not in ALLOWED_OPERATORS: raise ValueError("unsupported operator")
        return v
    @field_validator("reference")
    @classmethod
    def reference_ok(cls,v):
        if v is None:return v
        v=v.lower().strip()
        if v not in ALLOWED_INDICATORS: raise ValueError("unsupported reference")
        return v

class LogicGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    all: list[StrategyRule] = Field(default_factory=list, max_length=30)
    any: list[StrategyRule] = Field(default_factory=list, max_length=30)

class ParameterRange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    min: float | int | None = None
    max: float | int | None = None
    step: float | int | None = None
    values: list[float|int|str] | None = Field(default=None, max_length=50)
    @model_validator(mode="after")
    def bounds_ok(self):
        import math
        nums=[x for x in (self.min,self.max,self.step) if x is not None]
        if any(not math.isfinite(float(x)) for x in nums): raise ValueError("parameter bounds must be finite")
        if self.values is not None and any(isinstance(x,(int,float)) and not math.isfinite(float(x)) for x in self.values): raise ValueError("parameter values must be finite")
        if self.min is not None and self.max is not None and float(self.min)>float(self.max): raise ValueError("parameter min exceeds max")
        if self.step is not None and float(self.step)<=0: raise ValueError("parameter step must be positive")
        if self.values is None and any(x is not None for x in (self.min,self.max,self.step)) and not all(x is not None for x in (self.min,self.max,self.step)): raise ValueError("range requires min, max, and step")
        return self

class StructuredStrategyBlueprint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=3,max_length=255)
    description: str = Field(min_length=3,max_length=3000)
    blueprint_type: str
    base_strategy_name: str | None = Field(default=None,max_length=64)
    base_strategy_version: str | None = Field(default=None,max_length=32)
    symbol_scope: list[str] = Field(default_factory=list,max_length=20)
    timeframe_scope: list[str] = Field(default_factory=list,max_length=20)
    regime_scope: list[str] = Field(default_factory=list,max_length=20)
    feature_requirements: list[str] = Field(default_factory=list,max_length=50)
    indicator_requirements: list[str] = Field(default_factory=list,max_length=50)
    entry_logic: LogicGroup
    exit_logic: dict[str,Any] = Field(default_factory=dict)
    protection_logic: dict[str,Any] = Field(default_factory=dict)
    risk_constraints: dict[str,Any] = Field(default_factory=dict)
    parameter_space: dict[str,ParameterRange] = Field(default_factory=dict)
    expected_behavior: dict[str,Any] = Field(default_factory=dict)
    invalidation_conditions: dict[str,Any] = Field(default_factory=dict)
    estimated_data_requirements: dict[str,Any] = Field(default_factory=dict)
    @field_validator("blueprint_type")
    @classmethod
    def type_ok(cls,v):
        if v not in BLUEPRINT_TYPES: raise ValueError("unsupported blueprint type")
        return v
    @field_validator("indicator_requirements")
    @classmethod
    def indicators_ok(cls,v):
        vals=[x.lower().strip() for x in v]
        bad=[x for x in vals if x not in ALLOWED_INDICATORS]
        if bad: raise ValueError(f"unsupported indicator: {bad[0]}")
        return vals
    @field_validator("timeframe_scope")
    @classmethod
    def timeframes_ok(cls,v):
        for x in v:
            if not x or not all(ch.isalnum() or ch in "_-" for ch in x): raise ValueError("invalid timeframe")
        return v

class BlueprintGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_ai_proposal_id: UUID | None = None
    source_hypothesis_id: UUID | None = None
    source_experiment_id: UUID | None = None
    parent_blueprint_id: UUID | None = None

class BlueprintRead(BaseModel):
    id:UUID; name:str; description:str; blueprint_type:str; status:str
    source_ai_proposal_id:UUID|None; source_review_id:UUID|None; source_hypothesis_id:UUID|None; source_experiment_id:UUID|None
    base_strategy_name:str|None; base_strategy_version:str|None
    symbol_scope:list[Any]; timeframe_scope:list[Any]; regime_scope:list[Any]
    feature_requirements:list[Any]; indicator_requirements:list[Any]
    entry_logic:dict[str,Any]; exit_logic:dict[str,Any]; protection_logic:dict[str,Any]; risk_constraints:dict[str,Any]; parameter_space:dict[str,Any]
    expected_behavior:dict[str,Any]; invalidation_conditions:dict[str,Any]; evidence_summary:dict[str,Any]; evidence_scope:dict[str,Any]
    estimated_complexity:str; estimated_data_requirements:dict[str,Any]; readiness_score:float; warnings:list[Any]; blocking_reasons:list[Any]
    provider:str; model_name:str; prompt_version:str; blueprint_version:str; configuration:dict[str,Any]; configuration_hash:str
    parent_blueprint_id:UUID|None; research_observation_id:UUID|None; created_at:datetime; updated_at:datetime
