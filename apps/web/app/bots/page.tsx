"use client"
import { api } from "@/lib/api"
import { useApiData } from "@/lib/use-api"
import { EmptyState, ErrorState, LoadingState } from "@/components/data-state"
import { Metric, PageShell, Panel, fmt } from "@/components/page-shell"
export default function BotsPage(){
 const state=useApiData(()=>api.get<Record<string,unknown>>("/v1/bot/state"),[])
 const activity=useApiData(()=>api.get<Record<string,unknown>[]>("/v1/dashboard/bot-activity"),[])
 return <PageShell title="Bots" subtitle="Read-only view of the Phase-2 bot runtime. Runtime commands are intentionally not auto-fired by this dashboard.">
  {state.loading?<LoadingState/>:state.error?<ErrorState message={state.error}/>:<div className="grid gap-4 md:grid-cols-4"><Metric label="Bot ID" value={fmt(state.data?.bot_id)}/><Metric label="Status" value={fmt(state.data?.status)}/><Metric label="Supervisor" value={fmt(state.data?.supervisor_id)}/><Metric label="Heartbeat" value={fmt(state.data?.heartbeat_at)}/></div>}
  <div className="mt-6"><Panel title="Bot activity">{activity.loading?<LoadingState/>:activity.error?<ErrorState message={activity.error}/>:!activity.data?.length?<EmptyState message="No bot runtime events are available."/>:<div className="space-y-2">{activity.data.slice(0,30).map((e,i)=><div key={String(e.id??i)} className="rounded border border-slate-800 p-3 text-sm"><div className="font-medium text-cyan-200">{fmt(e.event_type)}</div><div className="mt-1 text-xs text-slate-500">{fmt(e.created_at)}</div><div className="mt-2 break-all text-xs text-slate-400">{fmt(e.payload)}</div></div>)}</div>}</Panel></div>
 </PageShell>
}
