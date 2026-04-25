// ─── SDA Platform — API Types ──────────────────────────────────────────────────
// Generated from OpenAPI schema. Keep in sync with backend/api/schemas/

// ── Enums ──────────────────────────────────────────────────────────────────────

export type Provider = 'prospeo' | 'apollo'

export type TargetType = 'business' | 'individual' | 'both'

export type Seniority =
  | 'owner' | 'founder' | 'c_suite' | 'partner' | 'vp'
  | 'head' | 'director' | 'manager' | 'senior' | 'entry' | 'intern'

export type LeadStatus =
  | 'ingested' | 'queried' | 'enriched' | 'qualified'
  | 'review' | 'disqualified' | 'email_written'

/** Campaign leads tab filters — includes semantic filters that are not raw `leads.status`. */
export type LeadPipelineFilter = LeadStatus | 'converted'

export type CampaignStatus =
  | 'created'
  | 'onboarding'
  | 'onboarding_complete'
  | 'onboarding_failed'
  | 'running'
  | 'ingesting'
  | 'enriching'
  | 'qualifying'
  | 'generating_emails'
  | 'campaign_complete'
  | 'failed'
  | 'cancelled'

// ── Requests ──────────────────────────────────────────────────────────────────

export interface CreateCampaignRequest {
  name: string
  website_url: string
  company_name?: string | null
  provider?: Provider | null
  fetch_all?: boolean | null
  enrich_mobile?: boolean | null
  target_lead_count?: number | null
}

export interface RunPipelineRequest {
  provider?: Provider | null
  fetch_all?: boolean | null
  enrich_mobile?: boolean | null
  target_lead_count?: number | null
}

export interface UpdateICPRequest {
  target_type?: TargetType | null
  industry?: string[] | null
  company_size_min?: number | null
  company_size_max?: number | null
  funding_status?: string[] | null
  job_titles?: string[] | null
  seniority?: Seniority[] | null
  locations?: string[] | null
  tech_stack?: string[] | null
  demographics?: string | null
}

export interface UpdateBriefRequest {
  product_name?: string | null
  what_it_does?: string | null
  who_it_is_for?: string | null
  pain_it_solves?: string | null
  key_differentiators?: string[] | null
  ideal_customer_description?: string | null
}

export interface UpdateEmailRequest {
  email_1_subject?: string | null
  email_1_body?: string | null
  email_2_subject?: string | null
  email_2_body?: string | null
  email_3_subject?: string | null
  email_3_body?: string | null
}

// ── Responses ─────────────────────────────────────────────────────────────────

export interface UserResponse {
  id: string
  email: string
  full_name: string | null
  plan: string
  has_active_subscription: boolean
  created_at: string
}

export interface CampaignSummary {
  total_leads: number
  enriched: number
  approved: number
  review: number
  rejected: number
  emails_written: number
  converted: number
}

export interface CampaignResponse {
  id: string
  user_id: string
  name: string
  status: string
  website_url: string | null
  company_name: string | null
  pipeline_version: string
  summary: CampaignSummary | null
  created_at: string
  updated_at: string
  completed_at: string | null
  failure_reason: string | null
}

export interface CampaignListResponse {
  campaigns: CampaignResponse[]
  total: number
}

export interface ICPResponse {
  id: string
  campaign_id: string
  target_type: string
  industry: string[]
  company_size_min: number | null
  company_size_max: number | null
  funding_status: string[] | null
  job_titles: string[]
  seniority: string[] | null
  locations: string[]
  tech_stack: string[] | null
  demographics: string | null
  confidence_score: number | null
  missing_fields: string[] | null
  created_at: string
  updated_at: string
}

export interface BriefResponse {
  id: string
  campaign_id: string
  product_name: string
  what_it_does: string
  who_it_is_for: string
  pain_it_solves: string
  key_differentiators: string[]
  ideal_customer_description: string
  created_at: string
  updated_at: string
}

