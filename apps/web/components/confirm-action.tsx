"use client"
import { useState } from "react"
import { AlertTriangle } from "lucide-react"

export function ConfirmAction({label, title, description, danger=false, disabled=false, onConfirm}:{label:string;title:string;description:string;danger?:boolean;disabled?:boolean;onConfirm:()=>Promise<void>}) {
  const [open,setOpen]=useState(false); const [busy,setBusy]=useState(false)
  const act=async()=>{setBusy(true);try{await onConfirm();setOpen(false)}catch{/* caller surfaces the backend-safe error state */}finally{setBusy(false)}}
  return <>
    <button disabled={disabled} onClick={()=>setOpen(true)} className={`rounded-lg border px-3 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-40 ${danger?"border-red-500/40 bg-red-500/10 text-red-200 hover:bg-red-500/20":"border-cyan-500/30 bg-cyan-500/10 text-cyan-200 hover:bg-cyan-500/20"}`}>{label}</button>
    {open&&<div className="fixed inset-0 z-[100] grid place-items-center bg-black/75 p-4" role="dialog" aria-modal="true"><div className="w-full max-w-lg rounded-2xl border border-slate-700 bg-slate-950 p-5 shadow-2xl"><div className="flex gap-3"><AlertTriangle className={`mt-0.5 h-5 w-5 ${danger?"text-red-400":"text-amber-400"}`}/><div><h3 className="font-semibold text-slate-100">{title}</h3><p className="mt-2 text-sm leading-6 text-slate-400">{description}</p></div></div><div className="mt-5 flex justify-end gap-2"><button onClick={()=>setOpen(false)} disabled={busy} className="rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-300">Cancel</button><button onClick={()=>void act()} disabled={busy} className={`rounded-lg px-3 py-2 text-sm font-semibold ${danger?"bg-red-600 text-white":"bg-cyan-500 text-slate-950"}`}>{busy?"Applying…":"Confirm"}</button></div></div></div>}
  </>
}
