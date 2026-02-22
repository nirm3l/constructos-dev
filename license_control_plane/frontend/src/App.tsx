import React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ApiError,
  createActivationCode,
  createClientToken,
  getHealth,
  getInstallation,
  listBugReports,
  listContactRequests,
  listInstallations,
  listWaitlist,
  openAdminEvents,
  updateInstallationSubscription
} from './api'
import type { ActivationCodeCreateRequest, ClientTokenCreateRequest, InstallationListItem, SubscriptionStatus, UpdateSubscriptionRequest } from './types'

const TOKEN_STORAGE_KEY = 'lcp_admin_token'
const STATUS_OPTIONS: SubscriptionStatus[] = ['none', 'active', 'trialing', 'grace', 'past_due', 'canceled']

type FormState = {
  subscription_status: SubscriptionStatus
  plan_code: string
  customer_ref: string
  valid_until: string
  metadata_text: string
}

type ActivationCodeFormState = {
  customer_ref: string
  plan_code: string
  valid_until: string
  max_installations: string
  metadata_text: string
}

type ClientTokenFormState = {
  customer_ref: string
  metadata_text: string
}

function toDatetimeLocal(value: string | null): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function parseMetadata(metadataText: string): Record<string, unknown> {
  const trimmed = metadataText.trim()
  if (!trimmed) return {}
  const parsed = JSON.parse(trimmed)
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('Metadata must be a JSON object')
  }
  return parsed as Record<string, unknown>
}

function buildFormState(item: InstallationListItem): FormState {
  return {
    subscription_status: (item.installation.subscription_status as SubscriptionStatus) || 'none',
    plan_code: item.installation.plan_code ?? '',
    customer_ref: item.installation.customer_ref ?? '',
    valid_until: toDatetimeLocal(item.installation.subscription_valid_until),
    metadata_text: JSON.stringify(item.installation.metadata ?? {}, null, 2),
  }
}

