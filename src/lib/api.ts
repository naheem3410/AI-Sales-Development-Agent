// ─── SDA Platform — API Client ────────────────────────────────────────────────
import { config } from '@/config'
import type {
  UserResponse,
  CampaignResponse,
  CampaignListResponse,
  CreateCampaignRequest,
  ICPResponse,
  UpdateICPRequest,
  BriefResponse,
  UpdateBriefRequest,
  PipelineStatusResponse,
  PipelineRunResponse,
  RunPipelineRequest,
  LeadListResponse,
  LeadResponse,
  EmailListResponse,
  EmailSequenceResponse,
  UpdateEmailRequest,
  AnalyticsSummaryResponse,
  MessageResponse,
  LeadPipelineFilter,
  OutreachSettingsRequest,
  OutreachSettingsResponse,
  SendOutreachEmailRequest,
  SendOutreachEmailResponse,
  RagDocumentUploadRequest,
  RagDocumentResponse,
  RagDocumentListResponse,
  RagDeleteResponse,
} from '@/types/api'

/** Same shape as `useAuth().getToken` — one retry uses `{ skipCache: true }` after a 401. */
export type ApiTokenGetter = (options?: { skipCache?: boolean }) => Promise<string | null>

function isInvalidOrExpiredTokenDetail(detail: unknown): boolean {
  if (!detail || typeof detail !== 'object' || !('detail' in detail)) return false
  return (detail as { detail: string }).detail === 'Invalid or expired token.'
}

// ── Core fetch wrapper ────────────────────────────────────────────────────────

async function apiFetch<T>(
  path: string,
  getToken: ApiTokenGetter,
  options: RequestInit = {},
  retried = false
): Promise<T> {
  const token = await getToken(retried ? { skipCache: true } : undefined)
  if (!token) throw new Error('Not authenticated')
  const url = `${config.api.baseUrl}${path}`

  const res = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
      ...options.headers,
    },
  })

  if (!res.ok) {
    let detail: unknown
    try {
      detail = await res.json()
    } catch {
      detail = null
    }
    if (res.status === 401 && !retried && isInvalidOrExpiredTokenDetail(detail)) {
      return apiFetch<T>(path, getToken, options, true)
    }
    const err = new Error(`API error ${res.status}: ${res.statusText}`) as Error & {
      status: number
      detail: unknown
    }
    err.status = res.status
    err.detail = detail
    throw err
  }

  // 204 No Content
  if (res.status === 204) return undefined as T

  return res.json() as Promise<T>
}

/** Multipart upload — do not set Content-Type (browser sets boundary). */
async function apiFetchFormData<T>(
  path: string,
  getToken: ApiTokenGetter,
  form: FormData,
  retried = false
): Promise<T> {
  const token = await getToken(retried ? { skipCache: true } : undefined)
  if (!token) throw new Error('Not authenticated')
  const url = `${config.api.baseUrl}${path}`

  const res = await fetch(url, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
    },
    body: form,
  })

  if (!res.ok) {
    let detail: unknown
    try {
      detail = await res.json()
    } catch {
      detail = null
    }
    if (res.status === 401 && !retried && isInvalidOrExpiredTokenDetail(detail)) {
      return apiFetchFormData<T>(path, getToken, form, true)
    }
    const err = new Error(`API error ${res.status}: ${res.statusText}`) as Error & {
      status: number
      detail: unknown
    }
    err.status = res.status
    err.detail = detail
    throw err
  }

  return res.json() as Promise<T>
}

// ── API factory — pass `useAuth().getToken` so 401s can refresh the JWT and retry once ─

