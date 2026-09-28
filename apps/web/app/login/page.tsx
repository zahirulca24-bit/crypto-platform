"use client"
import { FormEvent, useEffect, useState } from "react"
import { api, getSessionToken, setSessionToken, formatApiError } from "@/lib/api"
import { useRouter } from "next/navigation"

type TokenResponse={access_token:string;token_type:string;expires_in:number}

export default function LoginPage() {
  const router = useRouter()
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [message, setMessage] = useState<string|null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (getSessionToken()) {
      router.replace("/dashboard")
    }
  }, [router])

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setMessage(null)
    try {
      const t = await api.post<TokenResponse>("/v1/auth/login", { email, password })
      setSessionToken(t.access_token)
      router.replace("/dashboard")
    } catch(err) {
      setMessage(formatApiError(err))
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-black px-4 font-sans text-slate-100">
      <div className="w-full max-w-md rounded-2xl border border-slate-800 bg-slate-900/50 p-8 shadow-2xl backdrop-blur-xl">
        <div className="mb-8 text-center">
          <h1 className="text-2xl font-bold tracking-wider text-cyan-400">NEXUS</h1>
          <p className="mt-2 text-sm text-slate-400">Operator Authentication</p>
        </div>
        <form onSubmit={submit} className="space-y-5">
          <label className="block">
            <span className="mb-2 block text-sm font-medium text-slate-300">Email</span>
            <input value={email} onChange={e=>setEmail(e.target.value)} type="email" autoComplete="username" required className="w-full rounded-lg border border-slate-700 bg-black/50 px-4 py-2.5 text-slate-100 placeholder-slate-600 focus:border-cyan-500 focus:outline-none focus:ring-1 focus:ring-cyan-500" placeholder="admin@example.com"/>
          </label>
          <label className="block">
            <span className="mb-2 block text-sm font-medium text-slate-300">Password</span>
            <input value={password} onChange={e=>setPassword(e.target.value)} type="password" autoComplete="current-password" required className="w-full rounded-lg border border-slate-700 bg-black/50 px-4 py-2.5 text-slate-100 placeholder-slate-600 focus:border-cyan-500 focus:outline-none focus:ring-1 focus:ring-cyan-500" placeholder="********"/>
          </label>
          <button disabled={busy} className="mt-6 w-full rounded-lg bg-cyan-500 px-4 py-2.5 font-semibold text-black transition-colors hover:bg-cyan-400 disabled:opacity-50">
            {busy ? "Authenticating..." : "Sign In"}
          </button>
        </form>
        {message && <div className="mt-6 rounded-lg bg-red-500/10 p-3 text-center text-sm text-red-400">{message}</div>}
      </div>
    </div>
  )
}
