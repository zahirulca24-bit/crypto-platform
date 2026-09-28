# Adaptive Crypto Trading Platform

Adaptive Crypto Trading Platform — Local Development Environment.

## Project Status

- **Current Date:** 09 Sep 2026
- **Current Phase:** Phase 4 — Adaptive AI Research & Strategy Discovery
- **Current Progress:** Phase 4 (10/10) — COMPLETE
- **Phase Status:** Phase 4 CODE COMPLETE; runtime verification remains environment-dependent (fresh PostgreSQL/Docker unavailable in the build agent)

---

## Windows Launcher & Auto Update

The Windows launcher is a thin orchestration/updater utility. It reuses the existing `docker-compose.yml`; the API and frontend are already containerized, so it does not start duplicate host-side FastAPI or Next.js processes. The launcher/updater does **not** change trading safety rules and does **not** activate Live trading.

### Quick startup

- `start.bat` is the no-build fallback. Run it from Explorer or a Command Prompt in the project root. It checks Docker, runs `docker compose up -d`, waits for the API and frontend, then opens the frontend URL. Existing Compose containers are reused rather than duplicated.
- `CryptoPlatform.exe` is the preferred packaged launcher. Place/run `dist\CryptoPlatform.exe` inside this project tree; it discovers the project root by locating `VERSION` and `docker-compose.yml`.
- `build-launcher.bat` creates `dist\CryptoPlatform.exe` with PyInstaller on Windows. It uses a local `.launcher-build-venv` and packages only the launcher/updater code—not the application, database, Docker images, or secrets.

### Launcher configuration

Copy `launcher-config.example.json` to `launcher-config.json` only when overrides are needed. The local config is ignored by Git and is preserved by updates. Supported settings are `frontend_url`, `backend_health_url`, `docker_compose_file`, `update_manifest_url`, `update_check_enabled`, `startup_timeout_seconds`, and `http_timeout_seconds`. Equivalent environment overrides include `CRYPTO_PLATFORM_UPDATE_MANIFEST_URL`, `CRYPTO_PLATFORM_FRONTEND_URL`, `CRYPTO_PLATFORM_BACKEND_HEALTH_URL`, and `CRYPTO_PLATFORM_ROOT`.

The canonical application version is stored once in the root `VERSION` file. The initial post-Phase-3 version is `0.3.0`.

### Auto-update flow

When update checking is enabled and a manifest URL is configured, the launcher reads the local `VERSION`, downloads the HTTPS JSON manifest, validates it, compares `X.Y.Z` versions, and—when a newer release is accepted—downloads an update ZIP to a temporary directory. The ZIP is installed only after its SHA-256 exactly matches the manifest. A successful source update causes Compose startup to use `--build` so changed application images are rebuilt before readiness checks.

The manifest format is:

```json
{
  "version": "0.3.1",
  "download_url": "https://example.invalid/crypto-platform-v0.3.1.zip",
  "sha256": "64-lower-or-upper-case-hex-characters",
  "release_notes": "Optional release notes",
  "mandatory": false
}
```

No production update URL is hard-coded. If `update_manifest_url` / `CRYPTO_PLATFORM_UPDATE_MANIFEST_URL` is empty, the launcher reports that update checking is not configured and continues startup normally. Update manifest and package URLs must use HTTPS.

Security controls include strict manifest field/type validation, request timeouts, partial-download cleanup, SHA-256 verification, ZIP traversal/ZIP-slip rejection, symlink rejection, expected-project-layout validation, and a local `.launcher-backups` rollback copy of overwritten files. The updater copies project files directly; it does not run installer scripts downloaded from the release package.

The updater does not overwrite `.env`, `.env.local`/other real `.env*` files, `launcher-config.json`, common credential/private-key file names, or project-local data/volume directories. It never runs `docker compose down -v`, so PostgreSQL/Redis named volumes remain untouched. `.env.example` remains distributable.

### GitHub Releases compatibility

For a public GitHub repository, publish the complete project release ZIP as a Release asset and publish a small JSON manifest at a stable HTTPS URL (for example a version-controlled raw file or release asset). Set its `download_url` to the public GitHub Release asset URL and calculate the asset SHA-256 on the exact ZIP bytes. Then configure `CRYPTO_PLATFORM_UPDATE_MANIFEST_URL` or `launcher-config.json`. Public releases require no GitHub authentication. `tools/windows-launcher/update-manifest.example.json` is a template only and intentionally contains no real repository URL or digest.

### Troubleshooting

If startup fails, the launcher reports the exact component: Docker/Compose, PostgreSQL, Redis, API, or frontend. Use `docker compose ps` and `docker compose logs --tail=100` for container diagnostics. A missing update URL is not an error. If an update fails hash/manifest/ZIP validation, it is rejected and startup continues on the currently installed version.

A genuine Windows `CryptoPlatform.exe` must be built on Windows because PyInstaller does not cross-compile Windows executables from Linux. If launcher source changes in a release, rebuild/replace the EXE on Windows as part of release packaging; application project updates themselves remain versioned by `VERSION`.


## Architecture Overview

```text
crypto-platform/
├── apps/
│   ├── web/                # Next.js frontend
│   └── api/                # FastAPI backend (stateless API)
├── services/
│   ├── trading-worker/     # Execution & bot runtime worker (placeholder)
│   ├── supervisor/         # System monitor & supervisor (placeholder)
│   ├── research-worker/    # Background R&D & learning worker (placeholder)
│   └── research-monitor-worker/ # P4-08 supervised adaptive research monitor
├── packages/
│   ├── strategies/         # Strategy definitions & signals
│   ├── risk/               # Risk management & checks
│   ├── exchange/           # Exchange connectivity & adapters
│   └── shared/             # Shared schemas, constants, and utilities
├── tests/                  # Test suites
├── infra/                  # Infrastructure configurations
├── docs/                   # Documentation & specifications
├── .env.example            # Environment template
├── .gitignore              # Git ignore rules
├── docker-compose.yml      # Local Docker Compose development stack
└── README.md               # Getting started guide
```

---


## P4-10 Final Integration / Runtime Verification

**Date:** 09 Sep 2026  
**Phase:** Phase 4 — Adaptive AI Research & Strategy Discovery  
**Progress:** Phase 4 (10/10) — COMPLETE (code complete)

P4-10 closes the Phase-4 code/integration gate while reporting runtime verification separately. The historical fresh-database defect was real: migration `008_trade_outcomes` references `positions.id`, but the original canonical Alembic path did not create the Phase-2 `positions` table before migration 008. The repaired chain inserts `004_phase2_authoritative` after `004_sym_selection` and before `005_research_observations`. It creates the actual Phase-2 persistence schema used by the ORM/runtime: `strategy_decisions`, `risk_decisions`, `demo_orders`, `positions`, `applied_order_fills`, `position_protections`, `bot_runtime_state`, `bot_commands`, and `bot_journal`.

For backward compatibility, forward revision `021_phase2_schema_compatibility` follows `020_demo_strategy_manifests`. Existing installations already at later historical revisions are not stamped or rewritten; the forward guard creates only genuinely missing Phase-2 tables. The repository now has one head: `021_phase2_schema_compatibility`. `apps/api/scripts/verify_fresh_postgres.py` provides a destructive zero-to-head verifier for an explicitly supplied **dedicated test PostgreSQL database** through `P4_FRESH_POSTGRES_URL`; it refuses non-PostgreSQL URLs and database names that do not contain `test`. It never uses `alembic stamp`.

**Runtime verification in this agent:** Docker, `psql`, `pg_isready`, and a local PostgreSQL server were unavailable. Therefore fresh PostgreSQL bootstrap, full Docker stack health, live API-against-PostgreSQL checks, and monitor-worker heartbeat runtime checks were **NOT RUN — ENVIRONMENT UNAVAILABLE**. This is not reported as a pass. Static Alembic graph verification, ORM/migration audit, unit/integration regressions, Python compilation, YAML validation, worker/FastAPI architecture checks, and research safety scans were run.

The Phase-2 UUID persistence layer was also corrected to bind UUID-typed ORM keys as UUID values rather than stringifying them. Phase-2 UUID columns use SQLAlchemy's portable `Uuid(as_uuid=True)` ORM type, which remains native UUID on PostgreSQL while avoiding SQLite test-harness affinity corruption. PostgreSQL migration definitions remain authoritative. Relevant Phase-2 regression tests pass without changing risk/order/position/protection semantics.

