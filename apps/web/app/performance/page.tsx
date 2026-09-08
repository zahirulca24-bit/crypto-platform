"use client"
import { api } from "@/lib/api"
import { useApiData } from "@/lib/use-api"
import { EmptyState, ErrorState, LoadingState } from "@/components/data-state"
import { Metric, PageShell, Panel, fmt } from "@/components/page-shell"
export default function PerformancePage(){
 const portfolio=useApiData(()=>api.get<Record<string,unknown>>("/v1/portfolio/summary"),[])
 const analytics=useApiData(()=>api.get<Record<string,unknown>[]>("/v1/research/analytics/performance"),[])
 return <PageShell title="Performance" subtitle="Portfolio state from Phase 2 plus deterministic Phase-3 learning analytics when completed outcomes exist.">
  {portfolio.loading?<LoadingState/>:portfolio.error?<ErrorState message={portfolio.error}/>:<div className="grid gap-4 md:grid-cols-5"><Metric label="Open Positions" value={fmt(portfolio.data?.open_positions)}/><Metric label="Realized PnL" value={fmt(portfolio.data?.realized_pnl)}/><Metric label="Unrealized PnL" value={fmt(portfolio.data?.unrealized_pnl)}/><Metric label="Fees" value={fmt(portfolio.data?.fees)}/><Metric label="Net PnL" value={fmt(portfolio.data?.net_pnl)}/></div>}
  <div className="mt-6"><Panel title="Learning analytics">{analytics.loading?<LoadingState/>:analytics.error?<ErrorState message={analytics.error}/>:!analytics.data?.length?<EmptyState message="No completed trade-outcome analytics are available yet."/>:<div className="grid gap-3 lg:grid-cols-2">{analytics.data.map((r,i)=><div key={i} className="rounded-lg border border-slate-800 bg-black/20 p-3 text-xs text-slate-300"><pre className="whitespace-pre-wrap">{JSON.stringify(r,null,2)}</pre></div>)}</div>}</Panel></div>
 </PageShell>
}
