import time
from datetime import datetime,timezone
from .models import BotCommandRequest,BotIntent,BotStatus
class BotRuntime:
 def __init__(self,store,order_store,position_engine,protection_service,risk_engine=None,order_engine=None):self.store,self.order_store,self.position_engine,self.protection_service,self.risk_engine,self.order_engine=store,order_store,position_engine,protection_service,risk_engine,order_engine
 def command(self,r:BotCommandRequest):
  c=self.store.enqueue(r);self.store.journal('bot.command_queued',{'intent':c.intent.value});return c
 def record_closed_candle(self,symbol,selected=True,strategy_decision=None,risk_decision=None,order=None,position=None):
  """Worker hook for the closed-candle pipeline; it records facts but never runs in FastAPI."""
  self.store.journal('symbol.selected' if selected else 'symbol.rejected',{'symbol':symbol})
  if not selected:return
  self.store.journal('strategy.decision',{'symbol':symbol,'decision':strategy_decision or 'no_signal'})
  if risk_decision is not None:self.store.journal('risk.decision',{'decision_id':str(risk_decision.id),'approved':risk_decision.approved})
  if order is not None:self.store.journal('order.submission_result',{'order_id':str(order.id),'status':order.status.value})
  if position is not None:self.store.journal('position.changed',{'position_id':str(position.id),'realized_pnl':str(position.realized_pnl),'unrealized_pnl':str(position.unrealized_pnl)})
 def execute_closed_candle(self,risk_request,tp_price=None,sl_price=None,candle_closed=True):
  """The worker's single guarded demo flow. Strategies may supply intent, never quantity."""
  symbol=risk_request.proposal.symbol
  if not candle_closed:
   self.store.journal('symbol.rejected',{'symbol':symbol,'reason':'candle_not_closed'});return None
  if self.risk_engine is None or self.order_engine is None:raise RuntimeError('Runtime execution dependencies are unavailable')
  self.store.journal('symbol.selected',{'symbol':symbol});self.store.journal('strategy.decision',{'symbol':symbol,'decision':'proposal_received'})
  decision=self.risk_engine.evaluate(risk_request);self.store.journal('risk.decision',{'decision_id':str(decision.id),'approved':decision.approved})
  if not decision.approved:return decision,None,None
  from packages.exchange.models import DemoOrderSubmitRequest
  order=self.order_engine.submit(DemoOrderSubmitRequest(risk_decision_id=decision.id));self.store.journal('order.submission_result',{'order_id':str(order.id),'status':order.status.value})
  position=None;protection=None
  if order.status.value=='filled':
   position=self.position_engine.apply_filled_order(order);self.store.journal('position.changed',{'position_id':str(position.id),'realized_pnl':str(position.realized_pnl)})
   if tp_price is not None and sl_price is not None:
    from packages.protection.models import ProtectionRequest
    protection=self.protection_service.ensure(ProtectionRequest(position_id=position.id,tp_price=tp_price,sl_price=sl_price));self.store.journal('protection.changed',{'position_id':str(position.id),'status':protection.protection_status.value})
  return decision,order,protection
 def recover(self,supervisor_id='supervisor',worker_id='trading-worker'):
  s=self.store.state();s.supervisor_id,s.worker_id,s.heartbeat_at=supervisor_id,worker_id,datetime.now(timezone.utc);self.store.save_state(s);self.store.journal('runtime.recovered',{'worker_id':worker_id});return self.reconcile()
 def tick(self,supervisor_id='supervisor',worker_id='trading-worker'):
  s=self.store.state();s.supervisor_id,s.worker_id,s.heartbeat_at=supervisor_id,worker_id,datetime.now(timezone.utc)
  states={BotIntent.START:BotStatus.RUNNING,BotIntent.RESUME:BotStatus.RUNNING,BotIntent.PAUSE:BotStatus.PAUSED,BotIntent.STOP:BotStatus.STOPPED}
  for c in self.store.pending():s.status=states[c.intent];self.store.complete(c);self.store.journal('bot.command_applied',{'intent':c.intent.value})
  self.store.save_state(s);self.store.journal('runtime.heartbeat',{'status':s.status.value});return s
 def reconcile(self):
  issues=[]
  for o in self.order_store.list(500):
   if o.status.value=='unknown':
    issues.append({'kind':'order_reconciliation_mismatch','order_id':str(o.id)});self.store.journal('reconciliation.issue',issues[-1])
   if o.status.value=='filled':
    try:self.position_engine.apply_filled_order(o)
    except Exception as e:issues.append({'kind':'position_reconciliation_error','order_id':str(o.id)});self.store.journal('reconciliation.issue',issues[-1])
  for p in self.protection_service.reconcile():self.store.journal('protection.reconciled',{'position_id':str(p.position_id)})
  return issues
 def run_forever(self,interval_seconds=5):
  self.recover()
  while True:self.tick();time.sleep(interval_seconds)
