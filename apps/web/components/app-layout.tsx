"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { useEffect, useRef, useState } from "react"
import { Activity, BarChart3, Bot, BookOpen, Brain, FlaskConical, LayoutDashboard, LineChart, ListOrdered, Menu, Settings, Shield, Sparkles, TestTube2, X } from "lucide-react"
import { api } from "@/lib/api"

const sections = [
  { label: "Trading", items: [
    ["Dashboard", "/", LayoutDashboard], ["Market", "/market", LineChart], ["Symbol Selection", "/symbol-selection", Sparkles],
    ["Strategies", "/strategies", Brain], ["Bots", "/bots", Bot], ["Orders", "/orders", ListOrdered],
    ["Positions", "/positions", BarChart3], ["Performance", "/performance", Activity], ["Logs", "/logs", BookOpen],
  ]},
  { label: "R&D / Learning Intelligence", items: [
    ["Research Overview", "/research", FlaskConical], ["Market Regimes", "/market-regimes", Activity],
    ["Strategy Lab", "/strategy-lab", Brain], ["Experiments", "/experiments", TestTube2],
    ["Learning Journal", "/learning-journal", BookOpen], ["Candidate Strategies", "/candidate-strategies", Shield],
  ]},
  { label: "System", items: [["System Status", "/system-status", Activity], ["Settings", "/settings", Settings]] },
] as const

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const [open, setOpen] = useState(true)
  const [apiOk, setApiOk] = useState<boolean | null>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    let alive = true
    api.get<{status:string}>("/health").then(() => alive && setApiOk(true)).catch(() => alive && setApiOk(false))
    return () => { alive = false }
  }, [pathname])

  useEffect(() => {
    const canvas = canvasRef.current; if (!canvas) return
    const ctx = canvas.getContext("2d"); if (!ctx) return
    const resize = () => { canvas.width = innerWidth; canvas.height = innerHeight }; resize(); addEventListener("resize", resize)
    const particles = Array.from({length: 55}, () => ({x:Math.random()*innerWidth,y:Math.random()*innerHeight,r:Math.random()*1.8+0.5,dx:(Math.random()-.5)*.25,dy:(Math.random()-.5)*.25}))
    let frame = 0
    const draw = () => { ctx.clearRect(0,0,canvas.width,canvas.height); ctx.fillStyle="rgba(34,211,238,.25)"; for(const p of particles){p.x=(p.x+p.dx+canvas.width)%canvas.width;p.y=(p.y+p.dy+canvas.height)%canvas.height;ctx.beginPath();ctx.arc(p.x,p.y,p.r,0,Math.PI*2);ctx.fill()} frame=requestAnimationFrame(draw) }; draw()
    return () => { cancelAnimationFrame(frame); removeEventListener("resize", resize) }
  }, [])

  return <div className="min-h-screen bg-gradient-to-br from-black via-slate-950 to-slate-900 text-slate-100">
    <canvas ref={canvasRef} className="pointer-events-none fixed inset-0 h-full w-full opacity-60" />
    <aside className={`fixed inset-y-0 left-0 z-40 border-r border-cyan-500/15 bg-slate-950/90 backdrop-blur-xl transition-all ${open ? "w-72" : "w-20"}`}>
      <div className="flex h-16 items-center justify-between border-b border-slate-800 px-4">
        <Link href="/" className="flex items-center gap-3"><div className="rounded-lg border border-cyan-400/30 bg-cyan-400/10 p-2"><Sparkles className="h-5 w-5 text-cyan-300" /></div>{open && <div><div className="font-semibold tracking-wide">Crypto Platform</div><div className="text-[10px] text-cyan-300">Phase 3 Intelligence</div></div>}</Link>
        <button onClick={() => setOpen(!open)} className="rounded p-1 text-slate-400 hover:bg-slate-800">{open ? <X className="h-4 w-4"/> : <Menu className="h-4 w-4"/>}</button>
      </div>
      <nav className="h-[calc(100vh-8rem)] overflow-y-auto p-3">
        {sections.map(section => <div key={section.label} className="mb-5">{open && <div className="mb-2 px-3 text-[10px] uppercase tracking-[.2em] text-slate-500">{section.label}</div>}
          <div className="space-y-1">{section.items.map(([label, href, Icon]) => { const active = pathname === href; return <Link key={href} href={href} title={label} className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition ${active ? "border border-cyan-500/30 bg-cyan-500/10 text-cyan-200" : "text-slate-400 hover:bg-slate-900 hover:text-slate-100"}`}><Icon className="h-4 w-4 shrink-0"/>{open && label}</Link>})}</div>
        </div>)}
      </nav>
      <div className="absolute bottom-0 left-0 right-0 border-t border-slate-800 p-3"><div className="flex items-center gap-2 rounded-lg bg-slate-900/70 px-3 py-2 text-xs"><span className={`h-2 w-2 rounded-full ${apiOk === true ? "bg-emerald-400" : apiOk === false ? "bg-red-400" : "bg-amber-400"}`} />{open && (apiOk === true ? "Backend connected" : apiOk === false ? "Backend unavailable" : "Checking backend")}</div></div>
    </aside>
    <main className={`relative z-10 min-h-screen transition-all ${open ? "pl-72" : "pl-20"}`}><div className="mx-auto max-w-[1600px] p-4 md:p-7">{children}</div></main>
  </div>
}
