@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo Crypto Platform - Windows fallback launcher
if "%CRYPTO_PLATFORM_BACKEND_HEALTH_URL%"=="" set "CRYPTO_PLATFORM_BACKEND_HEALTH_URL=http://localhost:8000/health"
if "%CRYPTO_PLATFORM_FRONTEND_URL%"=="" set "CRYPTO_PLATFORM_FRONTEND_URL=http://localhost:3000"
if not exist "docker-compose.yml" (
  echo [ERROR] docker-compose.yml was not found in %CD%
  exit /b 2
)

where docker >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Docker CLI was not found. Install/start Docker Desktop.
  exit /b 3
)

docker info >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Docker daemon is not ready. Start Docker Desktop first.
  exit /b 4
)

docker compose version >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Docker Compose v2 is unavailable.
  exit /b 5
)

echo [INFO] Starting existing Docker Compose stack...
docker compose up -d
if errorlevel 1 (
  echo [ERROR] Docker Compose startup failed.
  exit /b 6
)

echo [INFO] Waiting for API/frontend readiness...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$deadline=(Get-Date).AddSeconds(180); $api='%CRYPTO_PLATFORM_BACKEND_HEALTH_URL%'; $web='%CRYPTO_PLATFORM_FRONTEND_URL%';" ^
  "$apiOk=$false; $webOk=$false; while((Get-Date)-lt $deadline){" ^
  "try { $r=Invoke-WebRequest -UseBasicParsing -Uri $api -TimeoutSec 3; if($r.StatusCode -lt 500){$apiOk=$true} } catch {}" ^
  "try { $r=Invoke-WebRequest -UseBasicParsing -Uri $web -TimeoutSec 3; if($r.StatusCode -lt 500){$webOk=$true} } catch {}" ^
  "if($apiOk -and $webOk){exit 0}; Start-Sleep -Seconds 2 }; exit 1"
if errorlevel 1 (
  echo [ERROR] API or frontend did not become ready within 180 seconds.
  echo [INFO] Inspect status with: docker compose ps
  echo [INFO] Inspect logs with: docker compose logs --tail=100
  exit /b 7
)

echo [OK] API ready
echo [OK] Frontend ready
echo Opening %CRYPTO_PLATFORM_FRONTEND_URL%
start "" "%CRYPTO_PLATFORM_FRONTEND_URL%"
exit /b 0
