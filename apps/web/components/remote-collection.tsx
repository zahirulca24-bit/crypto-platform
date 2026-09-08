"use client"
import { useMemo } from "react"
import { api } from "@/lib/api"
import { useApiData } from "@/lib/use-api"
import { EmptyState, ErrorState, LoadingState } from "@/components/data-state"
import { PageShell, Panel, fmt } from "@/components/page-shell"

export type Column = { key: string; label: string }
export function RemoteCollectionPage({title, subtitle, endpoint, columns, emptyMessage}:{title:string;subtitle:string;endpoint:string;columns:Column[];emptyMessage:string}) {
  const result = useApiData(() => api.get<Record<string, unknown>[]>(endpoint), [endpoint])
  const rows = useMemo(() => Array.isArray(result.data) ? result.data : [], [result.data])
  return <PageShell title={title} subtitle={subtitle}>
    <Panel title={`${title} data`}>
      {result.loading ? <LoadingState/> : result.error ? <ErrorState message={result.error}/> : !rows.length ? <EmptyState message={emptyMessage}/> : <div className="overflow-x-auto"><table className="w-full min-w-[760px] text-sm"><thead><tr className="text-left text-xs uppercase tracking-wider text-slate-500">{columns.map(c=><th key={c.key} className="p-2">{c.label}</th>)}</tr></thead><tbody>{rows.map((row,i)=><tr key={String(row.id ?? i)} className="border-t border-slate-800/80 hover:bg-slate-800/30">{columns.map(c=><td key={c.key} className="max-w-xs p-2 text-slate-300">{fmt(row[c.key])}</td>)}</tr>)}</tbody></table></div>}
    </Panel>
  </PageShell>
}
