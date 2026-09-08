import { AlertTriangle, Database, Loader2 } from "lucide-react"

export function LoadingState({ label = "Loading from backend..." }: { label?: string }) {
  return <div className="rounded-xl border border-cyan-500/20 bg-slate-900/60 p-8 text-center text-slate-400"><Loader2 className="mx-auto mb-3 h-6 w-6 animate-spin text-cyan-400" />{label}</div>
}
export function ErrorState({ message }: { message: string }) {
  return <div className="rounded-xl border border-red-500/30 bg-red-950/20 p-6 text-red-200"><AlertTriangle className="mb-2 h-5 w-5" />{message}</div>
}
export function EmptyState({ message = "No persisted data is available yet." }: { message?: string }) {
  return <div className="rounded-xl border border-slate-700/60 bg-slate-900/50 p-8 text-center text-slate-400"><Database className="mx-auto mb-3 h-6 w-6 text-slate-500" />{message}</div>
}
export function JsonPreview({ value }: { value: unknown }) {
  return <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-black/30 p-3 text-xs text-slate-300">{JSON.stringify(value, null, 2)}</pre>
}