function formatDateTime(value: string | null): string {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function datetimeLocalFromNow(days: number): string {
  const date = new Date(Date.now() + Math.max(0, days) * 24 * 60 * 60 * 1000)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

const ICON_PATHS = {
  save: 'M5 3h11l3 3v15H5z M8 3v6h8V3 M8 14h8',
  clear: 'M6 6l12 12M18 6L6 18',
  refresh: 'M20 12a8 8 0 1 1-2.34-5.66M20 4v4h-4',
  generate: 'M12 5v14M5 12h14',
  reset: 'M4 4v6h6M20 20v-6h-6M8 8l8 8',
  filter: 'M3 5h18l-7 8v6l-4-2v-4z',
} as const

function ButtonIcon({ name }: { name: keyof typeof ICON_PATHS }) {
  return (
    <svg className="button-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
      <path d={ICON_PATHS[name]} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

export function App() {
  const queryClient = useQueryClient()

  const [tokenInput, setTokenInput] = React.useState(() => localStorage.getItem(TOKEN_STORAGE_KEY) ?? '')
  const [token, setToken] = React.useState(() => localStorage.getItem(TOKEN_STORAGE_KEY) ?? '')

  const [search, setSearch] = React.useState('')
  const [statusFilter, setStatusFilter] = React.useState('')
  const [waitlistSearch, setWaitlistSearch] = React.useState('')
  const [waitlistStatusFilter, setWaitlistStatusFilter] = React.useState('')
  const [waitlistSourceFilter, setWaitlistSourceFilter] = React.useState('')
  const [contactRequestsSearch, setContactRequestsSearch] = React.useState('')
  const [contactRequestsTypeFilter, setContactRequestsTypeFilter] = React.useState('')
  const [contactRequestsStatusFilter, setContactRequestsStatusFilter] = React.useState('')
  const [contactRequestsSourceFilter, setContactRequestsSourceFilter] = React.useState('')
  const [bugReportsSearch, setBugReportsSearch] = React.useState('')
  const [bugReportsStatusFilter, setBugReportsStatusFilter] = React.useState('')
  const [bugReportsSeverityFilter, setBugReportsSeverityFilter] = React.useState('')
  const [bugReportsSourceFilter, setBugReportsSourceFilter] = React.useState('')
  const [selectedInstallationId, setSelectedInstallationId] = React.useState<string | null>(null)
  const [form, setForm] = React.useState<FormState | null>(null)
  const [feedback, setFeedback] = React.useState<string>('')
  const [createdActivationCode, setCreatedActivationCode] = React.useState<string>('')
  const [createdClientToken, setCreatedClientToken] = React.useState<string>('')
  const [activationCodeForm, setActivationCodeForm] = React.useState<ActivationCodeFormState>({
    customer_ref: '',
    plan_code: 'monthly',
    valid_until: datetimeLocalFromNow(30),
    max_installations: '3',
    metadata_text: '{}',
  })
  const [clientTokenForm, setClientTokenForm] = React.useState<ClientTokenFormState>({
    customer_ref: '',
    metadata_text: '{}',
  })
  const [liveFeedState, setLiveFeedState] = React.useState<'connecting' | 'online' | 'offline'>('offline')
  const [liveFeedLastEventAt, setLiveFeedLastEventAt] = React.useState<string | null>(null)
  const liveFeedRefetchAtRef = React.useRef(0)

  const health = useQuery({ queryKey: ['health'], queryFn: getHealth, refetchInterval: 30000 })

  const installations = useQuery({
    queryKey: ['installations', token, search, statusFilter],
    queryFn: () => listInstallations(token, { q: search, status: statusFilter, limit: 50, offset: 0 }),
  })

  const waitlist = useQuery({
    queryKey: ['waitlist', token, waitlistSearch, waitlistStatusFilter, waitlistSourceFilter],
    queryFn: () =>
      listWaitlist(token, {
        q: waitlistSearch,
        status: waitlistStatusFilter,
        source: waitlistSourceFilter,
        limit: 100,
        offset: 0,
      }),
    enabled: Boolean(token),
  })

  const contactRequests = useQuery({
    queryKey: ['contact-requests', token, contactRequestsSearch, contactRequestsTypeFilter, contactRequestsStatusFilter, contactRequestsSourceFilter],
    queryFn: () =>
      listContactRequests(token, {
        q: contactRequestsSearch,
        request_type: contactRequestsTypeFilter,
        status: contactRequestsStatusFilter,
        source: contactRequestsSourceFilter,
        limit: 100,
        offset: 0,
      }),
    enabled: Boolean(token),
  })
  const bugReports = useQuery({
    queryKey: ['bug-reports', token, bugReportsSearch, bugReportsStatusFilter, bugReportsSeverityFilter, bugReportsSourceFilter],
    queryFn: () =>
      listBugReports(token, {
        q: bugReportsSearch,
        status: bugReportsStatusFilter,
        severity: bugReportsSeverityFilter,
        source: bugReportsSourceFilter,
        limit: 100,
        offset: 0,
      }),
    enabled: Boolean(token),
  })

  React.useEffect(() => {
    if (!selectedInstallationId) return
    const current = installations.data?.items.find((item) => item.installation.installation_id === selectedInstallationId)
    if (current) {
      setForm(buildFormState(current))
    }
  }, [installations.data, selectedInstallationId])

  const details = useQuery({
    queryKey: ['installation', token, selectedInstallationId],
    queryFn: () => getInstallation(token, selectedInstallationId || ''),
    enabled: Boolean(selectedInstallationId),
  })

  const updateMutation = useMutation({
    mutationFn: async () => {
      if (!token || !selectedInstallationId || !form) {
        throw new Error('Missing token, installation, or form state')
      }
      const payload: UpdateSubscriptionRequest = {
        subscription_status: form.subscription_status,
        plan_code: form.plan_code.trim() || null,
        customer_ref: form.customer_ref.trim() || null,
        valid_until: form.valid_until ? new Date(form.valid_until).toISOString() : null,
        metadata: parseMetadata(form.metadata_text),
      }
      return updateInstallationSubscription(token, selectedInstallationId, payload)
    },
    onSuccess: async () => {
      setFeedback('Subscription updated successfully.')
      await queryClient.invalidateQueries({ queryKey: ['installations'] })
      await queryClient.invalidateQueries({ queryKey: ['installation'] })
    },
    onError: (error: unknown) => {
      const message = error instanceof Error ? error.message : 'Failed to update subscription'
      setFeedback(message)
    },
  })
  const createActivationCodeMutation = useMutation({
    mutationFn: async () => {
      if (!token) {
        throw new Error('Admin token is required to create activation codes')
      }
      const customerRef = String(activationCodeForm.customer_ref || '').trim()
      if (!customerRef) {
        throw new Error('customer_ref is required')
      }
      const maxInstallations = Number.parseInt(String(activationCodeForm.max_installations || '').trim(), 10)
      if (!Number.isFinite(maxInstallations) || maxInstallations < 1 || maxInstallations > 100) {
        throw new Error('max_installations must be between 1 and 100')
      }
      const payload: ActivationCodeCreateRequest = {
        customer_ref: customerRef,
        plan_code: String(activationCodeForm.plan_code || '').trim() || null,
        valid_until: activationCodeForm.valid_until ? new Date(activationCodeForm.valid_until).toISOString() : null,
        max_installations: maxInstallations,
        metadata: parseMetadata(activationCodeForm.metadata_text),
      }
      return createActivationCode(token, payload)
    },
    onSuccess: async (response) => {
      setCreatedActivationCode(response.activation_code)
      setFeedback('Activation code created successfully.')
      await queryClient.invalidateQueries({ queryKey: ['installations'] })
    },
    onError: (error: unknown) => {
      const message = error instanceof Error ? error.message : 'Failed to create activation code'
      setFeedback(message)
    },
  })
  const createClientTokenMutation = useMutation({
    mutationFn: async () => {
      if (!token) {
        throw new Error('Admin token is required to create client tokens')
      }
      const customerRef = String(clientTokenForm.customer_ref || '').trim()
      if (!customerRef) {
        throw new Error('customer_ref is required')
      }
      const payload: ClientTokenCreateRequest = {
        customer_ref: customerRef,
        metadata: parseMetadata(clientTokenForm.metadata_text),
      }
      return createClientToken(token, payload)
    },
    onSuccess: (response) => {
      setCreatedClientToken(response.client_token)
      setFeedback('Client token created successfully.')
    },
    onError: (error: unknown) => {
      const message = error instanceof Error ? error.message : 'Failed to create client token'
      setFeedback(message)
    },
  })

  const authError = installations.error instanceof ApiError && installations.error.status === 401

  React.useEffect(() => {
    setLiveFeedState('connecting')
    const source = openAdminEvents(token)

    const refreshQueries = () => {
      const nowMs = Date.now()
      if (nowMs - liveFeedRefetchAtRef.current < 1200) {
        return
      }
      liveFeedRefetchAtRef.current = nowMs
      void queryClient.invalidateQueries({ queryKey: ['health'] })
      void queryClient.invalidateQueries({ queryKey: ['installations'] })
      void queryClient.invalidateQueries({ queryKey: ['installation'] })
      void queryClient.invalidateQueries({ queryKey: ['waitlist'] })
      void queryClient.invalidateQueries({ queryKey: ['contact-requests'] })
      void queryClient.invalidateQueries({ queryKey: ['bug-reports'] })
    }

    const handleSseMessage = (event: MessageEvent<string>, shouldRefresh: boolean) => {
      setLiveFeedState('online')
      setLiveFeedLastEventAt(new Date().toISOString())
      if (shouldRefresh) {
        refreshQueries()
      }
      try {
        const payload = JSON.parse(String(event.data || '{}')) as Record<string, unknown>
        const action = String(payload.action || '').trim().toLowerCase()
        if (action && action !== 'heartbeat') {
          refreshQueries()
        }
      } catch {
        // Ignore invalid JSON payload and keep the stream alive.
      }
    }

    source.onopen = () => {
      setLiveFeedState('online')
      setLiveFeedLastEventAt(new Date().toISOString())
    }

    source.onerror = () => {
      setLiveFeedState(token.trim() ? 'connecting' : 'offline')
    }

    source.onmessage = (event) => handleSseMessage(event, true)
    source.addEventListener('refresh', (event) => handleSseMessage(event as MessageEvent<string>, true))
    source.addEventListener('heartbeat', (event) => handleSseMessage(event as MessageEvent<string>, false))

    return () => {
      source.close()
      setLiveFeedState('offline')
    }
  }, [queryClient, token])

  const selectedFromList = installations.data?.items.find(
    (item) => item.installation.installation_id === selectedInstallationId
  )
  const installationCount = installations.data?.items.length ?? 0
  const waitlistCount = waitlist.data?.items.length ?? 0
  const contactRequestsCount = contactRequests.data?.items.length ?? 0
  const bugReportsCount = bugReports.data?.items.length ?? 0
  const publicBetaLabel = health.data?.public_beta_active
    ? `active until ${formatDateTime(health.data?.public_beta_free_until ?? null)}`
    : health.data?.public_beta_free_until
      ? `ended (${formatDateTime(health.data?.public_beta_free_until ?? null)})`
      : 'not configured'
  const liveFeedLabel = liveFeedState === 'online' ? 'online' : liveFeedState === 'connecting' ? 'connecting' : 'offline'
  const liveFeedLastSeenLabel = formatDateTime(liveFeedLastEventAt)

  const saveToken = () => {
    const next = tokenInput.trim()
    setToken(next)
    localStorage.setItem(TOKEN_STORAGE_KEY, next)
    setFeedback('Token saved.')
  }

  const clearToken = () => {
    setToken('')
    setTokenInput('')
    localStorage.removeItem(TOKEN_STORAGE_KEY)
    setSelectedInstallationId(null)
    setForm(null)
    setFeedback('Token cleared.')
  }

  return (
    <div className="page">
      <header className="header">
        <div className="header-main">
          <h1>License Control Plane</h1>
          <p className="muted">Realtime operations dashboard for licensing, waitlist, requests, and bug triage.</p>
        </div>
        <div className="status-strip">
          <span className={`status-chip ${health.data?.ok ? 'status-chip-ok' : 'status-chip-warn'}`}>
            API {health.data?.ok ? 'OK' : 'UNKNOWN'}
          </span>
          <span className={`status-chip ${liveFeedState === 'online' ? 'status-chip-ok' : 'status-chip-warn'}`}>
            SSE {liveFeedLabel}
          </span>
          <span className="status-chip">
            Beta {publicBetaLabel}
          </span>
          <span className="status-chip">
            Trial {health.data?.trial_days ?? '-'}d
          </span>
          <span className="status-chip">
            Seats {health.data?.default_max_installations ?? '-'}
          </span>
          <span className="status-chip">
            Last event {liveFeedLastSeenLabel}
          </span>
        </div>
      </header>

      <section className="panel">
        <h2>Admin API Token</h2>
        <p className="muted">
          Use <code>LCP_API_TOKEN</code> for admin endpoints. This is not a customer license key.
        </p>
        <div className="row">
          <input
            type="password"
            value={tokenInput}
            onChange={(event) => setTokenInput(event.target.value)}
            placeholder="Enter LCP_API_TOKEN value if this server requires auth"
          />
          <button onClick={saveToken}><ButtonIcon name="save" />Save</button>
          <button className="button-secondary" onClick={clearToken}><ButtonIcon name="clear" />Clear</button>
          <button className="button-secondary" onClick={() => void installations.refetch()} disabled={!token}>
            <ButtonIcon name="refresh" />Reload
          </button>
        </div>
        {authError && <p className="error">Authentication failed. Check the token value.</p>}
        {feedback && <p className="muted">{feedback}</p>}
      </section>

      <section className="panel">
        <h2>Client API Tokens</h2>
        <p className="muted">
          Issue a dedicated deployment token per customer. This token is used as <code>LICENSE_SERVER_TOKEN</code> on the customer host.
        </p>
        <form
          onSubmit={(event) => {
            event.preventDefault()
            setFeedback('')
            createClientTokenMutation.mutate()
          }}
        >
          <div className="form-grid">
            <label>
              Customer reference
              <input
                value={clientTokenForm.customer_ref}
                onChange={(event) =>
                  setClientTokenForm((prev) => ({ ...prev, customer_ref: event.target.value }))
                }
                placeholder="customer-001"
              />
            </label>
          </div>
          <label>
            Metadata (JSON object)
            <textarea
              value={clientTokenForm.metadata_text}
              onChange={(event) =>
                setClientTokenForm((prev) => ({ ...prev, metadata_text: event.target.value }))
              }
              rows={4}
            />
          </label>
          <div className="row">
            <button type="submit" disabled={!token || createClientTokenMutation.isPending}>
              <ButtonIcon name="generate" />
              {createClientTokenMutation.isPending ? 'Generating...' : 'Generate Token'}
            </button>
            <button
              type="button"
              className="button-secondary"
              onClick={() =>
                setClientTokenForm({
                  customer_ref: '',
                  metadata_text: '{}',
                })
              }
            >
              <ButtonIcon name="reset" />Reset
            </button>
          </div>
        </form>
        {createdClientToken && (
          <p className="generated-code">
            New client token: <code>{createdClientToken}</code>
          </p>
        )}
      </section>

      <section className="panel">
        <h2>Activation Codes</h2>
        <p className="muted">
          Generate reusable customer activation codes. Seats are enforced per code via <code>max_installations</code>.
        </p>
        <form
          onSubmit={(event) => {
            event.preventDefault()
            setFeedback('')
            createActivationCodeMutation.mutate()
          }}
        >
          <div className="form-grid">
            <label>
              Customer reference
              <input
                value={activationCodeForm.customer_ref}
                onChange={(event) =>
                  setActivationCodeForm((prev) => ({ ...prev, customer_ref: event.target.value }))
                }
                placeholder="customer-001"
              />
            </label>
            <label>
              Plan code
              <input
                value={activationCodeForm.plan_code}
                onChange={(event) =>
                  setActivationCodeForm((prev) => ({ ...prev, plan_code: event.target.value }))
                }
                placeholder="monthly"
              />
            </label>
            <label>
              Valid until
              <input
                type="datetime-local"
                value={activationCodeForm.valid_until}
                onChange={(event) =>
                  setActivationCodeForm((prev) => ({ ...prev, valid_until: event.target.value }))
                }
              />
            </label>
            <label>
              Max installations
              <input
                value={activationCodeForm.max_installations}
                onChange={(event) =>
                  setActivationCodeForm((prev) => ({ ...prev, max_installations: event.target.value }))
                }
              />
            </label>
          </div>
          <label>
            Metadata (JSON object)
            <textarea
              value={activationCodeForm.metadata_text}
              onChange={(event) =>
                setActivationCodeForm((prev) => ({ ...prev, metadata_text: event.target.value }))
              }
              rows={4}
            />
          </label>
          <div className="row">
            <button type="submit" disabled={!token || createActivationCodeMutation.isPending}>
              <ButtonIcon name="generate" />
              {createActivationCodeMutation.isPending ? 'Generating...' : 'Generate Code'}
            </button>
            <button
              type="button"
              className="button-secondary"
              onClick={() =>
                setActivationCodeForm({
                  customer_ref: '',
                  plan_code: 'monthly',
                  valid_until: datetimeLocalFromNow(30),
                  max_installations: String(health.data?.default_max_installations ?? 3),
                  metadata_text: '{}',
                })
              }
            >
              <ButtonIcon name="reset" />Reset
            </button>
          </div>
        </form>
        {createdActivationCode && (
          <p className="generated-code">
            New activation code: <code>{createdActivationCode}</code>
          </p>
        )}
      </section>

      <section className="panel">
        <h2>Waitlist</h2>
        <p className="muted">
          Emails collected from the marketing-site waitlist form.
        </p>
        <div className="row compact">
          <input
            value={waitlistSearch}
            onChange={(event) => setWaitlistSearch(event.target.value)}
            placeholder="Search by email or source"
          />
          <select value={waitlistStatusFilter} onChange={(event) => setWaitlistStatusFilter(event.target.value)}>
            <option value="">All statuses</option>
            <option value="pending">pending</option>
            <option value="contacted">contacted</option>
            <option value="converted">converted</option>
          </select>
          <input
            value={waitlistSourceFilter}
            onChange={(event) => setWaitlistSourceFilter(event.target.value)}
            placeholder="Source (for example marketing-site)"
          />
        </div>
        <div className="row compact">
          <button
            type="button"
            className="button-secondary"
            onClick={() => {
              setWaitlistSearch('')
              setWaitlistStatusFilter('')
              setWaitlistSourceFilter('')
            }}
          >
            <ButtonIcon name="filter" />Clear Filters
          </button>
          <button
            type="button"
            className="button-secondary"
            onClick={() => void waitlist.refetch()}
            disabled={!token}
          >
            <ButtonIcon name="refresh" />Reload
          </button>
        </div>
        {!token && <p className="muted">Save admin token to load waitlist entries.</p>}
        {waitlist.isLoading && token && <p className="muted">Loading waitlist entries...</p>}
        {waitlist.isError && token && (
          <p className="error">{waitlist.error instanceof Error ? waitlist.error.message : 'Failed to load waitlist entries.'}</p>
        )}
        {!waitlist.isLoading && !waitlist.isError && token && waitlistCount === 0 && (
          <p className="muted">No waitlist entries found for current filters.</p>
        )}
        {!waitlist.isLoading && !waitlist.isError && token && waitlistCount > 0 && (
          <>
            <p className="muted">
              Loaded items: {waitlistCount} | Total: {waitlist.data?.total ?? 0}
            </p>
            <div className="feed-list">
              {(waitlist.data?.items ?? []).map((entry) => {
                const metadata = entry.metadata ?? {}
                const campaignRaw = metadata.campaign
                const campaign = typeof campaignRaw === 'string' && campaignRaw.trim() ? campaignRaw.trim() : '-'
                return (
                  <article key={entry.id} className="feed-item">
                    <div className="feed-item-head">
                      <div className="feed-item-title"><code>{entry.email}</code></div>
                      <div className="feed-item-chips">
                        <span className="status-chip">{entry.status || '-'}</span>
                        <span className="status-chip">{entry.source || '-'}</span>
                      </div>
                    </div>
                    <p className="feed-item-line">Campaign: {campaign}</p>
                    <p className="feed-item-line">Created: {formatDateTime(entry.created_at)}</p>
                  </article>
                )
              })}
            </div>
          </>
        )}
      </section>

      <section className="panel">
        <h2>Contact Requests</h2>
        <p className="muted">
          Requests submitted from marketing-site forms (demo, onboarding, plan details).
        </p>
        <div className="row compact">
          <input
            value={contactRequestsSearch}
            onChange={(event) => setContactRequestsSearch(event.target.value)}
            placeholder="Search by email, type, or source"
          />
          <select
            value={contactRequestsTypeFilter}
            onChange={(event) => setContactRequestsTypeFilter(event.target.value)}
          >
            <option value="">All request types</option>
            <option value="demo">demo</option>
            <option value="onboarding">onboarding</option>
            <option value="plan_details">plan_details</option>
          </select>
          <select
            value={contactRequestsStatusFilter}
            onChange={(event) => setContactRequestsStatusFilter(event.target.value)}
          >
            <option value="">All statuses</option>
            <option value="pending">pending</option>
            <option value="contacted">contacted</option>
            <option value="converted">converted</option>
          </select>
          <input
            value={contactRequestsSourceFilter}
            onChange={(event) => setContactRequestsSourceFilter(event.target.value)}
            placeholder="Source (for example marketing-site)"
          />
        </div>
        <div className="row compact">
          <button
            type="button"
            className="button-secondary"
            onClick={() => {
              setContactRequestsSearch('')
              setContactRequestsTypeFilter('')
              setContactRequestsStatusFilter('')
              setContactRequestsSourceFilter('')
            }}
          >
            <ButtonIcon name="filter" />Clear Filters
          </button>
          <button
            type="button"
            className="button-secondary"
            onClick={() => void contactRequests.refetch()}
            disabled={!token}
          >
            <ButtonIcon name="refresh" />Reload
          </button>
        </div>
        {!token && <p className="muted">Save admin token to load contact requests.</p>}
        {contactRequests.isLoading && token && <p className="muted">Loading contact requests...</p>}
        {contactRequests.isError && token && (
          <p className="error">
            {contactRequests.error instanceof Error ? contactRequests.error.message : 'Failed to load contact requests.'}
          </p>
        )}
        {!contactRequests.isLoading && !contactRequests.isError && token && contactRequestsCount === 0 && (
          <p className="muted">No contact requests found for current filters.</p>
        )}
        {!contactRequests.isLoading && !contactRequests.isError && token && contactRequestsCount > 0 && (
          <>
            <p className="muted">
              Loaded items: {contactRequestsCount} | Total: {contactRequests.data?.total ?? 0}
            </p>
            <div className="feed-list">
              {(contactRequests.data?.items ?? []).map((entry) => (
                <article key={entry.id} className="feed-item">
                  <div className="feed-item-head">
                    <div className="feed-item-title"><code>{entry.email}</code></div>
                    <div className="feed-item-chips">
                      <span className="status-chip">{entry.request_type || '-'}</span>
                      <span className="status-chip">{entry.status || '-'}</span>
                    </div>
                  </div>
                  <p className="feed-item-line">Source: {entry.source || '-'}</p>
                  <p className="feed-item-line">Created: {formatDateTime(entry.created_at)}</p>
                </article>
              ))}
            </div>
          </>
        )}
      </section>

      <section className="panel">
        <h2>Bug Reports</h2>
        <p className="muted">
          Reports submitted from authenticated app users through the application server.
        </p>
        <div className="row compact">
          <input
            value={bugReportsSearch}
            onChange={(event) => setBugReportsSearch(event.target.value)}
            placeholder="Search by report ID, title, reporter, installation, workspace, or customer"
          />
          <select
            value={bugReportsStatusFilter}
            onChange={(event) => setBugReportsStatusFilter(event.target.value)}
          >
            <option value="">All statuses</option>
            <option value="new">new</option>
            <option value="triaged">triaged</option>
            <option value="in_progress">in_progress</option>
            <option value="resolved">resolved</option>
            <option value="closed">closed</option>
            <option value="rejected">rejected</option>
          </select>
          <select
            value={bugReportsSeverityFilter}
            onChange={(event) => setBugReportsSeverityFilter(event.target.value)}
          >
            <option value="">All severities</option>
            <option value="low">low</option>
            <option value="medium">medium</option>
            <option value="high">high</option>
            <option value="critical">critical</option>
          </select>
          <input
            value={bugReportsSourceFilter}
            onChange={(event) => setBugReportsSourceFilter(event.target.value)}
            placeholder="Source (for example task-app-ui)"
          />
        </div>
        <div className="row compact">
          <button
            type="button"
            className="button-secondary"
            onClick={() => {
              setBugReportsSearch('')
              setBugReportsStatusFilter('')
              setBugReportsSeverityFilter('')
              setBugReportsSourceFilter('')
            }}
          >
            <ButtonIcon name="filter" />Clear Filters
          </button>
          <button
            type="button"
            className="button-secondary"
            onClick={() => void bugReports.refetch()}
            disabled={!token}
          >
            <ButtonIcon name="refresh" />Reload
          </button>
        </div>
        {!token && <p className="muted">Save admin token to load bug reports.</p>}
        {bugReports.isLoading && token && <p className="muted">Loading bug reports...</p>}
        {bugReports.isError && token && (
          <p className="error">{bugReports.error instanceof Error ? bugReports.error.message : 'Failed to load bug reports.'}</p>
        )}
        {!bugReports.isLoading && !bugReports.isError && token && bugReportsCount === 0 && (
          <p className="muted">No bug reports found for current filters.</p>
        )}
        {!bugReports.isLoading && !bugReports.isError && token && bugReportsCount > 0 && (
          <>
            <p className="muted">
              Loaded items: {bugReportsCount} | Total: {bugReports.data?.total ?? 0}
            </p>
            <div className="feed-list">
              {(bugReports.data?.items ?? []).map((entry) => (
                <article key={entry.report_id} className="feed-item">
                  <div className="feed-item-head">
                    <div>
                      <div className="feed-item-title">{entry.title || '-'}</div>
                      <div className="feed-item-subtitle"><code>{entry.report_id}</code></div>
                    </div>
                    <div className="feed-item-chips">
                      <span className="status-chip">{entry.severity || '-'}</span>
                      <span className="status-chip">{entry.status || '-'}</span>
                    </div>
                  </div>
                  <p className="feed-item-line">
                    Installation: <code>{entry.installation_id}</code>
                    {entry.workspace_id ? <> | ws: <code>{entry.workspace_id}</code></> : null}
                  </p>
                  <p className="feed-item-line">Reporter: {entry.reporter_username || entry.reporter_user_id || '-'}</p>
                  <p className="feed-item-line">Created: {formatDateTime(entry.created_at)}</p>
                  <p className="feed-item-desc">{entry.description || '-'}</p>
                </article>
              ))}
            </div>
          </>
        )}
      </section>

      <section className="layout">
        <aside className="panel">
          <h2>Installations</h2>
          <div className="row compact">
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search by installation ID, customer reference, or workspace ID"
            />
            <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
              <option value="">All statuses</option>
              {STATUS_OPTIONS.map((status) => (
                <option key={status} value={status}>
                  {status}
                </option>
              ))}
            </select>
          </div>
          <div className="row compact">
            <button
              type="button"
              className="button-secondary"
              onClick={() => {
                setSearch('')
                setStatusFilter('')
              }}
            >
              <ButtonIcon name="filter" />Clear Filters
            </button>
          </div>
          <p className="muted">Loaded items: {installationCount}</p>

          {installations.isLoading && <p className="muted">Loading installations...</p>}
          {installations.isError && !authError && (
            <p className="error">{installations.error instanceof Error ? installations.error.message : 'Failed to load installations.'}</p>
          )}
          {authError && !token && (
            <p className="error">This server requires an admin API token. Enter the LCP_API_TOKEN value and save it.</p>
          )}
          {!installations.isLoading && !installations.isError && installationCount === 0 && (
            <p className="muted">No installations found for current filters. Clear filters or search by exact installation ID.</p>
          )}

          <ul className="installation-list">
            {(installations.data?.items ?? []).map((item) => {
              const installationId = item.installation.installation_id
              const active = installationId === selectedInstallationId
              return (
                <li key={installationId} className={active ? 'active' : ''}>
                  <button
                    onClick={() => {
                      setSelectedInstallationId(installationId)
                      setForm(buildFormState(item))
                      setFeedback('')
                    }}
                  >
                    <strong>{installationId}</strong>
                    <span>{item.entitlement.status} | {item.installation.plan_code ?? '-'}</span>
                  </button>
                </li>
              )
            })}
          </ul>
        </aside>

        <main className="panel">
          <h2>Installation Details</h2>
          {!selectedInstallationId && <p className="muted">Select an installation to inspect and update.</p>}

          {selectedInstallationId && (
            <>
              <p className="muted">Installation: <code>{selectedInstallationId}</code></p>
              <p className="muted">
                Subscription status: <strong>{details.data?.installation.subscription_status ?? selectedFromList?.installation.subscription_status ?? '-'}</strong>
              </p>
              <p className="muted">
                Entitlement status: <strong>{details.data?.entitlement.status ?? selectedFromList?.entitlement.status ?? '-'}</strong>
              </p>
              <p className="muted">
                Valid until: {formatDateTime(details.data?.entitlement.valid_until ?? selectedFromList?.entitlement.valid_until ?? null)}
              </p>
              <p className="muted">
                Trial ends at: {formatDateTime(details.data?.installation.trial_ends_at ?? selectedFromList?.installation.trial_ends_at ?? null)}
              </p>
              <p className="muted">
                Activation IP: <code>{String(details.data?.installation.activation_ip ?? selectedFromList?.installation.activation_ip ?? '-')}</code>
              </p>

              {form && (
                <form
                  onSubmit={(event) => {
                    event.preventDefault()
                    setFeedback('')
                    updateMutation.mutate()
                  }}
                >
                  <div className="form-grid">
                    <label>
                      Subscription status
                      <select
                        value={form.subscription_status}
                        onChange={(event) =>
                          setForm((prev) =>
                            prev
                              ? {
                                  ...prev,
                                  subscription_status: event.target.value as SubscriptionStatus,
                                }
                              : prev
                          )
                        }
                      >
                        {STATUS_OPTIONS.map((status) => (
                          <option key={status} value={status}>
                            {status}
                          </option>
                        ))}
                      </select>
                    </label>

                    <label>
                      Plan code
                      <input
                        value={form.plan_code}
                        onChange={(event) =>
                          setForm((prev) => (prev ? { ...prev, plan_code: event.target.value } : prev))
                        }
                      />
                    </label>

                    <label>
                      Customer reference
                      <input
                        value={form.customer_ref}
                        onChange={(event) =>
                          setForm((prev) => (prev ? { ...prev, customer_ref: event.target.value } : prev))
                        }
                      />
                    </label>

                    <label>
                      Subscription valid until
                      <input
                        type="datetime-local"
                        value={form.valid_until}
                        onChange={(event) =>
                          setForm((prev) => (prev ? { ...prev, valid_until: event.target.value } : prev))
                        }
                      />
                    </label>
                  </div>

                  <label>
                    Metadata (JSON object)
                    <textarea
                      value={form.metadata_text}
                      onChange={(event) =>
                        setForm((prev) => (prev ? { ...prev, metadata_text: event.target.value } : prev))
                      }
                      rows={10}
                    />
                  </label>

                  <div className="row">
                    <button type="submit" disabled={updateMutation.isPending}>
                      <ButtonIcon name="save" />
                      {updateMutation.isPending ? 'Saving...' : 'Save Subscription'}
                    </button>
                    <button
                      type="button"
                      className="button-secondary"
                      onClick={() => {
                        if (!selectedFromList) return
                        setForm(buildFormState(selectedFromList))
                        setFeedback('Form reset.')
                      }}
                    >
                      <ButtonIcon name="reset" />Reset Form
                    </button>
                  </div>
                </form>
              )}
            </>
          )}
        </main>
      </section>
    </div>
  )
}
