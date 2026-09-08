# Windows Launcher

`CryptoPlatform.exe` is a thin local launcher/updater. It does not embed the application, database, Docker images, exchange credentials, or trading strategy logic.

## Build on Windows

From the repository root:

```bat
build-launcher.bat
```

This creates `dist\CryptoPlatform.exe` using PyInstaller. Python is required only to build the EXE; the built launcher itself embeds the Python runtime it needs.

## Configuration

Copy `launcher-config.example.json` to `launcher-config.json` if local overrides are required. The real config file is intentionally not packaged as a secret-bearing artifact.

Supported environment overrides include:

- `CRYPTO_PLATFORM_ROOT`
- `CRYPTO_PLATFORM_FRONTEND_URL`
- `CRYPTO_PLATFORM_BACKEND_HEALTH_URL`
- `CRYPTO_PLATFORM_COMPOSE_FILE`
- `CRYPTO_PLATFORM_UPDATE_MANIFEST_URL`
- `CRYPTO_PLATFORM_UPDATE_CHECK_ENABLED`
- `CRYPTO_PLATFORM_STARTUP_TIMEOUT_SECONDS`
- `CRYPTO_PLATFORM_HTTP_TIMEOUT_SECONDS`

The updater accepts HTTPS manifest/package URLs only. A missing manifest URL simply disables remote update checks.