A read-only `GET /v1/research/ai/integration-health` endpoint reports Phase-4 module availability, database connectivity, expected/actual Alembic head when available, required-table inventory, `postgresql_authoritative=true`, and `trading_execution_authority=false`. It exposes no secrets and performs no exchange actions.

Gemini behavior is fail-open for deterministic research but fail-closed for AI generation: without `GOOGLE_AI_API_KEY`, API startup remains valid and AI health reports `configured=false`. No key existed in this agent, so **Real Gemini Smoke: NOT_CONFIGURED**. A bounded fake-provider end-to-end smoke verified research context → structured proposal → deterministic review.

Frontend remains `apps/web` and continues to use only `NEXT_PUBLIC_API_BASE_URL` for public backend configuration. Backend CORS uses comma-separated `CORS_ALLOW_ORIGINS` (for example `http://localhost:3000,https://your-app.vercel.app`) rather than wildcard CORS. Backend Gemini/database/JWT/exchange secrets must never be exposed as `NEXT_PUBLIC_*`. Dependency installation for a fresh frontend build timed out in this agent, so a new production frontend build was not claimed.

The supervised `research-monitor-worker` remains a separate Compose/Render worker; FastAPI contains no persistent monitoring loop. `start.bat` and the Windows launcher still run the complete Compose topology with `docker compose up -d`, so the added worker remains included without launcher-specific service duplication.

**Safety boundary:** Phase-4 research artifacts, `ready_for_demo_runtime`, and `DemoRuntimeRelease(status=ready)` do not start a bot, submit an order, create a position, decrypt credentials, allocate capital, or bypass risk. Every future Demo order proposal must still follow closed candle → strategy logic → `StrategyOrderProposal` → **Phase-2 Risk Engine** → Order Engine.

## Changelog

### 09 Sep 2026 — P4-10 — Final Integration + Fresh PostgreSQL Bootstrap Repair + Runtime Verification

- Repaired the canonical Alembic graph so real Phase-2 persistence precedes Phase-3 foreign-key consumers; added non-destructive forward compatibility revision `021_phase2_schema_compatibility`.
- Added dedicated PostgreSQL zero→head verification script/test, required-table inventory, ORM/migration audit, integration-health endpoint, empty-state checks, Gemini not-configured/fake-provider smoke, worker boundary checks, frontend-public-secret audit, and Phase-4 execution-authority source scan.
- Relevant Phase-2 regression: **46/46 passed**. Complete research regression including P4-10: **328 passed, 1 PostgreSQL integration test skipped because PostgreSQL was unavailable** (see current verification output).
- Fresh PostgreSQL/Docker runtime could not be executed in this agent because Docker/PostgreSQL tooling was unavailable; runtime status is explicitly not claimed as verified.
- Phase 4 is **CODE COMPLETE**. Runtime verification requires a genuine fresh PostgreSQL/Docker environment.



### 09 Sep 2026 — P4-04 — Deterministic Blueprint Backtesting + Validation Engine

- Added a PostgreSQL-backed, research-only blueprint validation layer: `BlueprintValidationRun` and `BlueprintSimulatedTrade` remain separate from authoritative orders, fills, positions, and `TradeOutcome`.
- `AIStrategyBlueprint` must be `accepted_for_validation` before validation can start. Validation never creates candidates, approves Demo, activates bots, or submits orders.
- The safe JSON rule interpreter supports `all`/`any`, `<`, `<=`, `>`, `>=`, `==`, `!=`, `crosses_above`, and `crosses_below` without `eval`, `exec`, generated code, dynamic imports, CCXT, or exchange access.
- Historical processing uses persisted **closed candles only**. A signal confirmed on candle T executes at the **next available candle open**. Feature/regime data dated after the candle is ignored to prevent look-ahead leakage.
- TP/SL simulation uses conservative intrabar handling. If both are touched and ordering is unknowable, the default `AI_BACKTEST_INTRABAR_CONFLICT_POLICY=stop_first` assumes the adverse stop-loss outcome first.
- Backtests include configurable Decimal-based fees/slippage and use normalized fixed-notional research sizing; real account balances are never read for simulation sizing.
- Bounded blueprint parameter spaces are enumerated deterministically up to `AI_BLUEPRINT_MAX_PARAMETER_COMBINATIONS`. Parameter selection uses training data only; later chronological validation data is not used for selection.
- Chronological train/validation splitting enforces `train_end < validation_start`. Walk-forward mode advances through ordered train→unseen-validation windows without random shuffling.
- Metrics include signals/trades, wins/losses, win rate, gross/net PnL, expectancy, profit factor, drawdown, MAE/MFE, holding time, costs, return distribution, regime performance, and train-vs-validation results.
- Added deterministic validation, stability, data-quality, parameter-sensitivity, and overfit-risk scores. Overfit risk is an engineering heuristic, **not mathematical proof of overfitting**.
- Configurable pass/fail gates cover minimum trades/expectancy/profit factor/stability/data quality and maximum drawdown/overfit risk/execution-cost drag. Effective assumptions and thresholds are persisted with the exact candle/feature/regime IDs and canonical SHA-256 configuration/parameter hashes.
- Added APIs: `POST /v1/research/ai/blueprints/{id}/validate`, `GET /v1/research/ai/validations`, validation detail/trades/parameters/robustness reads, and blueprint validation history.
- Lifecycle observations: `ai_blueprint_validation_started`, `ai_blueprint_validation_completed`, and sanitized `ai_blueprint_validation_failed`.
- P4-04 tests: **25/25 passed**. Complete combined research regression: **235/235 passed**.
- Known limitation: simulation currently uses deterministic OHLC candle assumptions rather than tick/order-book reconstruction. Local Docker/PostgreSQL runtime verification remains required.

**Safety boundary:** Blueprint backtests are research simulations only. They do not create real/demo orders, positions, candidates, or trading activation.

### 09 Sep 2026 — P4-03 — AI Strategy Discovery Engine + Strategy Blueprint Generation

- Added persisted `AIStrategyBlueprint` with `blueprint_version = "1.0.0"` and `strategy_discovery_prompt_version = "1.0.0"` via Alembic migration `014_ai_strategy_blueprints`; PostgreSQL remains authoritative and prior migrations are preserved.
- Blueprint lifecycle is research-only: `draft` → `review_required` → `accepted_for_validation`, with `rejected` and `archived` states. No `active`, `enabled`, `approved_for_demo`, or `approved_for_live` blueprint status exists.
- Supported blueprint types: `trend_following`, `mean_reversion`, `breakout`, `momentum`, `regime_filtered`, `volatility_adaptive`, `multi_signal`, `exit_optimization`, `risk_adjusted_variant`, and `execution_aware_variant`.
- Strategy discovery accepts persisted reviewed/accepted AI proposals, deterministic `ResearchHypothesis` records, and completed `ResearchExperiment` evidence only. It does not accept arbitrary free-form strategy text as a discovery source, and exact source IDs/evidence scope are persisted.
- Blueprint logic is structured JSON only. Entry rules validate an explicit allowlist (`SMA`, `EMA`, `RSI`, `MACD`, MACD signal/histogram, `ATR`, volatility, momentum/ROC, volume, spread, rolling high/low distance, regime, selection score, price/close), supported comparison/cross operators, bounded lookbacks/confirmations, and no future/look-ahead references.
- Executable Python/JavaScript/shell-like payloads, dynamic-import/eval/exec concepts, future-candle logic, credential/order/Live activation requests, and attempts to disable mandatory risk/protection are critical blockers. Unsupported indicators/operators are rejected by strict Pydantic validation rather than silently treated as executable capabilities.
- Parameter spaces use structured finite `min/max/step` or discrete values, validate ordering/positive steps, and calculate an exact deterministic combination estimate. `AI_BLUEPRINT_MAX_PARAMETER_COMBINATIONS` and `AI_BLUEPRINT_MAX_CONDITIONS` cap research search-space/condition complexity to reduce overfitting/combinatorial risk.
- Deterministic complexity classification (`low`, `medium`, `high`, `excessive`) considers indicators, conditions, parameters, parameter combinations, regime dependencies, and exit-rule complexity. Excessive complexity is blocked/warned.
- Deterministic readiness score `0..1` combines persisted evidence quality, testability, data availability, and bounded complexity. `AI_BLUEPRINT_MIN_READINESS_SCORE` controls explicit `accept-for-validation`; the score is not an ML probability.
- Exact duplicate blueprints are idempotent using canonical SHA-256 hashing across blueprint/prompt versions, source evidence scope, structured entry/exit/protection/risk logic, parameter space, symbol/timeframe/regime scope, and parent lineage.
- Added APIs: `POST /v1/research/ai/blueprints/generate`, `GET /v1/research/ai/blueprints`, `GET /v1/research/ai/blueprints/{id}`, `GET /v1/research/ai/blueprints/{id}/readiness`, `POST /v1/research/ai/blueprints/{id}/request-review`, `POST /v1/research/ai/blueprints/{id}/accept-for-validation`, and `POST /v1/research/ai/blueprints/{id}/reject`.
- Lifecycle observations: `ai_strategy_blueprint_generated`, `ai_strategy_blueprint_review_requested`, `ai_strategy_blueprint_accepted_for_validation`, and `ai_strategy_blueprint_rejected`, storing safe blueprint/source/readiness metadata only.
- `accepted_for_validation` only changes research metadata. It does not create an experiment/candidate automatically, generate strategy code, start a bot, place an order, bypass Phase-2 Risk Engine, modify production strategy configuration, or activate Demo/Live trading.
- P4-03 tests: **17/17 passed**. P4-02 regression: **15/15 passed**. P4-01 regression: **25/25 passed**. Complete Phase-3 regression: **153/153 passed**. Combined research regression: **210/210 passed**.
- **AIStrategyBlueprint is non-executable research metadata. It cannot place orders, activate bots, bypass risk, or enable Demo/Live trading.** Later deterministic validation remains mandatory before any candidate/governance stage.
- **Known issues:** real Gemini/provider and Docker/PostgreSQL integration were not exercised in the sandbox; discovery uses a single structured provider call and still requires local/runtime validation with configured Google AI credentials.

