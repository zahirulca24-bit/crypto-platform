"use client"
import { useState } from "react"
import { api, formatApiError } from "@/lib/api"
import { useApiData } from "@/lib/use-api"
import { EmptyState, ErrorState, LoadingState } from "@/components/data-state"
import { Metric, PageShell, Panel, fmt } from "@/components/page-shell"
type Selection={run_id:string;exchange:string;scanned_count:number;eligible_count:number;selected_count:number;rejected_count:number;selected_symbols:string[];results:Array<Record<string,unknown>>}
export default function SymbolSelectionPage(){
 const [run,setRun]=useState<Selection|null>(null); const [running,setRunning]=useState(false); const [actionError,setActionError]=useState<string|null>(null)
 const recent=useApiData(()=>api.get<Record<string,unknown>[]>("/v1/research/observations",{event_type:"symbol_selection",limit:50}),[])
 async function execute(){setRunning(true);setActionError(null);try{setRun(await api.post<Selection>("/v1/market-data/symbol-selection",{exchange:"binance",quote_currency:"USDT",max_symbols:10}))}catch(e){setActionError(formatApiError(e))}finally{setRunning(false)}}
 return <PageShell title="Symbol Selection" subtitle="Runs the existing backend selector and shows persisted research context. Selection does not submit orders or bypass risk.">
  <div className="mb-5 flex items-center gap-3"><button disabled={running} onClick={()=>void execute()} className="rounded-lg bg-cyan-600 px-4 py-2 text-sm font-medium hover:bg-cyan-500 disabled:opacity-50">{running?"Running scan...":"Run Selection"}</button><span className="text-xs text-slate-500">binance · USDT · max 10</span></div>
  {actionError&&<ErrorState message={actionError}/>} {run&&<div className="mb-6 grid gap-4 md:grid-cols-4"><Metric label="Scanned" value={run.scanned_count}/><Metric label="Eligible" value={run.eligible_count}/><Metric label="Selected" value={run.selected_count}/><Metric label="Rejected" value={run.rejected_count}/></div>}
  {run&&<Panel title="Current selection results">{!run.results.length?<EmptyState/>:<div className="space-y-2">{run.results.map((r,i)=><div key={i} className="rounded border border-slate-800 p-3 text-sm"><div className="flex justify-between"><span className="font-medium text-cyan-200">{fmt(r.symbol)}</span><span>{r.selected?"selected":"rejected"}</span></div><div className="mt-1 text-xs text-slate-500">Score: {fmt(r.score)} · reasons: {fmt(r.rejection_reasons)}</div></div>)}</div>}</Panel>}
  <div className="mt-6"><Panel title="Persisted selection research observations">{recent.loading?<LoadingState/>:recent.error?<ErrorState message={recent.error}/>:!recent.data?.length?<EmptyState message="No selection observations are available yet."/>:<div className="space-y-2">{recent.data.map((o,i)=><div key={String(o.event_id??i)} className="rounded border border-slate-800 p-3 text-xs text-slate-400">{fmt(o.symbol)} · {fmt(o.selection_status)} · {fmt(o.selection_reasons)}</div>)}</div>}</Panel></div>
 </PageShell>
}
