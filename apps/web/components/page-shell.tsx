import AppLayout from "./app-layout"
export function PageShell({title, subtitle, children}:{title:string; subtitle:string; children:React.ReactNode}) {
  return <AppLayout><div className="mb-6"><div className="text-xs uppercase tracking-[.24em] text-cyan-400">Adaptive Crypto Platform</div><h1 className="mt-1 text-2xl font-semibold md:text-3xl">{title}</h1><p className="mt-2 max-w-3xl text-sm text-slate-400">{subtitle}</p></div>{children}</AppLayout>
}
export function Metric({label,value}:{label:string;value:React.ReactNode}) {return <div className="rounded-xl border border-slate-700/60 bg-slate-900/60 p-4 backdrop-blur"><div className="text-xs uppercase tracking-wider text-slate-500">{label}</div><div className="mt-2 text-xl font-semibold text-slate-100">{value ?? "—"}</div></div>}
export function Panel({title,children}:{title:string;children:React.ReactNode}) {return <section className="rounded-xl border border-slate-700/60 bg-slate-900/55 p-4 backdrop-blur"><h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-slate-300">{title}</h2>{children}</section>}
export function fmt(value: unknown) { if (value === null || value === undefined || value === "") return "—"; if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(4); if (typeof value === "object") return JSON.stringify(value); return String(value) }
