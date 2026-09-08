export const API_BASE_URL = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "")

export class ApiError extends Error {
  status: number
  detail?: unknown
  constructor(message: string, status = 0, detail?: unknown) {
    super(message)
    this.name = "ApiError"
    this.status = status
    this.detail = detail
  }
}

export type QueryValue = string | number | boolean | null | undefined

export function withQuery(path: string, params: Record<string, QueryValue> = {}) {
  const url = new URL(`${API_BASE_URL}${path}`)
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") url.searchParams.set(key, String(value))
  }
  return url.toString()
}

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const url = path.startsWith("http") ? path : `${API_BASE_URL}${path}`
  let response: Response
  try {
    response = await fetch(url, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
      cache: "no-store",
    })
  } catch (error) {
    throw new ApiError(`Backend unavailable at ${API_BASE_URL}`, 0, error)
  }
  const text = await response.text()
  let body: unknown = null
  if (text) {
    try { body = JSON.parse(text) } catch { body = text }
  }
  if (!response.ok) {
    const detail = typeof body === "object" && body && "detail" in body ? (body as { detail?: unknown }).detail : body
    throw new ApiError(`API request failed (${response.status})`, response.status, detail)
  }
  return body as T
}

export const api = {
  get: <T>(path: string, params?: Record<string, QueryValue>) => apiRequest<T>(withQuery(path, params)),
  post: <T>(path: string, body?: unknown) => apiRequest<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) }),
  patch: <T>(path: string, body?: unknown) => apiRequest<T>(path, { method: "PATCH", body: body === undefined ? undefined : JSON.stringify(body) }),
}

export function formatApiError(error: unknown) {
  if (error instanceof ApiError) {
    const detail = typeof error.detail === "string" ? `: ${error.detail}` : ""
    return `${error.message}${detail}`
  }
  return error instanceof Error ? error.message : "Unknown API error"
}
