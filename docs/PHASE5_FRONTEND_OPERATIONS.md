# Phase 5 frontend operations integration

The NEXUS web application reads operational state from the FastAPI service configured by `NEXT_PUBLIC_API_BASE_URL`.

## Production origin and CORS

`NEXT_PUBLIC_API_BASE_URL` must contain only the public API origin (for example an HTTPS FastAPI service origin). It is browser-visible and must never contain credentials, tokens, database URLs, Redis URLs, encryption keys, or exchange secrets.

Production CORS is configured on the **backend**, not inferred by the frontend. `CORS_ALLOW_ORIGINS` must explicitly contain the deployed HTTPS web origin(s). Wildcard production CORS and localhost development origins are intentionally rejected by backend startup validation.

## Operator authentication

Read-only public Phase 5 status APIs remain usable without frontend credentials where the backend permits them. Protected safety and security APIs require the existing backend JWT/RBAC policies. The operator sign-in screen stores the returned access token in browser `sessionStorage`; passwords are never persisted by the web app.

The browser never receives decrypted exchange credentials. Credential screens consume `/v1/security/exchange-credentials`, which returns security-safe metadata and a one-way API-key fingerprint only.

## Safety boundary

The web app does not implement trading authorization or safety decisions itself. Confirmed halt/resume/pause commands are requests to the backend safety API. The backend remains authoritative for RBAC, kill switches, circuit breakers, reconciliation blocks, portfolio risk, order governance, and live execution eligibility.

LIVE/DEMO mode displayed by the UI comes from `/v1/system/readiness` and `/v1/system/capabilities`. The frontend has no local switch that can enable LIVE trading.
