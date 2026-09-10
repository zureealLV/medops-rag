import { useAuthStore } from '@/stores/auth'

const API_BASE = (import.meta.env.VITE_API_BASE ?? '').replace(/\/$/, '')

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly code?: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

export async function apiRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  const auth = useAuthStore()
  const headers = new Headers(options.headers)
  if (auth.profile.authMode === 'api_key') {
    if (auth.profile.apiKey) headers.set('Authorization', `Bearer ${auth.profile.apiKey}`)
  } else {
    headers.set('X-Tenant-ID', auth.profile.tenantId)
    headers.set('X-Actor-ID', auth.profile.actorId)
  }
  if (options.body && !(options.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const response = await fetch(`${API_BASE}${path}`, { ...options, headers })
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`
    let code: string | undefined
    try {
      const payload = await response.json() as { detail?: string; message?: string; error?: { code?: string; message?: string } }
      message = payload.error?.message ?? payload.detail ?? payload.message ?? message
      code = payload.error?.code
    } catch { /* non-JSON error response */ }
    throw new ApiError(message, response.status, code)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export function encodeQuery(values: Record<string, string | number | undefined>): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(values)) {
    if (value !== undefined && value !== '') params.set(key, String(value))
  }
  return params.toString()
}
