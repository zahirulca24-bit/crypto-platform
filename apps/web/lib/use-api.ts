"use client"
import { useCallback, useEffect, useState } from "react"
import { formatApiError } from "./api"

export function useApiData<T>(loader: () => Promise<T>, deps: readonly unknown[] = []) {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const reload = useCallback(async () => {
    setLoading(true); setError(null)
    try { setData(await loader()) } catch (e) { setError(formatApiError(e)) } finally { setLoading(false) }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  useEffect(() => { void reload() }, [reload])
  return { data, loading, error, reload }
}
