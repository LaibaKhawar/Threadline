// Same-origin API client. The session cookie is HttpOnly; unsafe requests echo the CSRF cookie in a header.

export class ApiError extends Error {
  status: number
  detail: unknown
  requestId?: string
  constructor(status: number, detail: unknown, requestId?: string) {
    super(typeof detail === 'string' ? detail : `Request failed (${status})`)
    this.status = status
    this.detail = detail
    this.requestId = requestId
  }
}

function csrfToken(): string | undefined {
  if (typeof document === 'undefined') return undefined
  const m = document.cookie.match(/(?:^|;\s*)tl_csrf=([^;]+)/)
  return m ? decodeURIComponent(m[1]) : undefined
}

type Method = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'

export async function api<T>(path: string, opts: { method?: Method; body?: unknown; form?: FormData; signal?: AbortSignal } = {}): Promise<T> {
  const method = opts.method ?? 'GET'
  const headers: Record<string, string> = {}
  if (method !== 'GET') {
    const t = csrfToken()
    if (t) headers['x-csrf-token'] = t
  }
  let body: BodyInit | undefined
  if (opts.form) body = opts.form
  else if (opts.body !== undefined) {
    headers['content-type'] = 'application/json'
    body = JSON.stringify(opts.body)
  }
  const res = await fetch(path, { method, headers, body, credentials: 'same-origin', signal: opts.signal })
  if (res.status === 204) return undefined as T
  const ct = res.headers.get('content-type') ?? ''
  const data = ct.includes('application/json') ? await res.json() : await res.text()
  if (!res.ok) {
    const detail = typeof data === 'object' && data && 'detail' in data ? (data as { detail: unknown }).detail : data
    throw new ApiError(res.status, detail, typeof data === 'object' && data ? (data as { request_id?: string }).request_id : undefined)
  }
  return data as T
}

export const get = <T,>(path: string) => api<T>(path)
export const post = <T,>(path: string, body?: unknown) => api<T>(path, { method: 'POST', body })
export const put = <T,>(path: string, body?: unknown) => api<T>(path, { method: 'PUT', body })
export const patch = <T,>(path: string, body?: unknown) => api<T>(path, { method: 'PATCH', body })
export const del = <T,>(path: string) => api<T>(path, { method: 'DELETE' })

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    if (typeof e.detail === 'string') return e.detail
    if (Array.isArray(e.detail)) return e.detail.map((d: { msg?: string }) => d.msg).join('; ')
    return e.message
  }
  return e instanceof Error ? e.message : 'Unexpected error'
}
