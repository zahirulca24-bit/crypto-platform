from packages.exchange import DemoOrderStore
from packages.positions import PositionEngine, PositionStore
from packages.protection import ProtectionService, ProtectionStore
from packages.runtime import BotCommandRequest, BotRuntime, RuntimeStore


def runtime(db_session):
    db=db_session/'runtime.db'; positions=PositionEngine(PositionStore(db))
    return BotRuntime(RuntimeStore(db),DemoOrderStore(db),positions,ProtectionService(positions.store,ProtectionStore(db)))


def test_restart_recovery_restores_owner_and_heartbeat(db_session):
    bot=runtime(db_session);bot.recover('supervisor-a','worker-a')
    state=bot.store.state()
    assert state.supervisor_id=='supervisor-a' and state.worker_id=='worker-a' and state.heartbeat_at


def test_duplicate_command_is_safe(db_session):
    bot=runtime(db_session)
    one=bot.command(BotCommandRequest(intent='start',idempotency_key='start-1'))
    two=bot.command(BotCommandRequest(intent='start',idempotency_key='start-1'))
    assert one.id==two.id
    assert bot.tick().status.value=='running'


def test_reconciliation_mismatch_is_journaled(db_session):
    bot=runtime(db_session)
    # Unknown is a durable local/exchange ambiguity and must be surfaced, not retried into a duplicate order.
    from packages.exchange.models import DemoOrder,OrderStatus,OrderType
    order=DemoOrder(risk_decision_id='00000000-0000-0000-0000-000000000001',client_order_id='unknown',symbol='BTC/USDT',side='BUY',type=OrderType.LIMIT,quantity='1',price='100',status=OrderStatus.UNKNOWN)
    bot.order_store.create(order)
    assert bot.reconcile()[0]['kind']=='order_reconciliation_mismatch'
    assert any(e.event_type=='reconciliation.issue' for e in bot.store.events())


def test_journal_is_persisted(db_session):
    bot=runtime(db_session);bot.command(BotCommandRequest(intent='pause',idempotency_key='pause-1'));bot.tick()
    assert any(e.event_type=='bot.command_applied' for e in bot.store.events())


