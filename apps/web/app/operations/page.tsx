"use client"
import { useMemo, useState } from "react"
import { api, formatApiError } from "@/lib/api"
import { useApiData } from "@/lib/use-api"
import { ConfirmAction } from "@/components/confirm-action"
import { EmptyState, ErrorState, LoadingState } from "@/components/data-state"
import { Metric, PageShell, Panel, fmt } from "@/components/page-shell"

type Readiness={status:string;runtime_mode:string;trading_mode:string;checks:Record<string,{ready:boolean;reasons:{code:string;message:string}[]}>}
type Capabilities={runtime_mode:string;trading_mode:string;capabilities:Record<string,{enabled:boolean;reasons:{code:string;message:string}[]}>}
type Exposure={equity:string;cash_balance:string;reserved_capital:string;available_capital:string;position_exposure:string;portfolio_exposure:string;open_positions:number;daily_realized_pnl:string;total_drawdown:string;symbol_exposure:Record<string,string>;strategy_exposure:Record<string,string>}
type Safety={trading_halted:boolean;blockers:Array<{code:string;scope:string;scope_key?:string;reason_code?:string}>;state:{global_control:{active:boolean;mode:string;reason_code?:string};bots:Record<string,{active:boolean;mode:string;reason_code?:string}>}}
type Circuit={breaker:string;open:boolean;failure_count:number;threshold:number;reason_code?:string;recovery_observed:boolean;opened_at?:string}
type Reconciliation={latest_run?:Record<string,unknown>;severe_unresolved_count:number;execution_blocked:boolean;active_lease?:{bot_id:string;worker_id:string;heartbeat_at:string;expires_at:string}}
type Credential={id:string;exchange_id:string;environment:string;api_key_fingerprint:string;validation_status:string;validated_at?:string;updated_at:string}
type Audit={id:string;action:string;outcome:string;target_type?:string;target_id?:string;request_id?:string;context?:Record<string,unknown>;created_at:string}
type Incident={id:string;category:string;severity:string;title:string;status:string;occurrence_count:number;last_seen_at:string;context?:Record<string,unknown>}
type Alert={id:string;category:string;severity:string;message:string;emitted_at:string;context?:Record<string,unknown>}

const BOT_ID="demo-bot"
const idempotency=()=>`web-${Date.now()}-${crypto.randomUUID()}`
const tone=(mode?:string)=>mode==="live"?"border-red-500/70 bg-red-500/20 text-red-100":mode==="demo"?"border-amber-400/50 bg-amber-400/10 text-amber-100":"border-slate-700 bg-slate-900 text-slate-300"

function DataPanel({title,state,children}:{title:string;state:{loading:boolean;error:string|null};children:React.ReactNode}){return <Panel title={title}>{state.loading?<LoadingState/>:state.error?<ErrorState message={state.error}/>:children}</Panel>}
function ReasonList({reasons}:{reasons?:Array<{code:string;message:string}>}){if(!reasons?.length)return null;return <div className="mt-2 space-y-1">{reasons.map(r=><div key={r.code} className="text-xs text-slate-500"><span className="font-mono text-amber-300">{r.code}</span> — {r.message}</div>)}</div>}

