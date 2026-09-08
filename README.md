# Adaptive Crypto Trading Platform

Adaptive Crypto Trading Platform — Local Development Environment.

## Project Status

- **Current Date:** 08 Sep 2026
- **Current Phase:** Phase 3 — R&D / Learning Intelligence
- **Current Progress:** Phase 3 (8/8) — COMPLETE
- **Phase Status:** 8/8 — CODE COMPLETE

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
│   └── research-worker/    # Background R&D & learning worker (placeholder)
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


## Changelog

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