export interface PipelineStatusResponse {
  campaign_id: string
  status: string
  current_stage: string | null
  summary: CampaignSummary
  failure_reason: string | null
  is_running: boolean
  is_complete: boolean
  is_failed: boolean
}

export interface PipelineRunResponse {
  campaign_id: string
  message: string
  status: string
}

export interface EnrichmentSummary {
  identity_status: string | null
  confidence_score: number | null
  current_title: string | null
  company_signals: Record<string, string>[] | null
  notable_achievements: string[] | null
  discrepancies: Record<string, unknown>[] | null
  enrichment_summary: string | null
}

export interface QualificationSummary {
  decision: string | null
  icp_match_score: number | null
  decision_reason: string | null
  blocking_issues: string[] | null
  review_flags: string[] | null
  recommended_angle: string | null
}

export interface LeadResponse {
  id: string
  campaign_id: string
  status: string
  name: string | null
  first_name: string | null
  last_name: string | null
  title: string | null
  seniority: string | null
  email: string | null
  email_status: string | null
  phone: string | null
  company: string | null
  company_size: number | null
  industry: string | null
  location: string | null
  country: string | null
  linkedin: string | null
  provider: string | null
  lead_type: string | null
  enrichment: EnrichmentSummary | null
  qualification: QualificationSummary | null
  created_at: string
  updated_at: string
}

export interface LeadListResponse {
  leads: LeadResponse[]
  total: number
  campaign_id: string
}

export interface EmailDetail {
  subject: string | null
  body: string | null
}

export interface EmailSequenceResponse {
  id: string
  lead_id: string
  campaign_id: string
  lead_name: string | null
  lead_email: string
  email_1: EmailDetail
  email_2: EmailDetail
  email_3: EmailDetail
  sequence_notes: string | null
  email_1_sent_at: string | null
  email_2_sent_at: string | null
  email_3_sent_at: string | null
  created_at: string
  updated_at: string
}

export interface EmailListResponse {
  sequences: EmailSequenceResponse[]
  total: number
  campaign_id: string
}

export interface AnalyticsSummaryResponse {
  campaign_id: string
  campaign_name: string
  campaign_status: string
  total_leads: number
  enriched: number
  approved: number
  review: number
  rejected: number
  emails_written: number
  converted: number
  approval_rate: number | null
  enrichment_rate: number | null
}

export interface MessageResponse {
  message: string
}

// ── Outreach (user) ───────────────────────────────────────────────────────────

export interface OutreachSettingsRequest {
  resend_api_key: string
  sending_domain: string
  sending_email: string
  sending_name: string
  cal_link?: string | null
}

export interface OutreachSettingsResponse {
  user_id: string
  sending_domain: string | null
  sending_email: string | null
  sending_name: string | null
  cal_link: string | null
  is_configured: boolean
  has_api_key: boolean
}

export interface SendOutreachEmailRequest {
  email_number?: number
}

export interface SendOutreachEmailResponse {
  success: boolean
  outreach_log_id: string
  resend_message_id: string | null
  followups_scheduled: number
  error: string | null
}

// ── RAG (user knowledge base) ─────────────────────────────────────────────────

export type RagSourceType = 'faq' | 'company_info' | 'email_template' | 'other'

export interface RagDocumentUploadRequest {
  title: string
  source_type: RagSourceType
  content: string
}

export interface RagDocumentResponse {
  document_id: string
  title: string
  source_type: string
  chunk_count: number
}

export interface RagDocumentListItem {
  id: string
  title: string
  source_type: string
  chunk_count: number
  file_size_bytes: number | null
  embedded_at: string | null
  created_at: string
}

export interface RagDocumentListResponse {
  documents: RagDocumentListItem[]
  total: number
}

export interface RagDeleteResponse {
  message: string
  document_id: string
}

// ── API Error ─────────────────────────────────────────────────────────────────

export interface ApiError {
  status: number
  message: string
  detail?: unknown
}