### 09 Sep 2026 — P4-02 — AI Research Cycle Orchestrator + Proposal Review & Ranking

- Added persisted `AIResearchRun` (`orchestrator_version = "1.0.0"`) and `AIProposalReview` (`review_version = "1.0.0"`) with Alembic migration `013_ai_research_runs_reviews`; PostgreSQL remains authoritative and the P4-01 migration chain is preserved.
- Supported run types: `broad_scan`, `strategy_review`, `regime_review`, `symbol_review`, `performance_review`, `loss_review`, `execution_quality_review`, and `parameter_discovery`. Run states are research-only: `queued`, `running`, `completed`, `failed`, `cancelled`.
- The orchestrator reuses the P4-01 `ResearchAIProvider`, Gemini provider, bounded context builder, safety filtering, and structured proposal schemas. Each run performs at most **one primary provider call** and caps generated proposals using `AI_RESEARCH_MAX_PROPOSALS_PER_RUN` (default `5`). No recursive agent loop exists.
- Each run persists exact bounded evidence IDs, requested symbol/timeframe/regime/strategy/date scope, effective thresholds, context counts, provider/model/prompt versions, run metrics, warnings, and sanitized failure state. The full database is never dumped into a model request.
- Added deterministic proposal review scoring from `0..1` for evidence, novelty, testability, data quality, and safety plus a deterministic overall ranking score. Provider `model_confidence` is retained only as metadata and is explicitly non-authoritative. Novelty uses normalized deterministic structure/signatures against existing AI proposals and deterministic hypotheses; no vector DB or embeddings were introduced.
- Suppression blocks materially duplicate, invalid-scope, critically unsafe, severely under-evidenced, or non-testable proposals from research review while preserving the original AI proposal. Critical safety detection covers Risk Engine bypass, credential/withdrawal access, direct order execution, auto Demo/Live activation, dynamic generated-code execution, production strategy-config mutation, and stop-loss removal intended only to inflate win rate.
- Configurable deterministic thresholds: `AI_REVIEW_MIN_EVIDENCE_SCORE`, `AI_REVIEW_MIN_TESTABILITY_SCORE`, `AI_REVIEW_MIN_DATA_QUALITY_SCORE`, `AI_REVIEW_MIN_OVERALL_SCORE`, and `AI_RESEARCH_MAX_PROPOSALS_PER_RUN`. Effective values are persisted in review/run configuration hashes for reproducibility.
- Explicit `request-review` is required after a proposal passes deterministic review. Requesting review only moves the AI proposal to `review_required`; it does **not** convert it automatically into a `ResearchHypothesis`. The P4-01 explicit proposal → hypothesis endpoint remains a separate governance action.
- Added lifecycle observations: `ai_research_run_started`, `ai_research_run_completed`, `ai_research_run_failed`, `ai_proposal_reviewed`, `ai_proposal_suppressed`, and `ai_proposal_review_requested`, with safe metadata only.
- Added APIs: `POST /v1/research/ai/runs`, `GET /v1/research/ai/runs`, `GET /v1/research/ai/runs/{run_id}`, `GET /v1/research/ai/runs/{run_id}/proposals`, `GET /v1/research/ai/proposals/{proposal_id}/review`, and `POST /v1/research/ai/proposals/{proposal_id}/request-review`.
- Failure isolation persists sanitized failed runs for missing AI configuration/provider errors without affecting API startup, Phase-2 trading, Phase-3 deterministic research, Risk Engine, workers, or order execution.
- P4-02 dedicated tests: **15/15 passed**. P4-01 regression: **25/25 passed**. Phase-3 regression: **153/153 passed**. Combined research suite: **193/193 passed**.
- **AI research runs and proposal rankings do not authorize trading. Accepted ideas must still pass deterministic hypothesis, experiment, candidate, promotion and Phase-2 risk/execution controls.**
- **Known issues:** no real Gemini request or Docker/PostgreSQL integration was performed in the sandbox. Runtime validation with configured Google AI Studio credentials remains a separate local/integration step.

### 09 Sep 2026 — P4-01 — AI Research Agent Foundation + Google AI Studio Integration

