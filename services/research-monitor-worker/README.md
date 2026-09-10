# Research Monitor Worker

P4-08 supervised research-only monitoring worker. It evaluates enabled PostgreSQL-backed monitoring policies in bounded batches, persists deterministic trigger events, optionally queues bounded research jobs, processes a bounded job batch, and records a PostgreSQL heartbeat. It never places orders, controls bots, allocates capital, decrypts credentials, or bypasses the Risk Engine.
