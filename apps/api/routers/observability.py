from __future__ import annotations
from security_auth import current_principal

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_db
from packages.observability import AlertService, ObservabilityService, ObservabilityStore
from packages.observability.metrics import PrometheusMetricsCollector

router=APIRouter(tags=['Observability'])


def _redis_probe(settings):
    def probe():
        import redis
        client=redis.Redis.from_url(settings.redis_url,socket_connect_timeout=1.0,socket_timeout=1.0,decode_responses=False)
        try: return bool(client.ping())
        finally: client.close()
    return probe


def get_observability_service(request: Request, db: Session=Depends(get_db)):
    store=ObservabilityStore(db)
    alerts=AlertService(store,min_interval_seconds=request.app.state.settings.alert_min_interval_seconds)
    return ObservabilityService(store,alerts)


@router.get('/health/live')
def liveness(request: Request):
    return {'status':'alive','request_id':getattr(request.state,'request_id',None)}


@router.get('/health/ready')
def operational_readiness(request: Request, db: Session=Depends(get_db)):
    checks={'configuration': not bool(request.app.state.settings.validation_reasons()),'database':False,'redis':False}
    try: db.execute(text('SELECT 1')); checks['database']=True
    except Exception: pass
    try: checks['redis']=_redis_probe(request.app.state.settings)()
    except Exception: pass
    ready=all(checks.values())
    return Response(
        content=__import__('json').dumps({'status':'ready' if ready else 'not_ready','checks':checks}),
        status_code=200 if ready else 503,media_type='application/json')


@router.get('/metrics')
def metrics(request: Request, db: Session=Depends(get_db)):
    collector=PrometheusMetricsCollector(db,redis_probe=_redis_probe(request.app.state.settings),api_request_count=getattr(request.app.state,'api_request_count',0))
    return Response(content=collector.render(),media_type='text/plain; version=0.0.4; charset=utf-8')


@router.get('/v1/operations/incidents')
def incidents(limit:int=Query(100,ge=1,le=500),offset:int=Query(0,ge=0),service:ObservabilityService=Depends(get_observability_service)):
    return service.store.incidents(limit=limit,offset=offset)


@router.get('/v1/operations/alerts')
def alerts(limit:int=Query(100,ge=1,le=500),offset:int=Query(0,ge=0),service:ObservabilityService=Depends(get_observability_service)):
    return service.store.alert_history(limit=limit,offset=offset)