- Added a provider-independent AI research layer under `apps/api/packages/research/ai/`. `ResearchAIProvider` separates deterministic research services from provider implementation; the initial provider uses Google Gemini / Google AI Studio through the HTTPS Generative Language API.
- Google AI configuration is optional and environment-only: `GOOGLE_AI_API_KEY`, `GOOGLE_AI_MODEL`, `GOOGLE_AI_TEMPERATURE`, `GOOGLE_AI_MAX_OUTPUT_TOKENS`, and `GOOGLE_AI_TIMEOUT_SECONDS`. No API key is committed. If the key is absent, application startup and all deterministic Phase-3 research remain healthy; AI generation reports a clear not-configured state.
- Added persisted `AIResearchProposal` with `proposal_version = "1.0.0"` and `prompt_version = "1.0.0"`, model/provider configuration, exact bounded evidence scope, structured research conditions, evidence references, bounded model confidence/research priority, lifecycle status, canonical SHA-256 deduplication, and optional converted-hypothesis provenance. Private chain-of-thought is not requested or stored.
- Supported proposal types: `hypothesis_candidate`, `strategy_filter_candidate`, `feature_combination_candidate`, `parameter_candidate`, `regime_candidate`, `exit_improvement_candidate`, `risk_research_candidate`, and `execution_quality_candidate`. Proposal workflow statuses are research-only: `generated`, `review_required`, `accepted_for_research`, `rejected`, `converted`, and `archived`.
- Gemini responses must validate against strict Pydantic structured-output schemas. Unsupported proposal types, malformed JSON, out-of-range scores, executable/code-like condition fields, and evidence IDs outside the bounded context are rejected. The service never uses `eval`, `exec`, dynamic Python execution, or downloaded scripts.
- Added a deterministic bounded context builder over persisted Phase-3 observations, features, regimes, outcomes, hypotheses, experiments, candidates, promotion evaluations, and aggregate performance. It uses fixed limits, preserves exact source/reference IDs, excludes AI lifecycle feedback from generation scope, and recursively removes secret-like keys before provider submission.
- Added explicit AI proposal → `ResearchHypothesis` conversion. Conversion requires a reviewed/accepted proposal, preserves proposal/provider/model/prompt/configuration/data-scope provenance, creates a `proposed` unvalidated hypothesis, and still requires the existing P3-06 experiment → candidate → promotion-gate workflow. No AI proposal can create or approve a candidate directly.
- Added ResearchObservation lifecycle events: `ai_proposal_generated`, `ai_proposal_status_changed`, and `ai_proposal_converted_to_hypothesis`.
- Added APIs: `GET /v1/research/ai/health`, `POST /v1/research/ai/proposals/generate`, `GET /v1/research/ai/proposals`, `GET /v1/research/ai/proposals/{id}`, `PATCH /v1/research/ai/proposals/{id}/status`, and `POST /v1/research/ai/proposals/{id}/create-hypothesis`. AI health returns configuration/model/version metadata only and never returns the API key or performs an expensive model request.
- Added Alembic migration `012_ai_research_proposals`; PostgreSQL remains authoritative and the previous Phase-3 migration history is preserved. Docker and Render configuration accept optional Gemini environment variables without embedding credentials.
- Failure isolation covers missing keys, provider timeouts/unavailability, malformed structured output, authentication/quota failures, and invalid model responses. One generation request performs at most one primary provider call; context/output/timeout controls are bounded.
- **AI-generated proposals are research suggestions only. They cannot place orders, bypass the Risk Engine, approve candidates, or activate Demo/Live trading.** Every accepted idea still enters deterministic hypothesis/experiment/candidate/promotion governance before any later execution integration.
- Tests use fake/mock providers and require no real Gemini key. P4-01 tests cover provider abstraction/configuration, missing-key health, structured validation, malformed/unsupported output, persistence/hash/deduplication, bounded context, secret filtering, observation/outcome evidence references, status/conversion provenance, lifecycle observations, provider timeout isolation, and absence of trading/promotion/credential capabilities.
- **Known issues:** no real Gemini network call was made in the sandbox; provider behavior against a configured Google AI Studio key still requires local/runtime verification. Docker/PostgreSQL integration remains a separate acceptance step.

### 08 Sep 2026 — P3-POST-01 — Windows Launcher + Auto Updater

- Added the Windows launcher source under `tools/windows-launcher/`, with PyInstaller build configuration for `dist/CryptoPlatform.exe`.
- Added root `start.bat` as a fallback that starts the existing Docker Compose stack, waits for API/frontend readiness, and opens the frontend without launching duplicate host-side backend/frontend processes.
- Added canonical application `VERSION` (`0.3.0`) and `launcher-config.example.json`; local `launcher-config.json` and environment variables can override frontend/API/Compose/update settings without embedding secrets.
- Added a deterministic HTTPS-only updater with strict manifest validation, SHA-256 package verification, safe ZIP extraction, temporary-download cleanup, protected local configuration handling, and backup/rollback for overwritten project files. Docker named volumes are not deleted or recreated by the updater.
- Added tests for version comparison, manifest validation/rejection, HTTPS enforcement, SHA-256 verification, ZIP-slip protection, configuration loading, no-update behavior, newer-version detection, readiness polling, and preservation of local `.env`/launcher configuration.
- **Trading safety is unchanged:** the launcher/updater only orchestrates the existing local stack and does not enable Live trading, bypass Phase-2 risk/execution, embed exchange credentials, or alter trading logic.
- Windows EXE builds must be produced on Windows using `build-launcher.bat`; the Linux agent environment cannot produce a genuine Windows PyInstaller executable.

### 08 Sep 2026 — P3-08 — Phase-3 Final Integration + Verification

- Completed and audited the Phase-3 R&D pipeline: `ResearchObservation → MarketFeatureSnapshot → MarketRegimeSnapshot → TradeOutcome → ResearchHypothesis → ResearchExperiment → ResearchCandidateStrategy → CandidatePromotionEvaluation`.
- Added frontend/dashboard-ready research integration reads: `GET /v1/research/overview`, `GET /v1/research/pipeline/status`, `GET /v1/research/learning-journal`, `GET /v1/research/lineage/{entity_type}/{entity_id}`, and `GET /v1/research/health`. Empty datasets return safe defaults.
- Research overview exposes Phase-3 counts, hypothesis/candidate status summaries, experiment pass/fail and average research scores, trade performance, latest regime context, and recent research activity.
- Pipeline status exposes research-data readiness only. These readiness flags do **not** activate trading or imply demo/live execution readiness.
- Learning Journal reuses authoritative `ResearchObservation` lifecycle history rather than introducing another journal datastore; deterministic newest-first filters support event type, symbol, strategy, date window, limit, and offset.
- Lineage reads expose available upstream/downstream provenance for observations, features, regimes, outcomes, hypotheses, experiments, and candidates, including evidence outcome IDs and candidate promotion evaluations. Lineage endpoints are read-only.
- Research health verifies application DB reachability through the existing DB layer, expected Phase-3 model names, research versions, PostgreSQL authority, no external exchange/AI health dependency, and expected migration head `011_research_candidates`.
- Audited migrations `005_research_observations → 006_market_features → 007_market_regimes → 008_trade_outcomes → 009_research_hypotheses → 010_research_experiments → 011_research_candidates`. PostgreSQL UUID/JSONB/Numeric, foreign keys, unique constraints, indexes, and timezone-aware timestamps remain authoritative. No production SQLite fallback was introduced.
- Audited Phase-2-to-Phase-3 observation hooks: authoritative trading/selection/strategy/risk/order/position/protection state is persisted before best-effort research observation writes, and research failures are logged instead of silently swallowed.
- Added final Phase-3 integration tests for router registration, overview empty/populated states, pipeline status, Learning Journal ordering/filters, lineage, health/version reporting, full research provenance chain, UUID/Decimal/datetime serialization, no Live approval route/state, and research/execution isolation. Complete available Phase-3 regression: **151/151 passed**.
- CORS now permits `PATCH` so the existing P3-05 research-only hypothesis status endpoint is browser-usable alongside GET/POST research APIs.
- **Safety boundary:** `approved_for_demo` remains research governance approval only. It does not activate a bot, submit an order, mutate production strategy configuration, bypass risk, use exchange credentials, or grant Live approval. There is no Phase-3 Live approval/activation route or status.
- **External AI boundary:** Phase 3 contains no OpenAI/Gemini/Google AI Studio/external model integration. Future research-agent proposals must still pass deterministic research, experiment, candidate, promotion, and Phase-2 risk/execution boundaries.
- **Known issues / local verification:** Docker/local PostgreSQL/frontend integration was intentionally not run. The sandbox lacks `psycopg2` and `ccxt`; broader pre-existing tests that import CCXT cannot collect, and some Phase-2 UUID store tests fail only under the SQLite test harness because those stores pass strings to PostgreSQL UUID-typed columns. These SQLite limitations were not used to weaken production PostgreSQL behavior. Local Docker/PostgreSQL/frontend verification is still required before Phase 3 is runtime-accepted.
- **Phase 3 code completion does not mean production/live trading readiness.** Production acceptance requires the separate local Docker/PostgreSQL integration test cycle.

### 08 Sep 2026 — P3-07 — Candidate Strategy + Promotion Gates

