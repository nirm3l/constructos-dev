import React from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ApiError,
  deleteInstallation,
  getHealth,
  getInstallation,
  listContactRequests,
  listInstallations,
  listWaitlist,
  openAdminEvents,
  provisionOnboardingPackage,
  sendAdminEmail,
  updateCustomerSubscription,
  updateInstallationSubscription
} from './api'
import type {
  AdminProvisionOnboardingRequest,
  AdminSendEmailRequest,
  InstallationListItem,
  InstallationRecord,
  SubscriptionStatus,
  UpdateSubscriptionRequest,
} from './types'

const TOKEN_STORAGE_KEY = 'lcp_admin_token'
const STATUS_OPTIONS: SubscriptionStatus[] = ['none', 'active', 'trialing', 'lifetime', 'beta']
const LEGACY_STATUS_ALIASES: Record<string, SubscriptionStatus> = {
  canceled: 'none',
  past_due: 'active',
  grace: 'active',
}
const ONBOARDING_PLAN_CODES = ['monthly', 'yearly', 'trial', 'beta', 'lifetime'] as const
const SUBSCRIPTION_PLAN_CODES_BY_STATUS: Record<SubscriptionStatus, string[]> = {
  none: ['', 'monthly', 'yearly'],
  active: ['monthly', 'yearly'],
  trialing: ['trial'],
  lifetime: ['lifetime'],
  beta: ['beta'],
}

type FormState = {
  subscription_status: SubscriptionStatus
  plan_code: string
  customer_ref: string
  valid_until: string
  metadata_text: string
}

type EmailFormState = {
  to_email: string
  subject: string
  text_body: string
}

type OnboardingProvisionFormState = {
  to_email: string
  plan_code: string
  valid_until: string
  max_installations: string
  image_tag: string
  install_script_url: string
  support_email: string
  metadata_text: string
}

