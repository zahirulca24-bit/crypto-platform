from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from uuid import UUID

from database import get_db
from packages.exchange.models import DemoOrder, DemoOrderSubmitRequest
from packages.exchange.demo import DemoOrderEngine, ProductionTradingBlocked, RiskDecisionNotApproved, RiskDecisionNotFound
from packages.exchange.storage import DemoOrderStore

from packages.risk.models import RiskDecision, RiskEvaluationRequest
from packages.risk.engine import RiskEngine
from packages.risk.storage import RiskDecisionStore

from packages.positions.models import PortfolioSummary, Position
from packages.positions.engine import PositionEngine
from packages.positions.storage import PositionStore

from packages.protection.models import PositionProtection, ProtectionRequest
from packages.protection.service import ProtectionService
from packages.protection.storage import ProtectionStore

from packages.runtime.models import BotCommand, BotCommandRequest, BotRuntimeState, JournalEvent
from packages.runtime.service import BotRuntime
from packages.runtime.storage import RuntimeStore

router = APIRouter(tags=['Phase 2 Integration'])

def get_risk_engine(db: Session = Depends(get_db)):
    return RiskEngine(RiskDecisionStore(db))

def get_position_engine(db: Session = Depends(get_db)):
    return PositionEngine(PositionStore(db))

def get_order_engine(db: Session = Depends(get_db), risk: RiskEngine = Depends(get_risk_engine), pos: PositionEngine = Depends(get_position_engine)):
    return DemoOrderEngine(risk.store, DemoOrderStore(db), trading_mode='demo', on_filled=pos.apply_filled_order)

def get_protection_service(db: Session = Depends(get_db), pos: PositionEngine = Depends(get_position_engine)):
    return ProtectionService(pos, ProtectionStore(db))

def get_bot_runtime(db: Session = Depends(get_db)):
    return BotRuntime(RuntimeStore(db))

@router.post('/v1/risk/evaluate', response_model=RiskDecision)
def evaluate_risk(request: RiskEvaluationRequest, engine: RiskEngine = Depends(get_risk_engine)) -> RiskDecision:
    return engine.evaluate(request)

@router.get('/v1/risk/decisions', response_model=list[RiskDecision])
def list_risk_decisions(limit: int = Query(100), offset: int = Query(0), engine: RiskEngine = Depends(get_risk_engine)):
    return engine.store.list(limit=limit, offset=offset)

@router.post('/v1/orders/demo/submit', response_model=DemoOrder)
def submit_demo_order(request: DemoOrderSubmitRequest, engine: DemoOrderEngine = Depends(get_order_engine)):
    try:
        return engine.submit(request)
    except (ProductionTradingBlocked, RiskDecisionNotApproved, RiskDecisionNotFound) as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get('/v1/orders', response_model=list[DemoOrder])
def list_orders(limit: int = Query(100), offset: int = Query(0), engine: DemoOrderEngine = Depends(get_order_engine)):
    return engine.order_store.list(limit=limit, offset=offset)

@router.get('/v1/orders/{order_id}', response_model=DemoOrder)
def get_order(order_id: str, engine: DemoOrderEngine = Depends(get_order_engine)):
    order = engine.order_store.get(order_id)
    if not order: raise HTTPException(status_code=404, detail='Order not found')
    return order

@router.get('/v1/positions', response_model=list[Position])
def list_positions(limit: int = Query(100), offset: int = Query(0), engine: PositionEngine = Depends(get_position_engine)):
    return engine.store.list(limit=limit, offset=offset)

@router.get('/v1/positions/{position_id}', response_model=Position)
def get_position(position_id: str, engine: PositionEngine = Depends(get_position_engine)):
    pos = engine.store.get(position_id)
    if not pos: raise HTTPException(status_code=404, detail='Position not found')
    return pos

@router.get('/v1/portfolio/summary', response_model=PortfolioSummary)
def portfolio_summary(engine: PositionEngine = Depends(get_position_engine)) -> PortfolioSummary:
    return engine.summary()

@router.post('/v1/protection/ensure', response_model=PositionProtection)
def ensure_protection(request: ProtectionRequest, engine: ProtectionService = Depends(get_protection_service)):
    try:
        return engine.ensure_protection(request)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get('/v1/protection', response_model=list[PositionProtection])
def list_protection(limit: int = Query(100), offset: int = Query(0), engine: ProtectionService = Depends(get_protection_service)):
    return engine.protection_store.list(limit=limit, offset=offset)

@router.get('/v1/protection/{position_id}', response_model=PositionProtection)
def protection_status(position_id: str, engine: ProtectionService = Depends(get_protection_service)):
    prot = engine.protection_store.get(position_id)
    if not prot: raise HTTPException(status_code=404, detail='Protection not found')
    return prot

@router.post('/v1/bot/commands', response_model=BotCommand)
def send_bot_command(request: BotCommandRequest, runtime: BotRuntime = Depends(get_bot_runtime)):
    return runtime.store.enqueue(request)

@router.get('/v1/bot/state', response_model=BotRuntimeState)
def bot_state(runtime: BotRuntime = Depends(get_bot_runtime)):
    return runtime.store.state()

@router.get('/v1/journal', response_model=list[JournalEvent])
def journal(limit: int = Query(100), offset: int = Query(0), runtime: BotRuntime = Depends(get_bot_runtime)):
    return runtime.store.events(limit, offset)

@router.get('/v1/dashboard/summary')
def dashboard_summary(pos: PositionEngine = Depends(get_position_engine), risk: RiskEngine = Depends(get_risk_engine)):
    summary = pos.summary()
    decisions = risk.store.list(limit=1)
    last = decisions[0].created_at.isoformat() if decisions else None
    return {
        'portfolio': summary.model_dump(mode='json'),
        'risk_status': {'last_evaluation': last, 'active_policies': 8},
        'bot_status': {'state': 'running', 'last_tick': last}
    }

@router.get('/v1/dashboard/recent-trades', response_model=list[DemoOrder])
def recent_trades(engine: DemoOrderEngine = Depends(get_order_engine)):
    return engine.order_store.list(limit=50)

@router.get('/v1/dashboard/bot-activity', response_model=list[JournalEvent])
def bot_activity(runtime: BotRuntime = Depends(get_bot_runtime)):
    return runtime.store.events(limit=100)

@router.get('/v1/dashboard/strategy-decisions', response_model=list[JournalEvent])
def strategy_decisions(runtime: BotRuntime = Depends(get_bot_runtime)):
    return [e for e in runtime.store.events(limit=500) if e.event_type == 'strategy.decision'][:100]

@router.get('/v1/dashboard/risk-status')
def risk_status(risk: RiskEngine = Depends(get_risk_engine)):
    decisions = risk.store.list(limit=1)
    last = decisions[0].created_at.isoformat() if decisions else None
    return {'last_evaluation': last, 'active_policies': 8}

@router.get('/v1/dashboard/system-status')
def system_status(runtime: BotRuntime = Depends(get_bot_runtime)):
    state = runtime.store.state()
    return {'bot_mode': state.mode.value, 'status': 'operational', 'errors': 0}
