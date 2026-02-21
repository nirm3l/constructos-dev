import React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ApiError,
  createActivationCode,
  createClientToken,
  getHealth,
  getInstallation,
  listInstallations,
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

export function App() {
  const queryClient = useQueryClient()

  const [tokenInput, setTokenInput] = React.useState(() => localStorage.getItem(TOKEN_STORAGE_KEY) ?? '')
  const [token, setToken] = React.useState(() => localStorage.getItem(TOKEN_STORAGE_KEY) ?? '')

  const [search, setSearch] = React.useState('')
  const [statusFilter, setStatusFilter] = React.useState('')
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

  const health = useQuery({ queryKey: ['health'], queryFn: getHealth, refetchInterval: 30000 })

  const installations = useQuery({
    queryKey: ['installations', token, search, statusFilter],
    queryFn: () => listInstallations(token, { q: search, status: statusFilter, limit: 50, offset: 0 }),
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

  const selectedFromList = installations.data?.items.find(
    (item) => item.installation.installation_id === selectedInstallationId
  )
  const installationCount = installations.data?.items.length ?? 0

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
        <div>
          <h1>License Control Plane</h1>
          <p className="muted">
            Health: {health.data?.ok ? 'OK' : 'Unknown'} | Default trial duration for new installations: {health.data?.trial_days ?? '-'} days | Default max installations: {health.data?.default_max_installations ?? '-'}
          </p>
        </div>
      </header>

      <section className="panel">
        <h2>Quick Start</h2>
        <ol className="steps">
          <li>Enter the admin token and click Save Token.</li>
          <li>Create a client API token and configure it in customer deployment as <code>LICENSE_SERVER_TOKEN</code>.</li>
          <li>Create an activation code for the same customer and share that code with the customer.</li>
          <li>Customer enters activation code in the app. Installation binds to that customer (seat limit enforced).</li>
          <li>Select an installation and update subscription values in the right-side form.</li>
          <li>Click Save Subscription, then check entitlement status on the same page.</li>
        </ol>
        <p className="muted">
          Status rules: <code>active/trialing</code> + future <code>valid_until</code> results in active entitlement.
          <code>grace/past_due</code> + future <code>valid_until</code> results in grace entitlement.
          If no valid subscription exists, installation uses built-in trial until <code>trial_ends_at</code>, then becomes expired.
        </p>
      </section>

      <section className="panel">
        <h2>Admin API Token (Optional)</h2>
        <p className="muted">
          This token protects admin endpoints on the control-plane. It is not a customer license key.
        </p>
        <p className="muted">
          Use the same value configured on the server as <code>LCP_API_TOKEN</code>. In the local Docker setup, default is <code>dev-license-token</code> unless <code>LCP_API_TOKEN</code> is overridden.
        </p>
        <div className="row">
          <input
            type="password"
            value={tokenInput}
            onChange={(event) => setTokenInput(event.target.value)}
            placeholder="Enter LCP_API_TOKEN value if this server requires auth"
          />
          <button onClick={saveToken}>Save Token</button>
          <button className="button-secondary" onClick={clearToken}>Clear</button>
          <button className="button-secondary" onClick={() => void installations.refetch()} disabled={!token}>
            Reload
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
              {createClientTokenMutation.isPending ? 'Generating...' : 'Generate Client Token'}
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
              Reset
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
              {createActivationCodeMutation.isPending ? 'Generating...' : 'Generate Activation Code'}
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
              Reset
            </button>
          </div>
        </form>
        {createdActivationCode && (
          <p className="generated-code">
            New activation code: <code>{createdActivationCode}</code>
          </p>
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
              Clear Filters
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
                      Reset Form
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
