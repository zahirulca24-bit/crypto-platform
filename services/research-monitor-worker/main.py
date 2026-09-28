"""Supervised P4-08 research monitor worker.

Persistent loop lives here, never in FastAPI. PostgreSQL is authoritative;
Redis/Valkey remains transient coordination infrastructure only.
"""
from __future__ import annotations
import os, sys, time, logging
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
API=ROOT/'apps'/'api'
if str(API) not in sys.path: sys.path.insert(0,str(API))

from database import SessionLocal
from packages.research.ai.monitoring import ResearchMonitoringService

logging.basicConfig(level=os.getenv('LOG_LEVEL','INFO'),format='%(asctime)s %(levelname)s %(message)s')
log=logging.getLogger('research-monitor-worker')

def _poll_seconds():
    try:return max(1,min(3600,int(os.getenv('AI_MONITOR_POLL_SECONDS','60'))))
    except ValueError:return 60

def run_cycle():
    db=SessionLocal()
    try:return ResearchMonitoringService(db).worker_cycle('research-monitor-worker')
    finally:db.close()

def main():
    log.info('research monitor worker started; research-only, no trading authority')
    try:
        while True:
            try:log.info('cycle=%s',run_cycle())
            except Exception as exc:log.exception('bounded monitor cycle failed: %s',type(exc).__name__)
            time.sleep(_poll_seconds())
    except KeyboardInterrupt:log.info('research monitor worker stopped')

if __name__=='__main__':main()
