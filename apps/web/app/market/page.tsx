"use client"
import { useState } from "react"
import { api } from "@/lib/api"
import { useApiData } from "@/lib/use-api"
import { EmptyState, ErrorState, LoadingState } from "@/components/data-state"
import { Metric, PageShell, Panel, fmt } from "@/components/page-shell"
type Candle={id:string;open_time:string;open:string;high:string;low:string;close:string;volume:string;is_closed:boolean}
export default function MarketPage(){
 const [symbol,setSymbol]=useState("BTC/USDT"); const [timeframe,setTimeframe]=useState("1h")
 const candles=useApiData(()=>api.get<Candle[]>("/v1/market-data/ohlcv",{exchange:"binance",symbol,timeframe,limit:100}),[symbol,timeframe])
 const latest=candles.data?.at(-1)
 return <PageShell title="Market" subtitle="Persisted closed OHLCV market data from PostgreSQL. This screen does not fetch a live exchange feed itself.">
  <div className="mb-5 flex flex-wrap gap-3"><input value={symbol} onChange={e=>setSymbol(e.target.value)} className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm"/><select value={timeframe} onChange={e=>setTimeframe(e.target.value)} className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm"><option value="15m">15m</option><option value="1h">1h</option><option value="4h">4h</option><option value="1d">1d</option></select></div>
  {candles.loading?<LoadingState/>:candles.error?<ErrorState message={candles.error}/>:!candles.data?.length?<EmptyState message={`No persisted candles for ${symbol} ${timeframe}. Use the backend market-data sync workflow to populate data.`}/>:<><div className="grid gap-4 md:grid-cols-5"><Metric label="Latest Close" value={fmt(latest?.close)}/><Metric label="Open" value={fmt(latest?.open)}/><Metric label="High" value={fmt(latest?.high)}/><Metric label="Low" value={fmt(latest?.low)}/><Metric label="Volume" value={fmt(latest?.volume)}/></div><div className="mt-6"><Panel title="Recent closed candles"><div className="overflow-x-auto"><table className="w-full text-sm"><thead className="text-left text-slate-500"><tr><th className="p-2">Time</th><th>Open</th><th>High</th><th>Low</th><th>Close</th><th>Volume</th></tr></thead><tbody>{candles.data.slice(-30).reverse().map(c=><tr key={c.id} className="border-t border-slate-800"><td className="p-2 text-xs">{new Date(c.open_time).toLocaleString()}</td><td>{c.open}</td><td>{c.high}</td><td>{c.low}</td><td className="text-cyan-200">{c.close}</td><td>{c.volume}</td></tr>)}</tbody></table></div></Panel></div></>}
 </PageShell>
}