- Added persisted `ResearchCandidateStrategy` (`candidate_version = "1.0.0"`) and `CandidatePromotionEvaluation` (`gate_version = "1.0.0"`) with Alembic migration `011_research_candidates`. Candidates preserve hypothesis/experiment versions and hashes, exact historical scope, evidence, candidate/baseline metrics, conditions, and parameter overrides.
- Candidate lifecycle is research governance only: `draft` → `eligible`/`blocked` → `review_required` → explicit `approved_for_demo` or `rejected`; there is no `approved_for_live` state or Phase-3 live promotion path.
- Candidate creation requires an existing completed, persisted, passing `ResearchExperiment`. Same source experiment + candidate version + canonical candidate configuration hash is idempotent. Failed or incomplete experiments cannot create candidates.
- Added configurable deterministic promotion gates for historical sample size, minimum expectancy, profit factor, maximum drawdown, stability, data quality, execution-cost sensitivity, and regime robustness. Thresholds, results, warnings, and failure reasons are persisted with a canonical SHA-256 gate configuration hash.
- Added anti-overfitting safeguards/warnings for tiny samples, train/validation inconsistency or degradation, excessive parameter specificity, one-symbol dependence, one-regime dependence, extreme performance concentration, poor data quality, and high execution-cost sensitivity. These safeguards do not mathematically prove absence of overfitting.
- Added explicit review and approval actions. Passing gates only makes a candidate `eligible`; `request-review` is required before a separate explicit `approve-demo` action. Failed gates set the candidate `blocked` and prevent demo approval.
- **`approved_for_demo` is research governance approval only and does not activate a trading bot or submit orders.** It does not register an executable strategy, mutate Phase-2 strategy configuration, create positions/protection orders, bypass risk, use exchange credentials, or enable Live trading.
- Added APIs: `POST /v1/research/candidates/create`, `GET /v1/research/candidates`, `GET /v1/research/candidates/{id}`, `POST /v1/research/candidates/{id}/evaluate`, `GET /v1/research/candidates/{id}/promotion`, `POST /v1/research/candidates/{id}/request-review`, `POST /v1/research/candidates/{id}/approve-demo`, and `POST /v1/research/candidates/{id}/reject`.
- Added ResearchObservation lifecycle events: `candidate_created`, `candidate_evaluated`, `candidate_review_requested`, `candidate_approved_for_demo`, and `candidate_rejected`.
- Added 35 P3-07 targeted tests covering candidate eligibility/provenance/idempotency, all promotion gates, anti-overfitting warnings, explicit approval workflow, observations, filtering, versions, and execution/live/risk/credential isolation. Combined Phase-3 research regression: **138/138 passed**.
- **Known issues:** Docker/local PostgreSQL integration was intentionally not run. Sandbox validation uses isolated SQLite test databases while production remains PostgreSQL/Alembic. Regime/symbol robustness uses the exact persisted experiment evidence scope available today; later R&D phases can add richer cross-market robustness slices without changing Phase-2 execution behavior.



### 08 Sep 2026 — P3-06 — Replay + Experiment Evaluation Engine

- Added persisted `ResearchExperiment` model and Alembic migration `010_research_experiments`, linked to `ResearchHypothesis` with exact version/hash and historical-scope metadata.
- Added deterministic experiment types: historical replay, hypothesis validation, parameter comparison, regime validation, feature-filter validation, and execution-quality validation.
- Historical replay uses only persisted `TradeOutcome`/feature/regime/research data, processes outcomes chronologically, rejects feature context newer than trade entry, and never fetches exchange data.
- Added chronological train/validation splitting with no random shuffle and non-overlapping windows; exact train/validation boundaries and ordered evidence outcome IDs are persisted for reproducibility.
- Added metrics for trade count, win rate, gross/net PnL, expectancy, profit factor, average R, MAE/MFE, max drawdown, fees, slippage, and holding time plus candidate-vs-baseline differences.
- Added bounded deterministic experiment, stability, and data-quality scores. These are research heuristics, not ML probabilities or statistical-significance claims.
- Added configurable pass/fail gates for sample size, positive expectancy, drawdown, profit factor, stability, and data quality with explicit persisted failure reasons. Passing never validates/promotes or activates a strategy.
- Added APIs: `POST /v1/research/experiments/run`, `GET /v1/research/experiments`, `GET /v1/research/experiments/{id}`, and `GET /v1/research/experiments/{id}/comparison`.
- Added `experiment_started` / `experiment_completed` ResearchObservation events and queued-to-testing research workflow handling; execution/risk/bot/position/strategy configuration remain isolated.
- Added targeted tests for chronology/no leakage, split safety, hypothesis/baseline/parameter/regime/feature evaluation, scoring, gates, idempotency, filtering/comparison, lifecycle observations, workflow, and trading/runtime isolation.
- **Known issues:** Docker/local PostgreSQL integration was intentionally not run; sandbox validation uses isolated SQLite test databases while production remains PostgreSQL/Alembic. Current replay evaluates persisted completed-trade outcomes rather than simulating synthetic intrabar order fills.


### 08 Sep 2026 — P3-05 — Hypothesis + Research Engine

- Added persisted `ResearchHypothesis` model and Alembic migration `009_research_hypotheses`.
- Added deterministic hypothesis types: regime performance, symbol performance, feature condition, strategy filter, exit behavior, risk behavior, execution quality, and parameter candidate.
- Added bounded deterministic confidence and priority scoring with minimum-sample safety; scores are not p-values, ML probabilities, or claims of causality.
- Added evidence/baseline preservation, canonical SHA-256 evidence-scope deduplication, and research-only status workflow.
- Added `POST /v1/research/hypotheses/generate`, `GET /v1/research/hypotheses`, `GET /v1/research/hypotheses/{id}`, and `PATCH /v1/research/hypotheses/{id}/status`.
- Added lifecycle `ResearchObservation` events for proposal and status changes.
- Added tests for generation rules, scoring, small samples, deduplication, filtering, status lifecycle, observation linkage, and no trading/promotion capability.
- Known issue: Docker/PostgreSQL integration was intentionally not run in the sandbox; targeted research tests use an isolated SQLite test database while production remains PostgreSQL/Alembic.

### 08 Sep 2026 — P3-04 — Trade Outcome + Learning Analytics

- Added persisted `TradeOutcome` model with `outcome_version = "1.0.0"`, authoritative Phase-2 position linkage, feature/regime snapshot links, Decimal/Numeric trade economics, and JSONB research context.
- Added deterministic reconstruction of completed trades from persisted positions, applied fills/orders, risk decisions, protection state, research observations, closed candles, feature snapshots, and regime snapshots; no second trading ledger is introduced.
- Added calculations for gross/net PnL, return percentage, fees, observed slippage, holding time, closed-candle-only MAE/MFE, risk amount, and R multiple. Exit reasons support `take_profit`, `stop_loss`, `strategy_exit`, `manual`, `reconciliation`, and `unknown`.
- Added learning analytics grouped by symbol, strategy, strategy version, entry regime, timeframe, or exit reason with trade count, wins/losses, win rate, PnL, average win/loss, profit factor, expectancy, average R, holding time, MAE/MFE, fees/slippage totals, and ordered-outcome max drawdown.
- Added APIs: `POST /v1/research/outcomes/generate`, `GET /v1/research/outcomes`, `GET /v1/research/outcomes/{id}`, and `GET /v1/research/analytics/performance`.
- Added Alembic migration `008_trade_outcomes` and R&D `trade_outcome` observation emission with PnL, return, exit reason, MAE/MFE, R multiple, regime, fees, and slippage context.
- Added targeted tests for outcome calculations, TP/SL and win/loss cases, no-future-leakage MAE/MFE, idempotency, regime/feature linkage, analytics grouping/profit factor/expectancy/drawdown, observation linkage, and execution isolation.
- **Known issues:** full Docker/PostgreSQL integration is intentionally not run for this prompt; sandbox validation uses an isolated SQLite test database because `psycopg2` is unavailable. Slippage remains zero when no persisted observation supplies an execution-slippage value.

### 08 Sep 2026 — P3-03 — Market Regime Engine

- Added deterministic, versioned `MarketRegimeSnapshot` persistence with `regime_version = "1.0.0"`, canonical SHA-256 configuration hashes, supporting signals, confidence strength, and transition metadata.
- Added regimes: `trending_bull`, `trending_bear`, `ranging`, `high_volatility`, `low_volatility`, `breakout`, `mean_reverting`, `transition`, and `unknown`.
- Added research APIs: `POST /v1/research/regimes/classify`, `GET /v1/research/regimes`, `GET /v1/research/regimes/{id}`, and `GET /v1/research/regimes/current`.
- Added Alembic migration `007_market_regimes` and the `MarketRegimeSnapshot` database model, linked to persisted market feature snapshots and optional R&D observations.
- Added targeted tests for regime classifications, deterministic confidence, no-future-leakage behavior, idempotency, transition detection, current/history retrieval, observation linkage, and research/execution isolation.
- Market regime observations emit `event_type = "market_regime"` with confidence, reason, feature/regime identifiers, and transition context.
- **Known issues:** full Docker/PostgreSQL integration was intentionally not run for this phase; sandbox targeted tests use an isolated SQLite test database because the environment does not include the project PostgreSQL driver.

