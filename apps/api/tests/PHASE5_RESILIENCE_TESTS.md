# Phase 5 resilience test classification

P5-08 deliberately separates proof levels:

- **Deterministic/unit-concurrency**: in-process barriers, locks, deterministic adapters and persisted-state contracts. No sleeps, network, exchange keys, or real orders.
- **Integration-required**: real PostgreSQL/Redis failure injection. These tests are explicitly skipped unless infrastructure is genuinely available; mocks are not reported as infrastructure success.
- **Runtime-required**: process/network behavior such as a real WebSocket reconnect and PostgreSQL backend termination/reconnect. The current repository has no WebSocket transport, so that case remains an explicit skip rather than introducing a trading transport solely for a test.

Stable performance assertions are limited to CPU-only closed-candle strategy evaluation. No wall-clock bound is asserted for database, Redis, exchange, or network operations.
