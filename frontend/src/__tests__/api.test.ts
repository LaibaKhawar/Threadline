import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError, api, errorMessage } from '@/lib/api'

afterEach(() => vi.restoreAllMocks())

describe('api client', () => {
  it('sends the CSRF token on unsafe methods only', async () => {
    document.cookie = 'tl_csrf=tok123'
    const f = vi.fn().mockImplementation(async () => new Response('{}', { headers: { 'content-type': 'application/json' } }))
    global.fetch = f as typeof fetch
    await api('/api/x')
    await api('/api/x', { method: 'POST', body: { a: 1 } })
    expect(f.mock.calls[0][1].headers['x-csrf-token']).toBeUndefined()
    expect(f.mock.calls[1][1].headers['x-csrf-token']).toBe('tok123')
    expect(f.mock.calls[1][1].credentials).toBe('same-origin')
  })
  it('turns error responses into ApiError with detail', async () => {
    global.fetch = vi.fn().mockImplementation(async () => new Response(JSON.stringify({ detail: 'file type .exe is not supported', request_id: 'r1' }), { status: 400, headers: { 'content-type': 'application/json' } })) as typeof fetch
    await expect(api('/api/documents', { method: 'POST' })).rejects.toBeInstanceOf(ApiError)
    try {
      await api('/api/documents', { method: 'POST' })
    } catch (e) {
      expect(errorMessage(e)).toBe('file type .exe is not supported')
      expect((e as ApiError).requestId).toBe('r1')
    }
  })
})
