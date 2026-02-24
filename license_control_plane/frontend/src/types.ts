export type SubscriptionStatus = 'none' | 'active' | 'trialing' | 'grace' | 'past_due' | 'canceled'

export type InstallationRecord = {
  installation_id: string
  workspace_id: string | null
  customer_ref: string | null
  plan_code: string | null
  subscription_status: SubscriptionStatus | string
  subscription_valid_until: string | null
  trial_started_at: string
  trial_ends_at: string
  activation_ip?: string | null
  metadata: Record<string, unknown>
  updated_at: string
}

export type EntitlementRecord = {
  installation_id: string
  status: string
  plan_code: string | null
  valid_from: string
  valid_until: string | null
  trial_ends_at: string
  token_expires_at: string
  metadata: Record<string, unknown>
}

export type InstallationListItem = {
  installation: InstallationRecord
  entitlement: EntitlementRecord
}

export type InstallationsListResponse = {
  ok: boolean
  items: InstallationListItem[]
  total: number
  limit: number
  offset: number
}

export type InstallationResponse = {
  ok: boolean
  installation: InstallationRecord
  entitlement: EntitlementRecord
}

export type UpdateSubscriptionRequest = {
  subscription_status: SubscriptionStatus
  plan_code: string | null
  customer_ref: string | null
  valid_until: string | null
  metadata: Record<string, unknown>
}

export type UpdateSubscriptionResponse = {
  ok: boolean
  installation_id: string
  subscription_status: string
  entitlement: EntitlementRecord
}

export type HealthResponse = {
  ok: boolean
  timestamp: string
  trial_days: number
  default_max_installations?: number
  public_beta_free_until?: string | null
  public_beta_active?: boolean
}

export type ActivationCodeRecord = {
  id: number
  customer_ref: string
  plan_code: string | null
  valid_until: string | null
  max_installations: number
  is_active: boolean
  usage_count: number
  code_suffix: string
  last_used_at: string | null
  metadata: Record<string, unknown>
  updated_at: string
  created_at: string
}

export type ActivationCodeCreateRequest = {
  customer_ref: string
  plan_code: string | null
  valid_until: string | null
  max_installations: number
  metadata: Record<string, unknown>
}

export type ActivationCodeCreateResponse = {
  ok: boolean
  activation_code: string
  activation_code_record: ActivationCodeRecord
}

export type ClientTokenRecord = {
  id: number
  customer_ref: string
  is_active: boolean
  token_suffix: string
  metadata: Record<string, unknown>
  updated_at: string
  created_at: string
}

export type ClientTokenCreateRequest = {
  customer_ref: string
  metadata: Record<string, unknown>
}

export type ClientTokenCreateResponse = {
  ok: boolean
  client_token: string
  client_token_record: ClientTokenRecord
}

export type AdminSendEmailRequest = {
  to_email: string
  subject: string
  text_body: string
}

export type AdminSendEmailResponse = {
  ok: boolean
  provider: string
  to_email: string
  message_id: string | null
}

export type AdminSendOnboardingEmailRequest = {
  to_email: string
  customer_ref: string
  client_token: string
  activation_code: string
  image_tag: string
  install_script_url: string
  support_email: string
}

export type AdminSendOnboardingEmailResponse = {
  ok: boolean
  provider: string
  to_email: string
  customer_ref: string
  subject: string
  message_id: string | null
}

export type AdminProvisionOnboardingRequest = {
  to_email: string
  plan_code: string | null
  valid_until: string | null
  max_installations: number
  image_tag: string
  install_script_url: string
  support_email: string
  metadata: Record<string, unknown>
}

export type AdminProvisionOnboardingResponse = {
  ok: boolean
  provider: string
  to_email: string
  customer_ref: string
  subject: string
  message_id: string | null
  client_token: string
  client_token_record: ClientTokenRecord
  activation_code: string
  activation_code_record: ActivationCodeRecord
}

export type WaitlistEntryRecord = {
  id: number
  email: string
  source: string
  status: string
  metadata: Record<string, unknown>
  updated_at: string
  created_at: string
}

export type WaitlistListResponse = {
  ok: boolean
  items: WaitlistEntryRecord[]
  total: number
  limit: number
  offset: number
}

export type ContactRequestRecord = {
  id: number
  request_type: string
  email: string
  source: string
  status: string
  metadata: Record<string, unknown>
  updated_at: string
  created_at: string
}

export type ContactRequestsListResponse = {
  ok: boolean
  items: ContactRequestRecord[]
  total: number
  limit: number
  offset: number
}

export type BugReportRecord = {
  id: number
  report_id: string
  installation_id: string
  workspace_id: string | null
  customer_ref: string | null
  source: string
  status: string
  severity: string
  title: string
  description: string
  steps_to_reproduce: string | null
  expected_behavior: string | null
  actual_behavior: string | null
  reporter_user_id: string | null
  reporter_username: string | null
  triage_note: string | null
  assignee: string | null
  dedup_key: string
  metadata: Record<string, unknown>
  updated_at: string
  created_at: string
}

export type BugReportsListResponse = {
  ok: boolean
  items: BugReportRecord[]
  total: number
  limit: number
  offset: number
}
