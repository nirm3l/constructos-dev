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