export default function OperationsPage(){
 const readiness=useApiData(()=>api.get<Readiness>("/v1/system/readiness"),[])
 const capabilities=useApiData(()=>api.get<Capabilities>("/v1/system/capabilities"),[])
 const exposure=useApiData(()=>api.get<Exposure>("/v1/portfolio/exposure"),[])
 const allocations=useApiData(()=>api.get<Record<string,unknown>[]>("/v1/portfolio/capital-allocation",{limit:50}),[])
 const limits=useApiData(()=>api.get<Record<string,unknown>>("/v1/portfolio/risk-limits"),[])
 const safety=useApiData(()=>api.get<Safety>("/v1/safety/status",{bot_id:BOT_ID}),[])
 const circuits=useApiData(()=>api.get<Circuit[]>("/v1/safety/circuit-breakers"),[])
 const reconciliation=useApiData(()=>api.get<Reconciliation>("/v1/reconciliation/status"),[])
 const incidents=useApiData(()=>api.get<Incident[]>("/v1/operations/incidents",{limit:50}),[])
 const alerts=useApiData(()=>api.get<Alert[]>("/v1/operations/alerts",{limit:50}),[])
 const credentials=useApiData(()=>api.get<Credential[]>("/v1/security/exchange-credentials"),[])
 const audits=useApiData(()=>api.get<Audit[]>("/v1/security/audit-events",{limit:50}),[])
 const [actionMessage,setActionMessage]=useState<string|null>(null)
 const reloadSafety=async()=>{await Promise.all([safety.reload(),circuits.reload(),reconciliation.reload()])}
 const doCommand=async(path:string,body:unknown)=>{setActionMessage(null);try{await api.post(path,body);await reloadSafety();setActionMessage("Command accepted by the backend safety layer.")}catch(e){setActionMessage(formatApiError(e));throw e}}
 const globalActive=!!safety.data?.state.global_control.active
 const botControl=safety.data?.state.bots?.[BOT_ID]
 const mode=readiness.data?.trading_mode ?? capabilities.data?.trading_mode
 const live=mode==="live"
 const criticalEvents=useMemo(()=>[...(incidents.data??[]).filter(x=>["critical","error"].includes(x.severity)),...(alerts.data??[]).filter(x=>["critical","error"].includes(x.severity))].slice(0,20),[incidents.data,alerts.data])
 return <PageShell title="Operations & Safety" subtitle="Phase 5 operational control plane backed by the real API. Every trading/safety decision remains enforced server-side; this UI cannot bypass risk, safety, reconciliation, or execution governance.">
   <div className={`mb-6 rounded-xl border p-4 ${tone(mode)}`}><div className="flex flex-wrap items-center justify-between gap-3"><div><div className="text-xs uppercase tracking-[.2em] opacity-75">Trading mode</div><div className="mt-1 text-2xl font-black tracking-wider">{mode?.toUpperCase()??"UNKNOWN"}</div></div>{live&&<div className="rounded-lg border border-red-400/60 bg-red-950/50 px-4 py-2 text-sm font-bold">LIVE — REAL EXCHANGE EXECUTION MAY BE ENABLED BY BACKEND SAFETY GATES</div>}</div></div>

   <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
    <Metric label="Readiness" value={readiness.loading?"Loading…":readiness.error?"Unavailable":fmt(readiness.data?.status)}/>
    <Metric label="Runtime" value={fmt(readiness.data?.runtime_mode)}/>
    <Metric label="Trading" value={<span className={live?"text-red-300 font-black":""}>{fmt(mode).toUpperCase()}</span>}/>
    <Metric label="Execution blocked" value={fmt(reconciliation.data?.execution_blocked||safety.data?.trading_halted)}/>
    <Metric label="Worker" value={fmt(reconciliation.data?.active_lease?.worker_id)}/>
   </div>

   <div className="mt-6 grid gap-6 xl:grid-cols-2">
    <DataPanel title="System readiness" state={readiness}>{readiness.data&&<div className="space-y-3">{Object.entries(readiness.data.checks).map(([name,c])=><div key={name} className="rounded-lg border border-slate-800 p-3"><div className="flex justify-between gap-3"><span className="text-sm text-slate-200">{name}</span><span className={c.ready?"text-emerald-300":"text-red-300"}>{c.ready?"READY":"NOT READY"}</span></div><ReasonList reasons={c.reasons}/></div>)}</div>}</DataPanel>
    <DataPanel title="Capabilities" state={capabilities}>{capabilities.data&&<div className="space-y-3">{Object.entries(capabilities.data.capabilities).map(([name,c])=><div key={name} className="rounded-lg border border-slate-800 p-3"><div className="flex justify-between gap-3"><span className="text-sm text-slate-200">{name}</span><span className={c.enabled?"text-emerald-300":"text-slate-500"}>{c.enabled?"ENABLED":"UNAVAILABLE"}</span></div><ReasonList reasons={c.reasons}/></div>)}</div>}</DataPanel>
   </div>

   <div className="mt-6 grid gap-6 xl:grid-cols-3">
    <div className="xl:col-span-2"><DataPanel title="Portfolio exposure" state={exposure}>{exposure.data?<><div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4"><Metric label="Equity" value={fmt(exposure.data.equity)}/><Metric label="Available" value={fmt(exposure.data.available_capital)}/><Metric label="Reserved" value={fmt(exposure.data.reserved_capital)}/><Metric label="Exposure" value={fmt(exposure.data.portfolio_exposure)}/><Metric label="Positions" value={fmt(exposure.data.open_positions)}/><Metric label="Daily realized" value={fmt(exposure.data.daily_realized_pnl)}/><Metric label="Drawdown" value={fmt(exposure.data.total_drawdown)}/><Metric label="Cash" value={fmt(exposure.data.cash_balance)}/></div><div className="mt-4 grid gap-3 md:grid-cols-2"><div className="rounded-lg border border-slate-800 p-3"><div className="mb-2 text-xs uppercase text-slate-500">By symbol</div><pre className="overflow-auto text-xs text-slate-300">{JSON.stringify(exposure.data.symbol_exposure,null,2)}</pre></div><div className="rounded-lg border border-slate-800 p-3"><div className="mb-2 text-xs uppercase text-slate-500">By strategy</div><pre className="overflow-auto text-xs text-slate-300">{JSON.stringify(exposure.data.strategy_exposure,null,2)}</pre></div></div></>:<EmptyState/>}</DataPanel></div>
    <DataPanel title="Active risk limits" state={limits}>{limits.data?<pre className="max-h-[30rem] overflow-auto whitespace-pre-wrap text-xs text-slate-300">{JSON.stringify(limits.data,null,2)}</pre>:<EmptyState/>}</DataPanel>
   </div>

   <div className="mt-6 grid gap-6 xl:grid-cols-2">
    <DataPanel title="Capital allocation" state={allocations}>{!allocations.data?.length?<EmptyState message="No active/recent capital allocations."/>:<div className="space-y-2">{allocations.data.map((a,i)=><div key={String(a.risk_decision_id??i)} className="grid grid-cols-2 gap-2 rounded-lg border border-slate-800 p-3 text-xs md:grid-cols-5"><span>{fmt(a.symbol)}</span><span>{fmt(a.strategy_key)}</span><span>{fmt(a.reserved_notional)}</span><span>{fmt(a.status)}</span><span className="truncate font-mono text-slate-500">{fmt(a.risk_decision_id)}</span></div>)}</div>}</DataPanel>
    <DataPanel title="Reconciliation & worker" state={reconciliation}>{reconciliation.data?<div className="space-y-3 text-sm"><div className="grid grid-cols-2 gap-3"><Metric label="Unresolved severe" value={reconciliation.data.severe_unresolved_count}/><Metric label="Execution blocked" value={fmt(reconciliation.data.execution_blocked)}/></div><div className="rounded-lg border border-slate-800 p-3"><div className="text-xs uppercase text-slate-500">Worker lease</div>{reconciliation.data.active_lease?<div className="mt-2 space-y-1 text-xs"><div>{reconciliation.data.active_lease.bot_id} · {reconciliation.data.active_lease.worker_id}</div><div className="text-slate-500">heartbeat {fmt(reconciliation.data.active_lease.heartbeat_at)}</div><div className="text-slate-500">expires {fmt(reconciliation.data.active_lease.expires_at)}</div></div>:<div className="mt-2 text-amber-300">No active worker lease.</div>}</div><pre className="overflow-auto whitespace-pre-wrap rounded-lg border border-slate-800 p-3 text-xs text-slate-400">{JSON.stringify(reconciliation.data.latest_run??{},null,2)}</pre></div>:<EmptyState/>}</DataPanel>
   </div>

   <div className="mt-6"><Panel title="Trading safety controls"><div className="flex flex-wrap items-start justify-between gap-4"><div><div className={`text-lg font-bold ${safety.data?.trading_halted?"text-red-300":"text-emerald-300"}`}>{safety.loading?"Loading safety state…":safety.error?"Safety status unavailable":safety.data?.trading_halted?"NEW ENTRY EXECUTION HALTED":"New entry execution allowed by current safety state"}</div><div className="mt-2 text-sm text-slate-500">Bot {BOT_ID}: {botControl?.active?`${botControl.mode} (${botControl.reason_code??"no reason"})`:"active / not halted"}</div>{actionMessage&&<div className="mt-2 text-sm text-amber-200">{actionMessage}</div>}</div><div className="flex flex-wrap gap-2"><ConfirmAction label="Global kill switch" title="Halt all new trading?" description="This sends an audited global halt command to the backend. It does not cancel reconciliation or bypass protective-exit recovery." danger disabled={globalActive} onConfirm={()=>doCommand("/v1/safety/halt",{idempotency_key:idempotency(),scope:"global",mode:"halted",reason_code:"operator_web_kill_switch",operator_id:"web-operator"})}/><ConfirmAction label="Resume global" title="Resume global trading eligibility?" description="The backend will reject this if severe circuit/reconciliation conditions are not safe to resume. Confirmation does not override server-side safety gates." disabled={!globalActive} onConfirm={()=>doCommand("/v1/safety/resume",{idempotency_key:idempotency(),scope:"global",operator_id:"web-operator",acknowledgement:"Operator reviewed active blockers and requests safe resume"})}/><ConfirmAction label="Pause bot" title={`Pause ${BOT_ID}?`} description="Pauses new entries for this bot only. The backend remains authoritative and reconciliation/protective recovery continues." danger disabled={!!botControl?.active} onConfirm={()=>doCommand("/v1/safety/halt",{idempotency_key:idempotency(),scope:"bot",scope_key:BOT_ID,mode:"paused",reason_code:"operator_web_bot_pause",operator_id:"web-operator"})}/><ConfirmAction label="Resume bot" title={`Resume ${BOT_ID}?`} description="Requests a safe backend resume for this bot. Open severe safety conditions can still block execution." disabled={!botControl?.active} onConfirm={()=>doCommand("/v1/safety/resume",{idempotency_key:idempotency(),scope:"bot",scope_key:BOT_ID,operator_id:"web-operator",acknowledgement:"Operator reviewed bot safety state and requests safe resume"})}/></div></div>{safety.data?.blockers?.length?<div className="mt-4 space-y-2">{safety.data.blockers.map((b,i)=><div key={`${b.code}-${i}`} className="rounded border border-red-500/20 bg-red-500/5 p-2 text-xs text-red-200">{b.code} · {b.scope}{b.scope_key?`:${b.scope_key}`:""}{b.reason_code?` · ${b.reason_code}`:""}</div>)}</div>:null}</Panel></div>

   <div className="mt-6 grid gap-6 xl:grid-cols-2">
    <DataPanel title="Circuit breakers" state={circuits}>{!circuits.data?.length?<EmptyState message="No circuit breaker state returned."/>:<div className="space-y-2">{circuits.data.map(c=><div key={c.breaker} className={`rounded-lg border p-3 ${c.open?"border-red-500/40 bg-red-500/5":"border-slate-800"}`}><div className="flex justify-between"><span className="font-medium">{c.breaker}</span><span className={c.open?"text-red-300":"text-emerald-300"}>{c.open?"OPEN":"CLOSED"}</span></div><div className="mt-1 text-xs text-slate-500">failures {c.failure_count}/{c.threshold} · recovery observed {String(c.recovery_observed)} · {fmt(c.reason_code)}</div></div>)}</div>}</DataPanel>
    <DataPanel title="Exchange connection / credential metadata" state={credentials}>{credentials.error?<ErrorState message={`${credentials.error}. Sign in with an admin-authorized account to view security-safe credential metadata.`}/>:!credentials.data?.length?<EmptyState message="No stored credential metadata is available."/>:<div className="space-y-2">{credentials.data.map(c=><div key={c.id} className="rounded-lg border border-slate-800 p-3"><div className="flex justify-between gap-3"><span className="font-medium text-cyan-200">{c.exchange_id}</span><span className={c.environment==="live"?"font-black text-red-300":"text-amber-300"}>{c.environment.toUpperCase()}</span></div><div className="mt-2 font-mono text-xs text-slate-400">{c.api_key_fingerprint}</div><div className="mt-1 text-xs text-slate-500">validation: {c.validation_status} · {fmt(c.validated_at)}</div></div>)}</div>}</DataPanel>
   </div>

   <div className="mt-6 grid gap-6 xl:grid-cols-2">
    <DataPanel title="Operational incidents" state={incidents}>{!incidents.data?.length?<EmptyState message="No operational incidents."/>:<div className="space-y-2">{incidents.data.map(x=><div key={x.id} className="rounded-lg border border-slate-800 p-3"><div className="flex justify-between gap-2"><span className="font-medium">{x.title}</span><span className="text-xs uppercase text-slate-400">{x.severity}</span></div><div className="mt-1 text-xs text-slate-500">{x.category} · {x.status} · occurrences {x.occurrence_count} · {fmt(x.last_seen_at)}</div></div>)}</div>}</DataPanel>
    <DataPanel title="Recent alerts" state={alerts}>{!alerts.data?.length?<EmptyState message="No alert events."/>:<div className="space-y-2">{alerts.data.map(x=><div key={x.id} className="rounded-lg border border-slate-800 p-3"><div className="flex justify-between gap-2"><span className="text-sm">{x.message}</span><span className="text-xs uppercase text-slate-400">{x.severity}</span></div><div className="mt-1 text-xs text-slate-500">{x.category} · {fmt(x.emitted_at)}</div></div>)}</div>}</DataPanel>
   </div>

   <div className="mt-6 grid gap-6 xl:grid-cols-2">
    <DataPanel title="Security audit / recent critical actions" state={audits}>{audits.error?<ErrorState message={`${audits.error}. Admin authorization is required for security audit events.`}/>:!audits.data?.length?<EmptyState message="No security audit events are visible to this session."/>:<div className="space-y-2">{audits.data.slice(0,30).map(a=><div key={a.id} className="rounded-lg border border-slate-800 p-3 text-xs"><div className="flex justify-between gap-2"><span className="font-medium text-cyan-200">{a.action}</span><span className={a.outcome==="success"?"text-emerald-300":"text-amber-300"}>{a.outcome}</span></div><div className="mt-1 text-slate-500">{fmt(a.target_type)} · {fmt(a.target_id)} · {fmt(a.created_at)}</div></div>)}</div>}</DataPanel>
    <Panel title="Critical event digest">{!criticalEvents.length?<EmptyState message="No critical/error incident or alert events in the current result window."/>:<div className="space-y-2">{criticalEvents.map((e:any,i)=><div key={e.id??i} className="rounded-lg border border-red-500/20 bg-red-500/5 p-3 text-xs"><div className="font-medium text-red-200">{e.title??e.message}</div><div className="mt-1 text-slate-500">{e.category} · {e.severity} · {fmt(e.last_seen_at??e.emitted_at)}</div></div>)}</div>}</Panel>
   </div>
 </PageShell>
}