type CustomerGroup = {
  customer_ref: string
  items: InstallationListItem[]
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
  const rawStatus = String(item.installation.subscription_status || '').trim().toLowerCase()
  const normalizedStatus = LEGACY_STATUS_ALIASES[rawStatus] ?? (rawStatus as SubscriptionStatus)
  return {
    subscription_status: STATUS_OPTIONS.includes(normalizedStatus) ? normalizedStatus : 'none',
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

function isLifetimePlanCode(value: string | null | undefined): boolean {
  return String(value || '').trim().toLowerCase() === 'lifetime'
}

function isBetaPlanCode(value: string | null | undefined): boolean {
  return String(value || '').trim().toLowerCase() === 'beta'
}

function installationCustomerEmail(installation: InstallationRecord | null | undefined): string | null {
  const directValue = String(installation?.customer_email || '').trim().toLowerCase()
  if (directValue) {
    return directValue
  }
  const metadata = installation?.metadata
  if (!metadata || typeof metadata !== 'object') {
    return null
  }
  const candidateFields = ['issued_to_email', 'customer_email', 'to_email', 'contact_email', 'email']
  for (const key of candidateFields) {
    const value = String((metadata as Record<string, unknown>)[key] || '').trim().toLowerCase()
    if (value) {
      return value
    }
  }
  return null
}

function normalizePlanCodeForStatus(status: SubscriptionStatus, planCodeValue: string): string | null {
  const raw = String(planCodeValue || '').trim()
  const normalized = raw.toLowerCase()
  const reserved = new Set(['lifetime', 'beta', 'trial'])

  if (status === 'lifetime') {
    if (raw && normalized !== 'lifetime') {
      throw new Error("plan_code must be 'lifetime' when subscription_status is 'lifetime'")
    }
    return 'lifetime'
  }
  if (status === 'beta') {
    if (raw && normalized !== 'beta') {
      throw new Error("plan_code must be 'beta' when subscription_status is 'beta'")
    }
    return 'beta'
  }
  if (status === 'trialing') {
    if (raw && normalized !== 'trial') {
      throw new Error("plan_code must be 'trial' when subscription_status is 'trialing'")
    }
    return 'trial'
  }
  if (status === 'active') {
    if (!raw) {
      throw new Error(`plan_code is required when subscription_status is '${status}'`)
    }
    if (reserved.has(normalized)) {
      throw new Error(`plan_code '${normalized}' is not allowed when subscription_status is '${status}'`)
    }
    return raw
  }
  if (status === 'none') {
    if (reserved.has(normalized)) {
      throw new Error(`plan_code '${normalized}' is not allowed when subscription_status is '${status}'`)
    }
    return raw || null
  }
  return raw || null
}

function planCodeOptionsForSubscriptionStatus(status: SubscriptionStatus): string[] {
  return [...(SUBSCRIPTION_PLAN_CODES_BY_STATUS[status] ?? [''])]
}

const ICON_PATHS = {
  save: 'M5 3h11l3 3v15H5z M8 3v6h8V3 M8 14h8',
  clear: 'M6 6l12 12M18 6L6 18',
  refresh: 'M20 12a8 8 0 1 1-2.34-5.66M20 4v4h-4',
  generate: 'M12 5v14M5 12h14',
  reset: 'M4 4v6h6M20 20v-6h-6M8 8l8 8',
  filter: 'M3 5h18l-7 8v6l-4-2v-4z',
  delete: 'M6 7h12M9 7V5h6v2m-8 3 1 10h8l1-10',
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
  const [selectedCustomerRef, setSelectedCustomerRef] = React.useState<string | null>(null)
  const [selectedInstallationId, setSelectedInstallationId] = React.useState<string | null>(null)
  const [form, setForm] = React.useState<FormState | null>(null)
  const [feedback, setFeedback] = React.useState<string>('')
  const [onboardingProvisionForm, setOnboardingProvisionForm] = React.useState<OnboardingProvisionFormState>({
    to_email: '',
    plan_code: 'monthly',
    valid_until: datetimeLocalFromNow(30),
    max_installations: '3',
    image_tag: 'main',
    install_script_url: 'https://raw.githubusercontent.com/nirm3l/constructos/main/install.sh',
    support_email: 'support@constructos.dev',
    metadata_text: '{"source":"control-plane-ui"}',
  })
  const [provisionedCustomerRef, setProvisionedCustomerRef] = React.useState<string>('')
  const [provisionedClientToken, setProvisionedClientToken] = React.useState<string>('')
  const [provisionedActivationCode, setProvisionedActivationCode] = React.useState<string>('')
  const [provisionedMessageId, setProvisionedMessageId] = React.useState<string>('')
  const [emailForm, setEmailForm] = React.useState<EmailFormState>({
    to_email: '',
    subject: 'ConstructOS onboarding package',
    text_body: 'Hello,\n\nThis is a test email sent from the ConstructOS license control-plane admin panel.\n',
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

  const customerGroups = React.useMemo<CustomerGroup[]>(() => {
    const groups = new Map<string, InstallationListItem[]>()
    for (const item of installations.data?.items ?? []) {
      const customerRef = String(item.installation.customer_ref || '').trim() || 'cust_unassigned'
      const list = groups.get(customerRef)
      if (list) {
        list.push(item)
      } else {
        groups.set(customerRef, [item])
      }
    }
    return Array.from(groups.entries())
      .map(([customer_ref, items]) => ({
        customer_ref,
        items: [...items].sort((a, b) =>
          a.installation.installation_id.localeCompare(b.installation.installation_id)
        ),
      }))
      .sort((a, b) => a.customer_ref.localeCompare(b.customer_ref))
  }, [installations.data?.items])

  const selectedCustomer = customerGroups.find((group) => group.customer_ref === selectedCustomerRef) ?? null
  const selectedCustomerInstallations = selectedCustomer?.items ?? []

  React.useEffect(() => {
    if (customerGroups.length === 0) {
      setSelectedCustomerRef(null)
      setSelectedInstallationId(null)
      setForm(null)
      return
    }
    if (!selectedCustomerRef || !customerGroups.some((group) => group.customer_ref === selectedCustomerRef)) {
      const firstGroup = customerGroups[0]
      if (!firstGroup) return
      setSelectedCustomerRef(firstGroup.customer_ref)
    }
  }, [customerGroups, selectedCustomerRef])

  React.useEffect(() => {
    if (!selectedCustomerRef) return
    if (selectedCustomerInstallations.length === 0) {
      setSelectedInstallationId(null)
      setForm(null)
      return
    }
    if (
      !selectedInstallationId ||
      !selectedCustomerInstallations.some(
        (item) => item.installation.installation_id === selectedInstallationId
      )
    ) {
      const first = selectedCustomerInstallations[0]
      if (!first) return
      setSelectedInstallationId(first.installation.installation_id)
      setForm(buildFormState(first))
    }
  }, [selectedCustomerInstallations, selectedCustomerRef, selectedInstallationId])

  const defaultBetaValidUntilIso = health.data?.beta_plan_valid_until ?? health.data?.public_beta_free_until ?? null
  const defaultBetaValidUntilLocal = toDatetimeLocal(defaultBetaValidUntilIso)

  const buildSubscriptionPayload = React.useCallback((currentForm: FormState): UpdateSubscriptionRequest => {
    const status = currentForm.subscription_status
    const normalizedPlanCode = normalizePlanCodeForStatus(status, currentForm.plan_code)
    const normalizedValidUntil = currentForm.valid_until
      ? new Date(currentForm.valid_until).toISOString()
      : null
    if (status === 'trialing' && !normalizedValidUntil) {
      throw new Error("valid_until is required when subscription_status is 'trialing'")
    }
    const validUntil =
      status === 'lifetime'
        ? null
        : status === 'beta' && !normalizedValidUntil
          ? defaultBetaValidUntilIso
          : normalizedValidUntil
    return {
      subscription_status: status,
      plan_code: normalizedPlanCode,
      customer_ref: currentForm.customer_ref.trim() || null,
      valid_until: validUntil,
      metadata: parseMetadata(currentForm.metadata_text),
    }
  }, [defaultBetaValidUntilIso])

  const saveSubscriptionMutation = useMutation({
    mutationFn: async () => {
      if (!token || !form || !selectedCustomerRef) {
        throw new Error('Missing token, selected customer, or form state')
      }
      if (!form.customer_ref.trim()) {
        throw new Error('Customer reference is required')
      }
      const payload = buildSubscriptionPayload(form)
      return updateCustomerSubscription(token, selectedCustomerRef, payload)
    },
    onSuccess: async (response) => {
      setFeedback(
        `Updated ${response.updated_installations} installation(s): ${response.source_customer_ref ?? response.customer_ref} -> ${response.customer_ref}.`
      )
      await queryClient.invalidateQueries({ queryKey: ['installations'] })
      await queryClient.invalidateQueries({ queryKey: ['installation'] })
    },
    onError: (error: unknown) => {
      const message = error instanceof Error ? error.message : 'Failed to update customer subscription'
      setFeedback(message)
    },
  })
  const moveInstallationMutation = useMutation({
    mutationFn: async () => {
      if (!token || !selectedInstallationId || !form) {
        throw new Error('Missing token, installation, or form state')
      }
      const targetCustomerRef = String(form.customer_ref || '').trim()
      if (!targetCustomerRef) {
        throw new Error('Customer reference is required')
      }
      const sourceInstallation = details.data?.installation ?? selectedFromList?.installation
      if (!sourceInstallation) {
        throw new Error('Installation details are not available')
      }
      const payload: UpdateSubscriptionRequest = {
        subscription_status: (sourceInstallation.subscription_status as SubscriptionStatus) || 'none',
        plan_code: sourceInstallation.plan_code ?? null,
        customer_ref: targetCustomerRef,
        valid_until: sourceInstallation.subscription_valid_until,
        metadata: (sourceInstallation.metadata ?? {}) as Record<string, unknown>,
      }
      return updateInstallationSubscription(token, selectedInstallationId, payload)
    },
    onSuccess: async () => {
      const targetCustomerRef = String(form?.customer_ref || '').trim()
      setFeedback(`Installation moved to customer '${targetCustomerRef}'.`)
      await queryClient.invalidateQueries({ queryKey: ['installations'] })
      await queryClient.invalidateQueries({ queryKey: ['installation'] })
    },
    onError: (error: unknown) => {
      const message = error instanceof Error ? error.message : 'Failed to move installation'
      setFeedback(message)
    },
  })
  const deleteInstallationMutation = useMutation({
    mutationFn: async (installationId: string) => {
      if (!token) {
        throw new Error('Admin token is required to delete installation')
      }
      const normalizedInstallationId = String(installationId || '').trim()
      if (!normalizedInstallationId) {
        throw new Error('installation_id is required')
      }
      return deleteInstallation(token, normalizedInstallationId)
    },
    onSuccess: async (response) => {
      setFeedback(`Installation '${response.installation_id}' permanently deleted.`)
      if (selectedInstallationId === response.installation_id) {
        setSelectedInstallationId(null)
        setForm(null)
      }
      await queryClient.invalidateQueries({ queryKey: ['installations'] })
      await queryClient.invalidateQueries({ queryKey: ['installation'] })
    },
    onError: (error: unknown) => {
      const message = error instanceof Error ? error.message : 'Failed to delete installation'
      setFeedback(message)
    },
  })
  const provisionOnboardingMutation = useMutation({
    mutationFn: async () => {
      if (!token) {
        throw new Error('Admin token is required to provision onboarding package')
      }
      const toEmail = String(onboardingProvisionForm.to_email || '').trim()
      const normalizedPlanCode = String(onboardingProvisionForm.plan_code || '').trim().toLowerCase() || 'monthly'
      const isUnlimitedSeatPlan = isLifetimePlanCode(normalizedPlanCode) || isBetaPlanCode(normalizedPlanCode)
      let maxInstallations = Number.parseInt(String(onboardingProvisionForm.max_installations || '').trim(), 10)
      if (!toEmail) {
        throw new Error('to_email is required')
      }
      if (isUnlimitedSeatPlan) {
        maxInstallations = Number.parseInt(String(health.data?.default_max_installations ?? 3), 10)
      }
      if (!Number.isFinite(maxInstallations) || maxInstallations < 1 || maxInstallations > 100) {
        throw new Error('max_installations must be between 1 and 100')
      }
      const payload: AdminProvisionOnboardingRequest = {
        to_email: toEmail,
        plan_code: normalizedPlanCode || null,
        valid_until:
          isLifetimePlanCode(normalizedPlanCode)
            ? null
            : isBetaPlanCode(normalizedPlanCode) && !String(onboardingProvisionForm.valid_until || '').trim()
              ? defaultBetaValidUntilIso
            : onboardingProvisionForm.valid_until
              ? new Date(onboardingProvisionForm.valid_until).toISOString()
              : null,
        max_installations: maxInstallations,
        image_tag: String(onboardingProvisionForm.image_tag || '').trim() || 'main',
        install_script_url: String(onboardingProvisionForm.install_script_url || '').trim(),
        support_email: String(onboardingProvisionForm.support_email || '').trim() || 'support@constructos.dev',
        metadata: parseMetadata(onboardingProvisionForm.metadata_text),
      }
      return provisionOnboardingPackage(token, payload)
    },
    onSuccess: async (response) => {
      setProvisionedCustomerRef(response.customer_ref)
      setProvisionedClientToken(response.client_token)
      setProvisionedActivationCode(response.activation_code)
      setProvisionedMessageId(String(response.message_id || '').trim())
      setFeedback(`Onboarding package generated and sent to ${response.to_email}.`)
      await queryClient.invalidateQueries({ queryKey: ['installations'] })
    },
    onError: (error: unknown) => {
      const message = error instanceof Error ? error.message : 'Failed to provision onboarding package'
      setFeedback(message)
    },
  })
  const sendEmailMutation = useMutation({
    mutationFn: async () => {
      if (!token) {
        throw new Error('Admin token is required to send emails')
      }
      const toEmail = String(emailForm.to_email || '').trim()
      const subject = String(emailForm.subject || '').trim()
      const textBody = String(emailForm.text_body || '').trim()
      if (!toEmail) {
        throw new Error('to_email is required')
      }
      if (!subject) {
        throw new Error('subject is required')
      }
      if (!textBody) {
        throw new Error('text_body is required')
      }
      const payload: AdminSendEmailRequest = {
        to_email: toEmail,
        subject,
        text_body: textBody,
      }
      return sendAdminEmail(token, payload)
    },
    onSuccess: (response) => {
      const suffix = response.message_id ? ` (id: ${response.message_id})` : ''
      setFeedback(`Email sent successfully via ${response.provider}.${suffix}`)
    },
    onError: (error: unknown) => {
      const message = error instanceof Error ? error.message : 'Failed to send email'
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

  const selectedFromList = (installations.data?.items ?? []).find(
    (item) => item.installation.installation_id === selectedInstallationId
  )
  const currentInstallation = details.data?.installation ?? selectedFromList?.installation ?? null
  const currentInstallationCustomerRef = String(currentInstallation?.customer_ref ?? '').trim()
  const currentInstallationCustomerEmail = installationCustomerEmail(currentInstallation)
  const targetFormCustomerRef = String(form?.customer_ref || '').trim()
  const onboardingPlanIsLifetime = isLifetimePlanCode(onboardingProvisionForm.plan_code)
  const onboardingPlanSkipsSeatLimit = onboardingPlanIsLifetime || isBetaPlanCode(onboardingProvisionForm.plan_code)
  const subscriptionPlanCodeOptions = React.useMemo(() => {
    if (!form) {
      return [] as string[]
    }
    const options = planCodeOptionsForSubscriptionStatus(form.subscription_status)
    const currentPlanCode = String(form.plan_code || '').trim()
    if (currentPlanCode && !options.includes(currentPlanCode)) {
      options.push(currentPlanCode)
    }
    return options
  }, [form])
  const customerCount = customerGroups.length
  const installationCount = installations.data?.items.length ?? 0
  const selectedCustomerInstallationCount = selectedCustomerInstallations.length
  const waitlistCount = waitlist.data?.items.length ?? 0
  const contactRequestsCount = contactRequests.data?.items.length ?? 0
  const betaPlanCutoff = health.data?.beta_plan_valid_until ?? health.data?.public_beta_free_until ?? null
  const betaPlanLabel = betaPlanCutoff
    ? `${formatDateTime(betaPlanCutoff)}`
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
    setSelectedCustomerRef(null)
    setSelectedInstallationId(null)
    setForm(null)
    setFeedback('Token cleared.')
  }

  return (
    <div className="page">
      <header className="header">
        <div className="header-main">
          <h1>License Control Plane</h1>
          <p className="muted">Realtime operations dashboard for licensing, waitlist, contact requests, and onboarding.</p>
        </div>
        <div className="status-strip">
          <span className={`status-chip ${health.data?.ok ? 'status-chip-ok' : 'status-chip-warn'}`}>
            API {health.data?.ok ? 'OK' : 'UNKNOWN'}
          </span>
          <span className={`status-chip ${liveFeedState === 'online' ? 'status-chip-ok' : 'status-chip-warn'}`}>
            SSE {liveFeedLabel}
          </span>
          <span className="status-chip">
            Beta cutoff {betaPlanLabel}
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
        <h2>Onboarding Package</h2>
        <p className="muted">
          Enter customer email. The control-plane generates customer reference (from email hash), client token,
          activation code, and sends a branded onboarding email in one action.
        </p>
        <form
          onSubmit={(event) => {
            event.preventDefault()
            setFeedback('')
            provisionOnboardingMutation.mutate()
          }}
        >
          <div className="form-grid">
            <label>
              Recipient email
              <input
                value={onboardingProvisionForm.to_email}
                onChange={(event) =>
                  setOnboardingProvisionForm((prev) => ({ ...prev, to_email: event.target.value }))
                }
                placeholder="support@constructos.dev"
              />
            </label>
            <label>
              Plan code
              <select
                value={onboardingProvisionForm.plan_code}
                onChange={(event) =>
                  setOnboardingProvisionForm((prev) => ({
                    ...prev,
                    plan_code: event.target.value,
                    valid_until:
                      isLifetimePlanCode(event.target.value)
                        ? ''
                        : isBetaPlanCode(event.target.value) && !prev.valid_until
                          ? defaultBetaValidUntilLocal
                          : prev.valid_until,
                  }))
                }
              >
                {ONBOARDING_PLAN_CODES.map((planCode) => (
                  <option key={planCode} value={planCode}>
                    {planCode}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Valid until
              <input
                type="datetime-local"
                value={onboardingProvisionForm.valid_until}
                disabled={onboardingPlanIsLifetime}
                onChange={(event) =>
                  setOnboardingProvisionForm((prev) => ({ ...prev, valid_until: event.target.value }))
                }
              />
            </label>
            <label>
              Max installations
              <input
                value={onboardingProvisionForm.max_installations}
                disabled={onboardingPlanSkipsSeatLimit}
                onChange={(event) =>
                  setOnboardingProvisionForm((prev) => ({ ...prev, max_installations: event.target.value }))
                }
              />
            </label>
            {onboardingPlanSkipsSeatLimit && (
              <p className="muted">
                Seat limit is not enforced for <code>{onboardingProvisionForm.plan_code}</code> plan.
              </p>
            )}
            <label>
              Image tag
              <input
                value={onboardingProvisionForm.image_tag}
                onChange={(event) =>
                  setOnboardingProvisionForm((prev) => ({ ...prev, image_tag: event.target.value }))
                }
                placeholder="main"
              />
            </label>
            <label>
              Support email
              <input
                value={onboardingProvisionForm.support_email}
                onChange={(event) =>
                  setOnboardingProvisionForm((prev) => ({ ...prev, support_email: event.target.value }))
                }
                placeholder="support@constructos.dev"
              />
            </label>
          </div>
          <label>
            Install script URL
            <input
              value={onboardingProvisionForm.install_script_url}
              onChange={(event) =>
                setOnboardingProvisionForm((prev) => ({ ...prev, install_script_url: event.target.value }))
              }
              placeholder="https://raw.githubusercontent.com/nirm3l/constructos/main/install.sh"
            />
          </label>
          <label>
            Metadata (JSON object)
            <textarea
              value={onboardingProvisionForm.metadata_text}
              onChange={(event) =>
                setOnboardingProvisionForm((prev) => ({ ...prev, metadata_text: event.target.value }))
              }
              rows={4}
            />
          </label>
          <div className="row">
            <button type="submit" disabled={!token || provisionOnboardingMutation.isPending}>
              <ButtonIcon name="generate" />
              {provisionOnboardingMutation.isPending ? 'Provisioning...' : 'Generate + Send Package'}
            </button>
            <button
              type="button"
              className="button-secondary"
              onClick={() =>
                setOnboardingProvisionForm({
                  to_email: '',
                  plan_code: 'monthly',
                  valid_until: datetimeLocalFromNow(30),
                  max_installations: String(health.data?.default_max_installations ?? 3),
                  image_tag: 'main',
                  install_script_url: 'https://raw.githubusercontent.com/nirm3l/constructos/main/install.sh',
                  support_email: 'support@constructos.dev',
                  metadata_text: '{"source":"control-plane-ui"}',
                })
              }
            >
              <ButtonIcon name="reset" />Reset
            </button>
          </div>
        </form>
        {provisionedCustomerRef && (
          <p className="generated-code">
            Customer reference: <code>{provisionedCustomerRef}</code>
            <br />
            Client token: <code>{provisionedClientToken}</code>
            <br />
            Activation code: <code>{provisionedActivationCode}</code>
            {provisionedMessageId ? (
              <>
                <br />
                Resend message id: <code>{provisionedMessageId}</code>
              </>
            ) : null}
          </p>
        )}
      </section>

      <section className="panel">
        <h2>Email Delivery Test</h2>
        <p className="muted">
          Send a test email via Resend using control-plane environment variables{' '}
          <code>LCP_EMAIL_RESEND_API_KEY</code> and <code>LCP_EMAIL_FROM</code>.
        </p>
        <form
          onSubmit={(event) => {
            event.preventDefault()
            setFeedback('')
            sendEmailMutation.mutate()
          }}
        >
          <div className="form-grid">
            <label>
              Recipient email
              <input
                value={emailForm.to_email}
                onChange={(event) =>
                  setEmailForm((prev) => ({ ...prev, to_email: event.target.value }))
                }
                placeholder="ops@example.com"
              />
            </label>
            <label>
              Subject
              <input
                value={emailForm.subject}
                onChange={(event) =>
                  setEmailForm((prev) => ({ ...prev, subject: event.target.value }))
                }
                placeholder="ConstructOS onboarding package"
              />
            </label>
          </div>
          <label>
            Text body
            <textarea
              value={emailForm.text_body}
              onChange={(event) =>
                setEmailForm((prev) => ({ ...prev, text_body: event.target.value }))
              }
              rows={6}
            />
          </label>
          <div className="row">
            <button type="submit" disabled={!token || sendEmailMutation.isPending}>
              <ButtonIcon name="generate" />
              {sendEmailMutation.isPending ? 'Sending...' : 'Send Test Email'}
            </button>
            <button
              type="button"
              className="button-secondary"
              onClick={() =>
                setEmailForm({
                  to_email: '',
                  subject: 'ConstructOS onboarding package',
                  text_body:
                    'Hello,\n\nThis is a test email sent from the ConstructOS license control-plane admin panel.\n',
                })
              }
            >
              <ButtonIcon name="reset" />Reset
            </button>
          </div>
        </form>
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
          Requests submitted from marketing-site forms and in-app feedback.
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
            <option value="feedback">feedback</option>
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
                (() => {
                  const metadata =
                    entry.metadata && typeof entry.metadata === 'object'
                      ? (entry.metadata as Record<string, unknown>)
                      : {}
                  const feedbackTitle = String(metadata.title || '').trim()
                  const feedbackDescription = String(metadata.description || '').trim()
                  const feedbackInstallationId = String(metadata.installation_id || '').trim()
                  const feedbackReporter =
                    String(metadata.reporter_username || '').trim() || String(metadata.reporter_user_id || '').trim()
                  return (
                    <article key={entry.id} className="feed-item">
                      <div className="feed-item-head">
                        <div>
                          <div className="feed-item-title">
                            {feedbackTitle || <code>{entry.email}</code>}
                          </div>
                          {feedbackReporter ? (
                            <div className="feed-item-subtitle">Reporter: {feedbackReporter}</div>
                          ) : null}
                        </div>
                        <div className="feed-item-chips">
                          <span className="status-chip">{entry.request_type || '-'}</span>
                          <span className="status-chip">{entry.status || '-'}</span>
                        </div>
                      </div>
                      {feedbackInstallationId ? (
                        <p className="feed-item-line">Installation: <code>{feedbackInstallationId}</code></p>
                      ) : null}
                      <p className="feed-item-line">Source: {entry.source || '-'}</p>
                      <p className="feed-item-line">Created: {formatDateTime(entry.created_at)}</p>
                      {feedbackDescription ? <p className="feed-item-desc">{feedbackDescription}</p> : null}
                    </article>
                  )
                })()
              ))}
            </div>
          </>
        )}
      </section>

      <section className="layout">
        <aside className="panel">
          <h2>Customers</h2>
          <p className="muted">
            Customer-first view. Select a customer, then pick one of that customer's installations.
          </p>
          <div className="row compact">
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search by customer reference, installation ID, or workspace ID"
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
          <p className="muted">Loaded customers: {customerCount} | Loaded installations: {installationCount}</p>

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

          <ul className="installation-list customer-list">
            {customerGroups.map((group) => {
              const active = group.customer_ref === selectedCustomerRef
              const customerActiveCount = group.items.filter((item) => item.entitlement.status === 'active').length
              const customerEmails = Array.from(
                new Set(
                  group.items
                    .map((item) => installationCustomerEmail(item.installation))
                    .filter((value): value is string => Boolean(value))
                )
              )
              return (
                <li key={group.customer_ref} className={active ? 'active' : ''}>
                  <button
                    onClick={() => {
                      setSelectedCustomerRef(group.customer_ref)
                      setFeedback('')
                    }}
                  >
                    <strong>{group.customer_ref}</strong>
                    <span>Installations: {group.items.length}</span>
                    <span>Active entitlements: {customerActiveCount}</span>
                    <span>
                      {customerEmails.length <= 1
                        ? `Email: ${customerEmails[0] ?? '-'}`
                        : `Emails: ${customerEmails.length}`}
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>

          <h2>Customer Installations</h2>
          {!selectedCustomerRef && <p className="muted">Select a customer.</p>}
          {selectedCustomerRef && (
            <>
              <p className="muted">
                Customer: <code>{selectedCustomerRef}</code> | Installations: {selectedCustomerInstallationCount}
              </p>
              <ul className="installation-list">
                {selectedCustomerInstallations.map((item) => {
                  const installationId = item.installation.installation_id
                  const active = installationId === selectedInstallationId
                  const customerEmail = installationCustomerEmail(item.installation)
                  return (
                    <li key={installationId} className={active ? 'active' : ''}>
                      <button
                        onClick={() => {
                          setSelectedCustomerRef(item.installation.customer_ref || selectedCustomerRef)
                          setSelectedInstallationId(installationId)
                          setForm(buildFormState(item))
                          setFeedback('')
                        }}
                      >
                        <strong>{installationId}</strong>
                        <span>sub: {item.installation.subscription_status || '-'} | ent: {item.entitlement.status}</span>
                        <span>plan: {item.installation.plan_code ?? '-'}</span>
                        <span>os: {item.installation.operating_system ?? '-'}</span>
                        <span>email: {customerEmail ?? '-'}</span>
                        <span>installed: {formatDateTime(item.installation.created_at)}</span>
                      </button>
                    </li>
                  )
                })}
              </ul>
            </>
          )}
        </aside>

        <main className="panel">
          <h2>Installation Details</h2>
          {!selectedInstallationId && <p className="muted">Select an installation to inspect and update.</p>}

          {selectedInstallationId && (
            <>
              <p className="muted">Installation: <code>{selectedInstallationId}</code></p>
              <p className="muted">Customer: <code>{selectedCustomerRef ?? '-'}</code></p>
              <p className="muted">Customer email: <code>{currentInstallationCustomerEmail ?? '-'}</code></p>
              <p className="muted">
                Subscription changes are applied at customer level for all installations sharing the selected <code>customer_ref</code>.
              </p>
              <p className="muted">
                Use <code>Move Installation</code> only when a single installation must be reassigned to another customer.
              </p>
              <p className="muted">
                Subscription status: <strong>{details.data?.installation.subscription_status ?? selectedFromList?.installation.subscription_status ?? '-'}</strong>
              </p>
              <p className="muted">
                Plan code: <strong>{details.data?.installation.plan_code ?? selectedFromList?.installation.plan_code ?? '-'}</strong>
              </p>
              <p className="muted">
                Operating system: <strong>{details.data?.installation.operating_system ?? selectedFromList?.installation.operating_system ?? '-'}</strong>
              </p>
              <p className="muted">
                Entitlement status: <strong>{details.data?.entitlement.status ?? selectedFromList?.entitlement.status ?? '-'}</strong>
              </p>
              <p className="muted">
                Entitlement reason:{' '}
                <strong>{String(details.data?.entitlement.metadata?.entitlement_reason ?? selectedFromList?.entitlement.metadata?.entitlement_reason ?? '-')}</strong>
              </p>
              <p className="muted">
                Subscription valid until (configured):{' '}
                {formatDateTime(details.data?.installation.subscription_valid_until ?? selectedFromList?.installation.subscription_valid_until ?? null)}
              </p>
              <p className="muted">
                Entitlement valid until (effective): {formatDateTime(details.data?.entitlement.valid_until ?? selectedFromList?.entitlement.valid_until ?? null)}
              </p>
              <p className="muted">
                Trial ends at: {formatDateTime(details.data?.installation.trial_ends_at ?? selectedFromList?.installation.trial_ends_at ?? null)}
              </p>
              <p className="muted">
                Installed at: {formatDateTime(details.data?.installation.created_at ?? selectedFromList?.installation.created_at ?? null)}
              </p>
              <p className="muted">
                Activation IP: <code>{String(details.data?.installation.activation_ip ?? selectedFromList?.installation.activation_ip ?? '-')}</code>
              </p>

              {form && (
                <form
                  onSubmit={(event) => {
                    event.preventDefault()
                    setFeedback('')
                    saveSubscriptionMutation.mutate()
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
                                plan_code: (() => {
                                  const nextStatus = event.target.value as SubscriptionStatus
                                  if (nextStatus === 'lifetime') return 'lifetime'
                                  if (nextStatus === 'beta') return 'beta'
                                  if (nextStatus === 'trialing') return 'trial'
                                  const currentPlan = String(prev.plan_code || '').trim()
                                  const currentPlanLower = currentPlan.toLowerCase()
                                  if (nextStatus === 'active') {
                                    if (currentPlanLower === 'monthly' || currentPlanLower === 'yearly') {
                                      return currentPlanLower
                                    }
                                    return 'monthly'
                                  }
                                  if (nextStatus === 'none') {
                                    if (currentPlanLower === 'monthly' || currentPlanLower === 'yearly') {
                                      return currentPlanLower
                                    }
                                    return ''
                                  }
                                  return currentPlan
                                })(),
                                valid_until:
                                  (event.target.value as SubscriptionStatus) === 'lifetime'
                                      ? ''
                                      : (event.target.value as SubscriptionStatus) === 'beta' && !prev.valid_until
                                        ? defaultBetaValidUntilLocal
                                        : (event.target.value as SubscriptionStatus) === 'trialing' && !prev.valid_until
                                          ? datetimeLocalFromNow(14)
                                        : prev.valid_until,
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
                      <select
                        value={form.plan_code}
                        disabled={form.subscription_status === 'lifetime' || form.subscription_status === 'beta' || form.subscription_status === 'trialing'}
                        onChange={(event) =>
                          setForm((prev) => (prev ? { ...prev, plan_code: event.target.value } : prev))
                        }
                      >
                        {subscriptionPlanCodeOptions.map((planCode) => (
                          <option key={planCode || 'none'} value={planCode}>
                            {planCode || '(none)'}
                          </option>
                        ))}
                      </select>
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
                        disabled={form.subscription_status === 'lifetime'}
                        onChange={(event) =>
                          setForm((prev) => (prev ? { ...prev, valid_until: event.target.value } : prev))
                        }
                      />
                    </label>
                  </div>
                  <p className="muted">
                    Subscriptions are managed by <code>customer_ref</code>.
                  </p>
                  <p className="muted">
                    Status/Plan mapping: <code>lifetime → lifetime</code>, <code>beta → beta</code>, <code>trialing → trial</code>, and
                    <code> active</code> requires a commercial plan code such as <code>monthly</code> or <code>yearly</code>.
                  </p>

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
                    <button type="submit" disabled={saveSubscriptionMutation.isPending}>
                      <ButtonIcon name="save" />
                      {saveSubscriptionMutation.isPending ? 'Saving...' : 'Save Subscription'}
                    </button>
                    <button
                      type="button"
                      disabled={
                        moveInstallationMutation.isPending ||
                        !targetFormCustomerRef ||
                        targetFormCustomerRef === currentInstallationCustomerRef
                      }
                      onClick={() => {
                        setFeedback('')
                        moveInstallationMutation.mutate()
                      }}
                    >
                      <ButtonIcon name="generate" />
                      {moveInstallationMutation.isPending ? 'Moving...' : 'Move Installation'}
                    </button>
                    <button
                      type="button"
                      className="button-danger"
                      disabled={deleteInstallationMutation.isPending || !selectedInstallationId}
                      onClick={() => {
                        if (!selectedInstallationId) return
                        if (!window.confirm(`Delete installation '${selectedInstallationId}'?`)) {
                          setFeedback('Permanent delete canceled.')
                          return
                        }
                        setFeedback('')
                        deleteInstallationMutation.mutate(selectedInstallationId)
                      }}
                    >
                      <ButtonIcon name="delete" />
                      {deleteInstallationMutation.isPending ? 'Deleting...' : 'Permanent Delete'}
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
