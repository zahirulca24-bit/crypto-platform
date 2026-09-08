# Adaptive Crypto Trading Platform

Adaptive Crypto Trading Platform — Local Development Environment (Phase 0).

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
