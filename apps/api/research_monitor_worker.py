"""Durable research-monitor heartbeat worker.

The monitor observes persisted research policy/job state and publishes worker
health only.  It has no trading execution or exchange credential dependency and therefore
cannot place trades.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone

from sqlalchemy import text

from database import SessionLocal
from settings import AppSettings

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("crypto_platform.research_monitor")

UPSERT_HEARTBEAT = text("""
INSERT INTO research_monitor_worker_status
(worker_name,last_heartbeat,last_cycle_started,last_cycle_completed,policies_evaluated,
 triggers_detected,jobs_processed,jobs_failed,last_error,updated_at)
VALUES (:worker_name,:now,:now,:now,:policies,0,0,0,NULL,:now)
ON CONFLICT (worker_name) DO UPDATE SET
 last_heartbeat=EXCLUDED.last_heartbeat,
 last_cycle_started=EXCLUDED.last_cycle_started,
 last_cycle_completed=EXCLUDED.last_cycle_completed,
 policies_evaluated=EXCLUDED.policies_evaluated,
 last_error=NULL,
 updated_at=EXCLUDED.updated_at
""")


def run_cycle(db, worker_name: str) -> None:
    now = datetime.now(timezone.utc)
    policies = db.execute(text("SELECT count(*) FROM research_monitoring_policies WHERE status = 'active'" )).scalar_one()
    db.execute(UPSERT_HEARTBEAT, {"worker_name": worker_name, "now": now, "policies": int(policies)})
    db.commit()


def main() -> None:
    settings = AppSettings.from_env()
    settings.validate_startup()
    worker_name = os.getenv("RESEARCH_MONITOR_WORKER_NAME", "research-monitor-worker")
    interval = max(5.0, float(os.getenv("RESEARCH_MONITOR_INTERVAL_SECONDS", "30")))
    db = SessionLocal()
    try:
        while True:
            try:
                run_cycle(db, worker_name)
                logger.info("research_monitor.heartbeat", extra={"runtime_id": worker_name})
            except Exception:
                db.rollback()
                logger.exception("research_monitor.cycle_failed")
            time.sleep(interval)
    finally:
        db.close()


if __name__ == "__main__":
    main()