---

## Phase-3 Research API Inventory

### Observations
- `GET /v1/research/observations`
- `GET /v1/research/observations/{id}`
- `GET /v1/research/summary`

### Features
- `POST /v1/research/features/generate`
- `GET /v1/research/features`
- `GET /v1/research/features/{id}`

### Regimes
- `POST /v1/research/regimes/classify`
- `GET /v1/research/regimes`
- `GET /v1/research/regimes/current`
- `GET /v1/research/regimes/{id}`

### Outcomes / Analytics
- `POST /v1/research/outcomes/generate`
- `GET /v1/research/outcomes`
- `GET /v1/research/outcomes/{id}`
- `GET /v1/research/analytics/performance`

### Hypotheses
- `POST /v1/research/hypotheses/generate`
- `GET /v1/research/hypotheses`
- `GET /v1/research/hypotheses/{id}`
- `PATCH /v1/research/hypotheses/{id}/status`

### Experiments
- `POST /v1/research/experiments/run`
- `GET /v1/research/experiments`
- `GET /v1/research/experiments/{id}`
- `GET /v1/research/experiments/{id}/comparison`

### Candidates / Promotion
- `POST /v1/research/candidates/create`
- `GET /v1/research/candidates`
- `GET /v1/research/candidates/{id}`
- `POST /v1/research/candidates/{id}/evaluate`
- `GET /v1/research/candidates/{id}/promotion`
- `POST /v1/research/candidates/{id}/request-review`
- `POST /v1/research/candidates/{id}/approve-demo`
- `POST /v1/research/candidates/{id}/reject`

### Overview / Dashboard
- `GET /v1/research/overview`

### Learning Journal
- `GET /v1/research/learning-journal`

### Lineage / Provenance
- `GET /v1/research/lineage/{entity_type}/{entity_id}`

### Health / Pipeline Status
- `GET /v1/research/health`
- `GET /v1/research/pipeline/status`

All Phase-3 endpoints are research/analytics/governance surfaces. They do not replace Phase-2 risk or execution architecture.

---

## Prerequisites

Before running the platform, ensure you have the following installed on your machine:
- **Docker**: Docker Engine 24.0+ / Docker Desktop (Linux, macOS, or Windows WSL2)
- **Docker Compose**: Compose v2+ (comes bundled with Docker Desktop)

---

## Getting Started

### 1. Create `.env` Configuration File

Copy the safe example environment file `.env.example` to `.env`:

```bash
cp .env.example .env
```

*(On Windows PowerShell: `Copy-Item .env.example .env`)*

### 2. Start the Docker Stack

Build and start all services in the background:

```bash
docker compose up --build -d
```

### 3. Check Service Status

Verify that all containers are up and healthy:

```bash
docker compose ps
```

### 4. Viewing Logs

Stream logs from all services or a specific service:

```bash
# All logs
docker compose logs -f

# Tail last 100 lines across all services
docker compose logs --tail=100

# Specific service logs
docker compose logs -f api
docker compose logs -f web
docker compose logs -f celery-worker
```

### 5. Rebuilding Containers

To rebuild container images without cache or after making dependency changes:

```bash
docker compose up --build --force-recreate -d
```

### 6. Checking API Health

Verify the FastAPI backend health endpoint:

```bash
curl http://localhost:8000/health
```

Expected response:
```json
{"status":"ok"}
```

### 7. Opening the Frontend