export function createApiClient(getToken: ApiTokenGetter) {
  const get = <T>(path: string) => apiFetch<T>(path, getToken)
  const post = <T>(path: string, body?: unknown) =>
    apiFetch<T>(path, getToken, { method: 'POST', body: body ? JSON.stringify(body) : undefined })
  const put = <T>(path: string, body?: unknown) =>
    apiFetch<T>(path, getToken, { method: 'PUT', body: body ? JSON.stringify(body) : undefined })
  const patch = <T>(path: string, body?: unknown) =>
    apiFetch<T>(path, getToken, { method: 'PATCH', body: body ? JSON.stringify(body) : undefined })
  const del = <T>(path: string) => apiFetch<T>(path, getToken, { method: 'DELETE' })
  const postForm = <T>(path: string, form: FormData) => apiFetchFormData<T>(path, getToken, form)

  return {
    // ── Users ──────────────────────────────────────────────────────────────
    getMe: () =>
      get<UserResponse>('/users/me'),

    // ── Campaigns ──────────────────────────────────────────────────────────
    listCampaigns: () =>
      get<CampaignListResponse>('/campaigns'),

    getCampaign: (id: string) =>
      get<CampaignResponse>(`/campaigns/${id}`),

    createCampaign: (body: CreateCampaignRequest) =>
      post<CampaignResponse>('/campaigns', body),

    deleteCampaign: (id: string) =>
      del<MessageResponse>(`/campaigns/${id}`),

    // ── ICP ────────────────────────────────────────────────────────────────
    getICP: (campaignId: string) =>
      get<ICPResponse>(`/campaigns/${campaignId}/icp`),

    updateICP: (campaignId: string, body: UpdateICPRequest) =>
      put<ICPResponse>(`/campaigns/${campaignId}/icp`, body),

    // ── Brief ──────────────────────────────────────────────────────────────
    getBrief: (campaignId: string) =>
      get<BriefResponse>(`/campaigns/${campaignId}/brief`),

    updateBrief: (campaignId: string, body: UpdateBriefRequest) =>
      put<BriefResponse>(`/campaigns/${campaignId}/brief`, body),

    // ── Pipeline ───────────────────────────────────────────────────────────
    runPipeline: (campaignId: string, body: RunPipelineRequest) =>
      post<PipelineRunResponse>(`/campaigns/${campaignId}/pipeline/run`, body),

    getPipelineStatus: (campaignId: string) =>
      get<PipelineStatusResponse>(`/campaigns/${campaignId}/pipeline/status`),

    // ── Leads ──────────────────────────────────────────────────────────────
    listLeads: (campaignId: string, status?: LeadPipelineFilter) =>
      get<LeadListResponse>(
        `/campaigns/${campaignId}/leads${status ? `?status=${encodeURIComponent(status)}` : ''}`
      ),

    getLead: (campaignId: string, leadId: string) =>
      get<LeadResponse>(`/campaigns/${campaignId}/leads/${leadId}`),

    resolveLeadReview: (
      campaignId: string,
      leadId: string,
      resolution: 'approve' | 'reject'
    ) =>
      patch<LeadResponse>(
        `/campaigns/${campaignId}/leads/${leadId}/review-resolution`,
        { resolution }
      ),

    // ── Emails ─────────────────────────────────────────────────────────────
    listEmails: (campaignId: string) =>
      get<EmailListResponse>(`/campaigns/${campaignId}/emails`),

    getEmailSequence: (campaignId: string, leadId: string) =>
      get<EmailSequenceResponse>(`/campaigns/${campaignId}/emails/${leadId}`),

    updateEmailSequence: (campaignId: string, leadId: string, body: UpdateEmailRequest) =>
      put<EmailSequenceResponse>(`/campaigns/${campaignId}/emails/${leadId}`, body),

    // ── Analytics ──────────────────────────────────────────────────────────
    getCampaignSummary: (campaignId: string) =>
      get<AnalyticsSummaryResponse>(`/campaigns/${campaignId}/summary`),

    // ── Outreach (user — Resend / sending identity) ────────────────────────
    getOutreachSettings: () =>
      get<OutreachSettingsResponse>('/users/me/outreach-settings'),

    updateOutreachSettings: (body: OutreachSettingsRequest) =>
      put<OutreachSettingsResponse>('/users/me/outreach-settings', body),

    sendOutreachEmail: (
      campaignId: string,
      leadId: string,
      body: SendOutreachEmailRequest = {}
    ) =>
      post<SendOutreachEmailResponse>(
        `/outreach/${campaignId}/leads/${leadId}/send`,
        body
      ),

    // ── RAG (user knowledge — no admin/query debug endpoint) ────────────────
    listRagDocuments: () =>
      get<RagDocumentListResponse>('/rag/documents'),

    uploadRagDocument: (body: RagDocumentUploadRequest) =>
      post<RagDocumentResponse>('/rag/documents', body),

    uploadRagDocumentFile: (form: FormData) =>
      postForm<RagDocumentResponse>('/rag/documents/file', form),

    deleteRagDocument: (documentId: string) =>
      del<RagDeleteResponse>(`/rag/documents/${documentId}`),
  }
}

export type ApiClient = ReturnType<typeof createApiClient>
