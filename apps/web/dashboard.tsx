"use client"
import { api } from "@/lib/api"
import { useApiData } from "@/lib/use-api"
import { EmptyState, ErrorState, JsonPreview, LoadingState } from "@/components/data-state"
import { Metric, PageShell, Panel, fmt } from "@/components/page-shell"

type DashboardSummary = { portfolio?: Record<string, unknown>; risk_status?: Record<string, unknown>; bot_status?: Record<string, unknown> }
type Order = { id:string; symbol:string; side:string; status:string; price:string|number; quantity:string|number; created_at:string }
export default function Dashboard() {
  const summary = useApiData(() => api.get<DashboardSummary>("/v1/dashboard/summary"), [])
  const trades = useApiData(() => api.get<Order[]>("/v1/dashboard/recent-trades"), [])
  const system = useApiData(() => api.get<Record<string, unknown>>("/v1/dashboard/system-status"), [])
  return <PageShell title="Trading Dashboard" subtitle="Live local state from the current Phase-2 backend. No synthetic trading metrics are shown when backend data is unavailable.">
    {summary.loading ? <LoadingState/> : summary.error ? <ErrorState message={summary.error}/> : <>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
        <Metric label="Open Positions" value={fmt(summary.data?.portfolio?.open_positions)}/><Metric label="Realized PnL" value={fmt(summary.data?.portfolio?.realized_pnl)}/><Metric label="Unrealized PnL" value={fmt(summary.data?.portfolio?.unrealized_pnl)}/><Metric label="Net PnL" value={fmt(summary.data?.portfolio?.net_pnl)}/><Metric label="Bot State" value={fmt(system.data?.bot_mode ?? summary.data?.bot_status?.state)}/>
      </div>
      <div className="mt-6 grid gap-6 xl:grid-cols-3">
        <div className="xl:col-span-2"><Panel title="Recent Orders / Trades">{trades.loading ? <LoadingState/> : trades.error ? <ErrorState message={trades.error}/> : !trades.data?.length ? <EmptyState message="No orders have been persisted yet."/> : <div className="overflow-x-auto"><table className="w-full text-sm"><thead className="text-left text-slate-500"><tr><th className="p-2">Symbol</th><th>Side</th><th>Status</th><th>Price</th><th>Quantity</th><th>Time</th></tr></thead><tbody>{trades.data.slice(0,12).map(t=><tr key={t.id} className="border-t border-slate-800"><td className="p-2 font-medium text-cyan-200">{t.symbol}</td><td>{t.side}</td><td>{t.status}</td><td>{fmt(t.price)}</td><td>{fmt(t.quantity)}</td><td className="text-xs text-slate-500">{new Date(t.created_at).toLocaleString()}</td></tr>)}</tbody></table></div>}</Panel></div>
        <Panel title="Backend Risk / Runtime Context"><JsonPreview value={{risk_status: summary.data?.risk_status, bot_status: summary.data?.bot_status, system: system.data}}/></Panel>
      </div>
    </>}
  </PageShell>
}