Open your browser and navigate to:
[http://localhost:3000](http://localhost:3000)

You should see:
```text
Adaptive Crypto Trading Platform
Development Environment: Running
```

### 8. Stopping the Docker Stack

To stop the containers:

```bash
docker compose down
```

To stop containers and remove named volumes (resets database and cache):

```bash
docker compose down -v
```

## FRONTEND-WIRING-FIX-01 — Futuristic Frontend Restored + Backend/R&D Wiring

**Date:** 08 Sep 2026

`apps/web` is the canonical frontend. The previous placeholder Next.js page was replaced by the supplied futuristic multi-page dashboard, while `apps/api`, Phase-2/Phase-3 logic, migrations, workers, Docker services, `VERSION`, `start.bat`, `build-launcher.bat`, and `tools/windows-launcher/` remain from the latest project state.

### Frontend URLs and API configuration

- Local frontend: `http://localhost:3000`
- Local backend default: `http://localhost:8000`
- Central frontend API client: `apps/web/lib/api.ts`
- Configuration variable: `NEXT_PUBLIC_API_BASE_URL`
- Render/production example: `NEXT_PUBLIC_API_BASE_URL=https://<render-api-host>`

The frontend does not hard-code a Render hostname. Docker passes `NEXT_PUBLIC_API_BASE_URL` into the web image build so the browser bundle uses the configured API origin.

### Trading page wiring

The restored Dashboard, Market, Symbol Selection, Strategies, Bots, Orders, Positions, Performance, and Logs screens use the existing backend APIs where those APIs exist. When persisted data is empty or the backend is unavailable, the UI displays loading/empty/error states rather than invented positive trading data. Bot screens are read-oriented; no trading command is fired automatically.

### Phase-3 R&D wiring

Research Overview, Market Regimes, Strategy Lab, Experiments, Learning Journal, and Candidate Strategies consume the current `/v1/research/*` APIs, including overview, pipeline/health, regimes, hypotheses, experiments, learning journal, candidates, promotion evaluations, and existing lineage-ready backend data. `approved_for_demo` remains research governance approval only and does not activate a bot or submit an order.

### Docker web service and CORS

`docker-compose.yml` continues to build the web service from `./apps/web`, exposes port `3000`, and supplies `NEXT_PUBLIC_API_BASE_URL`. Backend CORS remains configurable through `CORS_ALLOW_ORIGINS`; its safe local default includes `http://localhost:3000` rather than using wildcard CORS.

### Known issues / build notes

The supplied futuristic frontend originated from Windows and bundled a Windows-only Next.js SWC native package. In the agent Linux sandbox, `next build` could not download the Linux SWC binary because outbound npm resolution was unavailable. The bundled TypeScript compiler (`tsc --noEmit`) completed successfully. A normal `npm ci && npm run build` should be rerun in the intended local/Docker environment, where the Linux container installs its own platform-correct dependencies.

The launcher/updater does not change trading safety rules and does not activate Live trading.


## P4-05 — Strategy Evolution + Variant Generation + Champion–Challenger Research Engine

**Date:** 09 Sep 2026  
**Phase:** Phase 4 — Adaptive AI Research & Strategy Discovery  
**Progress:** Phase 4 (5/10)

P4-05 adds a bounded, research-only strategy evolution layer on top of accepted P4-03 blueprints and completed P4-04 validations. `AIStrategyVariant` records are immutable lineage-preserving mutations; `AIStrategyEvolutionRun` records bound each generation cycle; and `ChampionChallengerComparison` records deterministic, same-scope research comparisons.

Variant generation supports neighboring parameter search, conservative parameter shifts, entry-filter simplification, exit adjustments, regime-filter adjustments, complexity reduction, risk-constraint tightening, execution-cost variants, and optional AI-assisted suggestions. AI-assisted generation reuses the existing `ResearchAIProvider` and is limited to one provider call per bounded request. Defaults are `AI_EVOLUTION_MAX_VARIANTS_PER_GENERATION=10`, `AI_EVOLUTION_MAX_CHANGED_FIELDS=3`, and `AI_EVOLUTION_MAX_GENERATIONS_PER_REQUEST=1`. Mutations are rejected if they add unsupported indicators, future data, executable code, risk bypass, relaxed maximum-risk constraints, disabled mandatory protection, or Live/Demo activation logic.

Variant validation reuses the P4-04 deterministic validator—there is no second backtester. The exact variant ID/hash is placed in the validation configuration and the variant lineage records validation IDs. Comparisons require the same historical data scope, symbol/timeframe/regime scope, fee/slippage assumptions, execution convention, train/validation boundaries, and gate configuration. Challenger selection uses a deterministic multi-metric trade-off score covering validation score, expectancy, profit factor, drawdown, stability, data quality, execution costs, overfit risk, and sample size. `AI_EVOLUTION_MIN_CHALLENGER_IMPROVEMENT` defaults to `0.03`, so microscopic changes do not replace the research champion.

Anti-overfitting safeguards bound variant counts/mutation width, penalize small or unstable improvements, preserve parameter-sensitivity/overfit metadata from P4-04, and prevent incompatible-scope comparisons. Evolution does not claim future profitability. A **Research champion** means the best currently validated research variant within a defined comparison scope. It is **not an active trading strategy** and has no authority to place orders, approve Demo, bypass Phase-2 risk, mutate production strategy configuration, or activate Demo/Live trading.

### P4-05 APIs

- `POST /v1/research/ai/evolution/runs`
- `GET /v1/research/ai/evolution/runs`
- `GET /v1/research/ai/evolution/runs/{run_id}`
- `GET /v1/research/ai/variants`
- `GET /v1/research/ai/variants/{variant_id}`
- `POST /v1/research/ai/variants/{variant_id}/validate`
- `GET /v1/research/ai/variants/{variant_id}/validations`
- `POST /v1/research/ai/evolution/compare`
- `GET /v1/research/ai/evolution/comparisons`
- `GET /v1/research/ai/evolution/comparisons/{comparison_id}`
- `GET /v1/research/ai/blueprints/{blueprint_id}/champion`

Lifecycle observations include `ai_strategy_evolution_started`, `ai_strategy_variant_generated`, `ai_strategy_variant_validation_completed`, `ai_champion_challenger_compared`, `ai_research_champion_changed`, `ai_strategy_evolution_completed`, and `ai_strategy_evolution_failed`.


## P4-06 — Adaptive Regime-to-Strategy Matching + Research Portfolio Selection Engine

**Date:** 09 Sep 2026  
**Phase:** Phase 4 — Adaptive AI Research & Strategy Discovery  
**Progress:** Phase 4 (6/10)

P4-06 adds deterministic, research-only regime profiles, validated-strategy ranking, and simulated research portfolio construction on top of P4-04/P4-05 validation/evolution evidence. It reuses the Phase-3 regime vocabulary and never uses provider/model confidence as allocation authority.

- **Regime profiles:** `StrategyRegimeProfile` summarizes regime-specific simulated trade count, expectancy, profit factor, win rate, drawdown, stability, data quality, overfit risk, execution-cost drag, strengths/weaknesses, warnings, and a deterministic compatibility score. Tiny samples are penalized through `AI_MATCH_MIN_REGIME_TRADES`.
- **Matching:** only completed passing deterministic validations are eligible. Failed validations, excessive overfit risk, poor data quality, incompatible symbol/timeframe scope, and weak regime evidence are filtered. P4-05 research champion status is advisory only; a stronger regime-specific challenger may rank above a champion.
- **Research portfolios:** supports `regime_specific`, `multi_regime`, `diversified_research`, `low_drawdown_research`, `stability_weighted`, and `equal_weight_research`. Allocation methods are equal, compatibility-weighted, stability-weighted, inverse-drawdown-weighted, and composite research weighting.
- **Concentration/correlation:** `AI_PORTFOLIO_MAX_COMPONENTS`, `AI_PORTFOLIO_MAX_COMPONENT_WEIGHT`, and `AI_PORTFOLIO_MAX_PAIRWISE_CORRELATION` bound simulated composition. Pairwise correlations use overlapping `BlueprintSimulatedTrade` return series only; insufficient overlap is reported instead of fabricated.
- **Portfolio evaluation:** persists expected expectancy/drawdown/overfit/cost drag, diversification, concentration, robustness, data quality, readiness score, warnings, and explicit blocking reasons. Research readiness is a deterministic engineering score, not an ML probability.
- **Regime transitions:** read-only analysis shows components that remain eligible, drop out, or enter the ranking when regime context changes. It never switches production strategies or bots.
- **Workflow:** portfolio states remain research-only: `draft`, `evaluated`, `review_required`, `accepted_for_research`, `rejected`, `archived`. Review/accept/reject actions change research metadata only.
- **APIs:** `/v1/research/ai/matching/profiles/generate`, `/matching/profiles`, `/matching/rank`, `/portfolios/build`, `/portfolios`, `/portfolios/{id}`, `/portfolios/{id}/evaluation`, `/portfolios/{id}/correlations`, `/matching/regime-transition`, plus explicit portfolio review/accept/reject endpoints.
- **Safety:** **Research portfolio weights are simulation/research metadata only. They do not allocate real/demo capital, switch bots, activate strategies, or submit orders.** No real account balance, leverage, exchange credentials, CCXT execution, Risk Engine bypass, candidate approval, Demo activation, or Live activation is introduced.

Known limitation: portfolio correlation uses simulated trade timestamps/returns rather than tick-level covariance; when overlap is insufficient, the API returns correlation-unavailable metadata and warnings. PostgreSQL remains authoritative; isolated SQLite is used only for unit testing.


## P4-07 — Shadow Research Deployment + Controlled Demo Candidate Handoff

**Date:** 09 Sep 2026  
**Phase:** Phase 4 — Adaptive AI Research & Strategy Discovery  
**Progress:** Phase 4 (7/10)

P4-07 adds a request-driven **shadow research** layer and an explicit bridge from validated Phase-4 artifacts into the existing Phase-3 `ResearchCandidateStrategy` governance workflow. Shadow sessions consume persisted closed OHLCV/features/regimes only, reuse the P4-04 structured interpreter and conservative simulation conventions, and persist separate `ShadowResearchTrade` records. They never insert authoritative orders, fills, positions, or `TradeOutcome` records.

Shadow execution confirms signals on closed candles and uses next-candle-open simulation, P4-04's conservative `stop_first` TP/SL conflict policy, configured research fees/slippage, and normalized research sizing. Processing is bounded by `AI_SHADOW_MAX_CANDLES_PER_PROCESS` and remains FastAPI request-driven; there is no autonomous forever loop. Reprocessing previously covered data is idempotent. Expected-vs-observed drift tracks expectancy, win-rate, profit-factor, drawdown, execution-cost and holding-time changes, with a deterministic 0..1 drift score. Shadow readiness uses sample coverage, historical quality, observed performance and drift together with persisted gates such as minimum trades/expectancy/data quality/readiness and maximum drawdown/drift.

The controlled handoff persists `ResearchCandidateHandoff` provenance covering the source blueprint/variant, deterministic validation, optional shadow session and research portfolio, structured strategy logic, parameters, risk/protection requirements, validation/shadow metrics, readiness, warnings and blockers. Failed validation, poor data quality, excessive overfit risk, protection removal, invalid variant provenance, or required-but-unready shadow evidence block candidate creation. `AI_HANDOFF_REQUIRE_SHADOW` defaults to `false`.

Candidate creation is a separate explicit action. The handoff creates deterministic governance bridge research records where required, then calls the existing Phase-3 `ResearchCandidateService`, so the resulting candidate begins in `draft` and still requires the unchanged P3-07 promotion evaluation → `eligible` → `review_required` → explicit `approved_for_demo` workflow. No second candidate system exists. **Demo readiness is not Demo activation.** `approved_for_demo` remains an explicit Phase-3 research-governance state and does not itself start a trading bot or submit an order.

P4-07 APIs include `POST/GET /v1/research/ai/shadow/sessions`, process/pause/resume/complete, shadow trades/drift/readiness, plus `POST/GET /v1/research/ai/handoffs`, handoff readiness, explicit `create-candidate`, and rejection. Lifecycle events include `ai_shadow_session_created`, `ai_shadow_session_processed`, `ai_shadow_session_completed`, `ai_shadow_drift_evaluated`, `ai_candidate_handoff_created`, readiness passed/blocked, candidate created, and rejected. All stored lifecycle metadata is research-only and contains no credentials or private model reasoning.

Tests cover accepted-source requirements, closed-candle and no-future-leakage behavior, P4-04 interpreter/execution reuse, conservative intrabar handling, costs, research-ledger isolation, bounded/idempotent processing, drift/readiness gates, blueprint/variant sources, handoff quality/protection/overfit blockers, optional/required shadow behavior, deterministic handoff idempotency, explicit Phase-3 candidate reuse, promotion-gate preservation and no trading/Live authority. Docker/local PostgreSQL integration remains a separate runtime-verification step; PostgreSQL remains authoritative.



## P4-09 — Demo Strategy Manifest Compiler + Runtime Compatibility & Governance Gate

**Date:** 09 Sep 2026  
**Progress:** Phase 4 (9/10)

P4-09 adds the final controlled research/runtime handoff between an explicitly Phase-3 `approved_for_demo` candidate and the existing Phase-2 strategy/risk contract. Compilation requires an existing approved candidate plus a passing `CandidatePromotionEvaluation`; P4-09 cannot approve candidates itself. The resulting `DemoStrategyManifest` is immutable structured data, not executable AI code. It freezes the exact available research lineage, entry/exit/protection rules, parameter values, symbol/timeframe/regime scope, feature/indicator requirements, and conservative research risk constraints.

The deterministic runtime-compatibility check validates the existing `packages.risk.models.StrategyOrderProposal` boundary: closed-candle inputs, supported structured operators/indicators/timeframes/symbols, mandatory protection, no future/look-ahead logic, no dynamic code, no credential/exchange dependency, and an explicit statement that Phase-2 Risk Engine remains final execution authority. Strategy proposals contain no strategy-supplied quantity; any future accepted quantity remains a Risk Engine decision.

The explicit manifest flow is `compiled → review_required → ready_for_demo_runtime`. A `DemoRuntimeRelease(status=ready)` is a governance/runtime handoff artifact only. **`ready_for_demo_runtime` and `DemoRuntimeRelease(status=ready)` do not start a bot or place an order.** Release gates require the candidate to remain `approved_for_demo`, the original promotion evaluation to remain passing, a passing compatibility check, minimum compatibility/readiness thresholds, and—when configured—no unresolved severe P4-08 monitoring trigger. Revocation changes only manifest/release eligibility metadata and does not issue bot stop/start commands.

**Phase-2 Risk Engine remains final execution authority for every future Demo order proposal.** Research risk constraints in a manifest are hints/conservative bounds only and cannot increase platform risk, bypass daily-loss/drawdown/position limits, disable kill switches, or remove mandatory protection. The read-only runtime contract contains no API keys, encrypted credential payloads, passwords, capital allocation, exchange clients/configuration, or bot commands.

Configuration defaults: `AI_DEMO_MANIFEST_MIN_COMPATIBILITY_SCORE=0.80`, `AI_DEMO_RELEASE_MIN_READINESS_SCORE=0.75`, and `AI_DEMO_RELEASE_BLOCK_SEVERE_TRIGGERS=true`. PostgreSQL is authoritative; migration head is `020_demo_strategy_manifests`.

APIs: `POST /v1/research/ai/demo-manifests/compile`, manifest list/get/lineage, compatibility check/read, readiness, runtime-contract, request-review, release, revoke, and Demo release list/get endpoints. Lifecycle observations include manifest compiled/compatibility/review/ready/blocked and runtime release created/revoked events with safe metadata only.

P4-09 dedicated tests cover governance prerequisites, exact structured manifest preservation, deterministic hash/idempotency, compatibility failures, monitoring release blockers, safe runtime contract, explicit release/revocation, observation events, and source-level absence of execution dependencies. Combined Phase-3 + P4-01 through P4-09 research regression: **317/317 passed** in the isolated test harness.

Known limitations: no Demo bot activation path is implemented in P4-09 by design; Docker/PostgreSQL runtime integration was not executed in the agent environment; future Phase-2 Demo activation must explicitly consume a ready runtime contract and still route every `StrategyOrderProposal` through the existing Risk Engine and Order Engine.

## P4-08 — Adaptive Research Monitoring + Drift Trigger Engine + Supervised Research Worker

**Date:** 09 Sep 2026  
**Phase:** Phase 4 — Adaptive AI Research & Strategy Discovery  
**Progress:** Phase 4 (8/10)

P4-08 adds PostgreSQL-authoritative monitoring policies, deterministic trigger events, bounded adaptive research jobs, and a dedicated supervised `services/research-monitor-worker` process. FastAPI remains stateless/request-driven; persistent monitoring loops run only in the supervised worker. Redis/Valkey remains transient coordination infrastructure and is not the source of truth for policies, triggers, jobs, or worker heartbeat state.

- **Monitoring policies:** research-only lifecycle `draft`, `enabled`, `paused`, `disabled`, `archived`. Enabling a policy does not enable a trading strategy. Policies persist exact symbol/timeframe/regime/strategy and Phase-4 source scope, trigger rules, deterministic thresholds, minimum sample size, cooldown, and canonical SHA-256 configuration hash.
- **Deterministic triggers:** reuse Phase-3 regime snapshots and persisted trade/validation/shadow/candidate/portfolio evidence. Supported triggers cover regime changes, expectancy/win-rate/profit-factor/drawdown degradation, fee/slippage/execution-cost drift, signal/shadow drift, stability/data-quality/overfit degradation, candidate staleness, and research-portfolio degradation. Provider/model confidence is not trigger authority.
- **Severity/confidence:** both are bounded deterministic engineering scores from evidence magnitude, sample sufficiency, data quality/completeness, and evidence scope. They are not ML probabilities or statistical-significance claims. Tiny samples are suppressed or receive low confidence.
- **Cooldown/deduplication:** trigger hashes include policy, trigger type, thresholds and exact evidence scope/metrics. Unchanged evidence is idempotent. New evidence during policy cooldown is persisted as suppressed rather than flooding downstream research.
- **Adaptive research jobs:** supported jobs include AI research reruns, deterministic hypothesis regeneration, blueprint review/revalidation, evolution review, regime-matching refresh, portfolio rebuild review, shadow readiness review and candidate readiness review. Jobs reuse existing P4-02/P4-04/P4-05/P4-06/P4-07 services where the source scope permits; no duplicate research engine is introduced. Jobs use bounded retry state and sanitized failure reasons.
- **Auto queue:** `AI_MONITOR_AUTO_QUEUE_RESEARCH=false` by default. With the default, triggers are persisted only and `/queue-research` is explicit. When enabled, only bounded research jobs may be queued—never trading actions.
- **Supervised worker:** `services/research-monitor-worker/main.py` runs heartbeat → bounded enabled-policy batch → deterministic evaluation → optional queue → bounded queued-job batch → persisted cycle metrics → sleep. Limits are controlled by `AI_MONITOR_MAX_POLICIES_PER_CYCLE`, `AI_MONITOR_MAX_TRIGGERS_PER_CYCLE`, `AI_MONITOR_MAX_JOBS_PER_CYCLE`, `AI_MONITOR_POLL_SECONDS`, and `AI_MONITOR_MAX_JOB_RETRIES`.
- **Worker status:** PostgreSQL stores worker name, heartbeat, cycle timestamps, policy/trigger/job counters, failures and sanitized last error. `GET /v1/research/ai/monitoring/status` exposes safe readiness metadata only.
- **APIs:** policy create/list/get/update/evaluate/pause/resume; trigger list/get/queue/acknowledge; adaptive-job list/get/cancel; monitoring status. These endpoints are frontend-ready for future Policies, Drift Alerts, Triggers, Jobs and Worker Health screens.
- **Docker/Render:** Docker adds an independent `research-monitor-worker` service. Render includes a dedicated background worker entry using the same PostgreSQL research state. The loop is never hosted inside FastAPI.
- **PostgreSQL authority:** migration `019_research_monitoring` follows `018_shadow_research_handoffs`. No production SQLite datastore is introduced.
- **Tests:** P4-08 unit coverage verifies policy lifecycle/hash/filtering, regime/performance/shadow/staleness triggers, insufficient-sample behavior, severity/confidence, cooldown/dedup, explicit/optional auto queue, idempotent jobs, bounded retries/cancellation, bounded worker batches/heartbeat, lifecycle observations, pipeline reuse, separate-worker architecture and trading-safety capability absence. Final combined Phase-3 + P4-01 through P4-08 research regression: **304/304 passed** in the isolated agent test harness.

**Adaptive research monitoring can trigger research work only. It cannot activate strategies, allocate capital, bypass risk, or submit Demo/Live orders.**

**Persistent monitoring loops run in supervised workers, not FastAPI.**

Known limitation: P4-08 evaluates persisted evidence in bounded polling cycles rather than acting as a low-latency market-event bus. That is intentional—the subsystem is research monitoring, not execution infrastructure. Local Docker/PostgreSQL runtime verification remains required separately.
