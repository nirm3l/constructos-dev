import type {
  ActivationCodeCreateRequest,
  ActivationCodeCreateResponse,
  ClientTokenCreateRequest,
  ClientTokenCreateResponse,
  ContactRequestsListResponse,
  HealthResponse,
  InstallationResponse,
  InstallationsListResponse,
  WaitlistListResponse,
  UpdateSubscriptionRequest,
  UpdateSubscriptionResponse,
} from './types'

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function api<T>(path: string, token: string | null, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers ?? {})
  if (!headers.has('Content-Type') && init?.body) {
    headers.set('Content-Type', 'application/json')
  }
  if (token && token.trim()) {
    headers.set('Authorization', `Bearer ${token.trim()}`)
  }

  const response = await fetch(path, {
    ...init,
    headers,
  })

  if (!response.ok) {
    let detail = `Request failed (${response.status})`
    try {
      const payload = await response.json()
      if (payload && typeof payload.detail === 'string') {
        detail = payload.detail
      }
    } catch {
      // Keep default detail.
    }
    throw new ApiError(response.status, detail)
  }

  return response.json() as Promise<T>
}

export function getHealth(): Promise<HealthResponse> {
  return api<HealthResponse>('/api/health', null)
}

export function listInstallations(
  token: string,
  params: { q?: string; status?: string; limit?: number; offset?: number }
): Promise<InstallationsListResponse> {
  const search = new URLSearchParams()
  if (params.q) search.set('q', params.q)
  if (params.status) search.set('status', params.status)
  if (params.limit != null) search.set('limit', String(params.limit))
  if (params.offset != null) search.set('offset', String(params.offset))
  return api<InstallationsListResponse>(`/v1/admin/installations?${search.toString()}`, token)
}

export function getInstallation(token: string, installationId: string): Promise<InstallationResponse> {
  return api<InstallationResponse>(`/v1/admin/installations/${encodeURIComponent(installationId)}`, token)
}

export function updateInstallationSubscription(
  token: string,
  installationId: string,
  payload: UpdateSubscriptionRequest
): Promise<UpdateSubscriptionResponse> {
  return api<UpdateSubscriptionResponse>(
    `/v1/admin/installations/${encodeURIComponent(installationId)}/subscription`,
    token,
    {
      method: 'PUT',
      body: JSON.stringify(payload),
    }
  )
}

export function createActivationCode(
  token: string,
  payload: ActivationCodeCreateRequest
): Promise<ActivationCodeCreateResponse> {
  return api<ActivationCodeCreateResponse>('/v1/admin/activation-codes', token, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function createClientToken(
  token: string,
  payload: ClientTokenCreateRequest
): Promise<ClientTokenCreateResponse> {
  return api<ClientTokenCreateResponse>('/v1/admin/client-tokens', token, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function listWaitlist(
  token: string,
  params: { q?: string; status?: string; source?: string; limit?: number; offset?: number }
): Promise<WaitlistListResponse> {
  const search = new URLSearchParams()
  if (params.q) search.set('q', params.q)
  if (params.status) search.set('status', params.status)
  if (params.source) search.set('source', params.source)
  if (params.limit != null) search.set('limit', String(params.limit))
  if (params.offset != null) search.set('offset', String(params.offset))
  return api<WaitlistListResponse>(`/v1/admin/waitlist?${search.toString()}`, token)
}

export function listContactRequests(
  token: string,
  params: { q?: string; request_type?: string; status?: string; source?: string; limit?: number; offset?: number }
): Promise<ContactRequestsListResponse> {
  const search = new URLSearchParams()
  if (params.q) search.set('q', params.q)
  if (params.request_type) search.set('request_type', params.request_type)
  if (params.status) search.set('status', params.status)
  if (params.source) search.set('source', params.source)
  if (params.limit != null) search.set('limit', String(params.limit))
  if (params.offset != null) search.set('offset', String(params.offset))
  return api<ContactRequestsListResponse>(`/v1/admin/contact-requests?${search.toString()}`, token)
}
