'use client'
import { useState, useEffect, useCallback, useRef } from 'react'
import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import { useApiClient } from '@/hooks/useApiClient'
import { usePolling } from '@/hooks/usePolling'
import { Badge, Spinner, ConfirmDialog } from '@/components/ui'
import { cn, statusLabel, campaignStatusColor, formatDateTime } from '@/lib/utils'
import { config } from '@/config'
import type { CampaignResponse, CampaignSummary, PipelineStatusResponse } from '@/types/api'
import { toast } from 'sonner'
import {
  ArrowLeft, Zap, Users, Mail, BarChart2,
  FileText, Target, Trash2, Play, AlertTriangle,
} from 'lucide-react'

// ── Tab definitions ──────────────────────────────────────────────────────────

type Tab = 'overview' | 'icp' | 'brief' | 'leads' | 'emails' | 'analytics'

const TABS: { id: Tab; label: string; icon: React.ElementType }[] = [
  { id: 'overview',  label: 'Overview',  icon: BarChart2  },
  { id: 'icp',       label: 'ICP',       icon: Target     },
  { id: 'brief',     label: 'Brief',     icon: FileText   },
  { id: 'leads',     label: 'Leads',     icon: Users      },
  { id: 'emails',    label: 'Emails',    icon: Mail       },
]

// ── Pipeline stages for the progress tracker ──────────────────────────────────
const PIPELINE_STAGES = [
  { key: 'onboarding', label: 'Onboarding' },
  { key: 'ingestion', label: 'Ingestion' },
  { key: 'enrichment', label: 'Enrichment' },
  { key: 'qualification', label: 'Qualification' },
  { key: 'emails', label: 'Emails' },
  { key: 'campaign_complete', label: 'Complete' },
]

function stageIndex(status: string): number {
  if (!status) return -1
  const s = status.toLowerCase()
  if (s === 'created' || s.startsWith('onboarding')) return 0
  if (s.includes('ingestion') || s === 'running' || s.startsWith('orchestration')) return 1
  if (s.includes('enrichment')) return 2
  if (s.includes('qualification')) return 3
  if (s.includes('email_generation') || s.includes('emails_')) return 4
  if (s === 'campaign_complete') return 5
  return -1
}

/** Campaign is still moving through onboarding or pipeline — keep GET /campaign fresh */
const ACTIVE_CAMPAIGN_STATUSES = new Set([
  'onboarding',
  'running',
  'orchestration_running',
  'orchestration_complete',
  'ingesting',
  'ingestion_running',
  'ingestion_complete',
  'enriching',
  'enrichment_running',
  'enrichment_complete',
  'qualifying',
  'qualification_running',
  'qualification_complete',
  'generating_emails',
  'email_generation_running',
])

/** Monotonic “progress” — a refetch must not overwrite newer UI state (poll often wins; HTTP can lag). */
const STATUS_PROGRESS: Record<string, number> = {
  created: 0,
  /** Backend uses `onboarding_running` — same tier as the legacy `onboarding` label */
  onboarding: 1,
  onboarding_running: 1,
  onboarding_complete: 2,
  // Granular *running* states (backend) — in-flight work
  orchestration_running: 3,
  orchestration_complete: 3,
  running: 3,
  ingesting: 3,
  ingestion_running: 3,
  ingestion_complete: 3,
  enriching: 3,
  enrichment_running: 3,
  enrichment_complete: 3,
  qualifying: 3,
  qualification_running: 3,
  qualification_complete: 3,
  generating_emails: 3,
  email_generation_running: 3,
  email_generation_complete: 3,
  campaign_complete: 4,
  failed: 4,
  onboarding_failed: 1,
  cancelled: 0,
}

const EMPTY_SUMMARY: CampaignSummary = {
  total_leads: 0,
  enriched: 0,
  approved: 0,
  review: 0,
  rejected: 0,
  emails_written: 0,
  converted: 0,
}

const FINAL_PIPELINE_STATUSES = new Set([
  'email_generation_complete',
  'campaign_complete',
  'failed',
  'onboarding_failed',
  'orchestration_failed',
  'ingestion_failed',
  'enrichment_failed',
  'qualification_failed',
  'email_generation_failed',
  'cancelled',
])

/** Campaign can be started / restarted from the dashboard */
function canRunPipeline(status: string): boolean {
  return status === 'onboarding_complete' || status === 'failed'
}

/**
 * Stale in-flight /poll responses are common; never make UI “go backward.”
 * Also handles unknown or future status strings.
 */
function isCampaignStateRegression(
  current: CampaignResponse,
  incoming: CampaignResponse
): boolean {
  const a = STATUS_PROGRESS[current.status] ?? 0
  const b = STATUS_PROGRESS[incoming.status] ?? 0
  if (a > b) return true
  if (a === b && new Date(incoming.updated_at) < new Date(current.updated_at)) {
    return true
  }
  return false
}

/** Polling is needed while the campaign is in any in-flight (non-terminal) stage */
function isCampaignInFlightState(status: string) {
  return !FINAL_PIPELINE_STATUSES.has(status) && (
    ACTIVE_CAMPAIGN_STATUSES.has(status) || status.endsWith('_running')
  )
}

// ── Sub-page lazy imports ─────────────────────────────────────────────────────
import ICPTab    from './ICPTab'
import BriefTab  from './BriefTab'
import LeadsTab  from './LeadsTab'
import EmailsTab from './EmailsTab'

export default function CampaignDetailPage() {
  const params           = useParams<{ campaignId: string }>()
  const router           = useRouter()
  const { getClient }    = useApiClient()
  const campaignId       = params.campaignId

  const [campaign, setCampaign]       = useState<CampaignResponse | null>(null)
  const [pipelineStatus, setPipeline] = useState<PipelineStatusResponse | null>(null)
  const [tab, setTab]                 = useState<Tab>('overview')
  const [loading, setLoading]         = useState(true)
  const [runLoading, setRunLoading]   = useState(false)
  const [awaitingRunTransition, setAwaitingRunTransition] = useState(false)
  const [deleteOpen, setDeleteOpen]   = useState(false)
  const [deleting, setDeleting]       = useState(false)

  // ── Initial load ─────────────────────────────────────────────────────────
  const loadCampaign = useCallback(async () => {
    try {
      const client = await getClient()
      const [camp, pipeline] = await Promise.all([
        client.getCampaign(campaignId),
        client.getPipelineStatus(campaignId).catch(() => null),
      ])
      setCampaign((prev) => {
        if (!prev) return camp
        if (isCampaignStateRegression(prev, camp)) return prev
        return camp
      })
      if (pipeline) {
        // getCampaign and getPipeline run in parallel; they can disagree briefly — campaign status wins.
        if (canRunPipeline(camp.status) && pipeline.is_running) {
          setPipeline({ ...pipeline, is_running: false, status: camp.status })
        } else {
          setPipeline(pipeline)
        }
      }
    } catch {
      toast.error('Failed to load campaign')
    } finally {
      setLoading(false)
    }
  }, [getClient, campaignId])

  useEffect(() => { loadCampaign() }, [loadCampaign])

  const pipelineRunningRef = useRef(false)
  // When campaign is ready to run, GET /pipeline/status is always is_running: false; stale
  // pipeline state must not keep campaign-poll alive forever.
  useEffect(() => {
    if (campaign && canRunPipeline(campaign.status)) {
      pipelineRunningRef.current = false
    } else {
      pipelineRunningRef.current = !!pipelineStatus?.is_running
    }
  }, [campaign?.status, pipelineStatus?.is_running])

  // ── Poll campaign while onboarding / pipeline stages advance ─────────────
  const shouldPollCampaign =
    !!campaign &&
    (isCampaignInFlightState(campaign.status) || !!pipelineStatus?.is_running || awaitingRunTransition)

  const campaignPoll = usePolling<CampaignResponse>({
    fetcher: async () => {
      const client = await getClient()
      return client.getCampaign(campaignId)
    },
    // While the pipeline worker runs, keep refreshing campaign — otherwise
    // onboarding_complete + is_running would stop the poll before status advances.
    shouldStop: (data) => {
      if (pipelineRunningRef.current) return false
      return !isCampaignInFlightState(data.status)
    },
    interval: config.polling.onboardingInterval,
    enabled: shouldPollCampaign,
    onError: () => {},
  })

  useEffect(() => {
    const incoming = campaignPoll.data
    if (!incoming) return
    setCampaign((prev) => {
      if (!prev) return incoming
      if (isCampaignStateRegression(prev, incoming)) return prev
      return incoming
    })
  }, [campaignPoll.data])

  const prevCampaignStatusRef = useRef<string | undefined>(undefined)

  /**
   * When onboarding flips to complete, refresh pipeline (Run button / is_running) only.
   * A full getCampaign() here can race the poll and briefly return still-onboarding, hiding the
   * Run Pipeline button until refresh — see STATUS_PROGRESS merge in loadCampaign.
   */
  useEffect(() => {
    const prev = prevCampaignStatusRef.current
    prevCampaignStatusRef.current = campaign?.status
    const wasOnboarding =
      prev === 'onboarding' || prev === 'onboarding_running'
    if (!wasOnboarding || campaign?.status !== 'onboarding_complete') return
    void (async () => {
      try {
        const client = await getClient()
        const pipeline = await client.getPipelineStatus(campaignId).catch(() => null)
        if (!pipeline) return
        if (pipeline.is_running) {
          setPipeline({ ...pipeline, is_running: false, status: 'onboarding_complete' })
        } else {
          setPipeline(pipeline)
        }
      } catch {
        /* best-effort */
      }
    })()
  }, [campaign?.status, getClient, campaignId])

  const campaignRef = useRef(campaign)
  useEffect(() => {
    campaignRef.current = campaign
  }, [campaign])

  // ── Poll pipeline status while campaign is active (or worker reports running)
  const shouldPollPipelineStatus =
    !!campaign &&
    (isCampaignInFlightState(campaign.status) || !!pipelineStatus?.is_running || awaitingRunTransition)

  const pipelinePoll = usePolling<PipelineStatusResponse>({
    fetcher: async () => {
      const client = await getClient()
      return client.getPipelineStatus(campaignId)
    },
    shouldStop: (data) => {
      const c = campaignRef.current
      const campaignInFlight = !!c && isCampaignInFlightState(c.status)
      return !campaignInFlight && !data.is_running
    },
    interval: config.polling.pipelineInterval,
    enabled: shouldPollPipelineStatus,
    onError: () => {},
  })

  useEffect(() => {
    if (!pipelinePoll.data) return
    const c = campaignRef.current
    let next = pipelinePoll.data
    if (c && canRunPipeline(c.status) && next.is_running) {
      next = { ...next, is_running: false, status: c.status }
    }
    setPipeline(next)
  }, [pipelinePoll.data])

  // ── Run pipeline ─────────────────────────────────────────────────────────
  const handleRun = async () => {
    if (!campaign) return
    setRunLoading(true)
    setAwaitingRunTransition(true)
    try {
      const client = await getClient()
      setPipeline((prev) => ({
        campaign_id: prev?.campaign_id ?? campaignId,
        status: 'running',
        current_stage: prev?.current_stage ?? 'ingesting',
        summary: prev?.summary ?? campaign.summary ?? EMPTY_SUMMARY,
        failure_reason: null,
        is_running: true,
        is_complete: false,
        is_failed: false,
      }))
      await client.runPipeline(campaignId, {
        provider: 'prospeo',
        fetch_all: false,
        enrich_mobile: false,
        target_lead_count: config.leads.defaultTargetCount,
      })
      toast.success('Pipeline started')
      await loadCampaign()
    } catch (err: unknown) {
      setAwaitingRunTransition(false)
      const status = (err as { status?: number }).status
      if (status === 402 || status === 403) {
        toast.error('Active subscription required', {
          action: {
            label: 'Subscribe',
            onClick: () => router.push('/billing'),
          },
        })
      } else {
        toast.error('Failed to start pipeline')
      }
    } finally {
      setRunLoading(false)
    }
  }

  useEffect(() => {
    if (!awaitingRunTransition) return
    if ((campaign && isCampaignInFlightState(campaign.status)) || pipelineStatus?.is_running) {
      setAwaitingRunTransition(false)
    }
  }, [awaitingRunTransition, campaign?.status, pipelineStatus?.is_running])

  // ── Delete ───────────────────────────────────────────────────────────────
  const handleDelete = async () => {
    setDeleting(true)
    try {
      const client = await getClient()
      await client.deleteCampaign(campaignId)
      toast.success('Campaign deleted')
      router.push('/campaigns')
    } catch {
      toast.error('Failed to delete campaign')
    } finally {
      setDeleting(false)
      setDeleteOpen(false)
    }
  }

  // ── Derived ──────────────────────────────────────────────────────────────
  /** Campaign status is the source of truth: ready/failed is never a running state on the server */
  const canRun = campaign && canRunPipeline(campaign.status)

  const campaignShowsBusy =
    !!campaign &&
    isCampaignInFlightState(campaign.status) &&
    !canRunPipeline(campaign.status)

  /** Stale getPipeline can still have is_running while the campaign is already in a terminal/ready state */
  const showWorkerSpinner =
    (!!pipelineStatus?.is_running || runLoading || awaitingRunTransition || campaignShowsBusy) &&
    !!campaign &&
    (!canRunPipeline(campaign.status) || awaitingRunTransition)

  const isCancelled = campaign?.status === 'cancelled'
  const currentStageIdx = stageIndex(campaign?.status || '')

  if (loading) {
    return (
      <div className="p-8 max-w-5xl mx-auto">
        <div className="skeleton h-8 w-48 mb-4" />
        <div className="skeleton h-4 w-72 mb-8" />
        <div className="card skeleton h-64" />
      </div>
    )
  }

  if (!campaign) return null

  return (
    <div className="p-8 max-w-5xl mx-auto animate-fade-in">
      {/* Back + header */}
      <Link
        href="/campaigns"
        className="inline-flex items-center gap-1.5 text-sm text-ink-muted hover:text-ink mb-5 transition-colors"
      >
        <ArrowLeft size={14} /> All Campaigns
      </Link>

      <div className="flex items-start justify-between mb-6">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <h1 className="text-2xl font-semibold text-ink tracking-tight">{campaign.name}</h1>
            <span className={cn('text-sm font-medium', campaignStatusColor(campaign.status))}>
              {statusLabel(campaign.status)}
            </span>
          </div>
          {campaign.website_url && (
            <a
              href={campaign.website_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-ink-muted hover:text-brand-600 transition-colors"
            >
              {campaign.website_url}
            </a>
          )}
        </div>

        <div className="flex items-center gap-2">
          {canRun && !isCancelled && (
            <button
              className="btn-primary"
              onClick={handleRun}
              disabled={runLoading}
            >
              {runLoading ? <Spinner size={14} /> : <Play size={14} fill="currentColor" />}
              Run Pipeline
            </button>
          )}
          {showWorkerSpinner && (
            <div className="flex items-center gap-2 px-4 py-2.5 rounded-xl bg-brand-50 text-brand-700 text-sm font-medium">
              <Spinner size={13} className="text-brand-500" />
              Running…
            </div>
          )}
          <button
            className="btn-ghost text-ink-ghost hover:text-red-500"
            onClick={() => setDeleteOpen(true)}
            title="Delete campaign"
          >
            <Trash2 size={15} />
          </button>
        </div>
      </div>

      {/* Failure reason */}
      {campaign.failure_reason && (
        <div className="mb-6 rounded-xl bg-red-50 border border-red-200 px-4 py-3 flex items-start gap-2.5">
          <AlertTriangle size={15} className="text-red-500 flex-shrink-0 mt-0.5" />
          <div>
            <p className="text-sm font-medium text-red-700">Pipeline failed</p>
            <p className="text-xs text-red-600 mt-0.5">{campaign.failure_reason}</p>
          </div>
        </div>
      )}

      {/* Onboarding in-progress notice */}
      {(campaign.status === 'onboarding' || campaign.status === 'onboarding_running') && (
        <div className="mb-6 rounded-xl bg-brand-50 border border-brand-200 px-4 py-3 flex items-center gap-2.5">
          <Spinner size={14} className="text-brand-500" />
          <p className="text-sm text-brand-700 font-medium">
            Onboarding agent is analyzing your website — ICP and product brief will appear shortly.
          </p>
        </div>
      )}

      {/* Pipeline progress bar */}
      {currentStageIdx >= 0 && (
        <div className="card px-6 py-4 mb-6">
          <div className="flex items-center justify-between mb-3">
            <p className="text-xs font-medium text-ink-muted uppercase tracking-wide">Pipeline Progress</p>
            {campaign.completed_at && (
              <p className="text-xs text-ink-subtle">Completed {formatDateTime(campaign.completed_at)}</p>
            )}
          </div>
          <div className="flex items-center gap-0">
            {PIPELINE_STAGES.map((stage, i) => {
              const done    = i < currentStageIdx
              const current = i === currentStageIdx
              const isLast  = i === PIPELINE_STAGES.length - 1
              return (
                <div key={stage.key} className="flex items-center flex-1">
                  <div className="flex flex-col items-center">
                    <div className={cn(
                      'w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-semibold flex-shrink-0 transition-colors',
                      done    ? 'bg-brand-600 text-white'
                      : current ? 'bg-brand-100 border-2 border-brand-500 text-brand-700'
                      : 'bg-surface-200 text-ink-ghost'
                    )}>
                      {done ? (
                        <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
                          <path d="M2 5L4 7L8 3" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                        </svg>
                      ) : i + 1}
                    </div>
                    <span className={cn(
                      'text-[10px] mt-1 whitespace-nowrap',
                      current ? 'text-brand-700 font-medium' : done ? 'text-ink-muted' : 'text-ink-ghost'
                    )}>
                      {stage.label}
                    </span>
                  </div>
                  {!isLast && (
                    <div className={cn(
                      'flex-1 h-0.5 mx-1 mb-4 rounded',
                      done ? 'bg-brand-500' : 'bg-surface-200'
                    )} />
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Summary cards */}
      {campaign.summary && (
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-7 gap-3 mb-6">
          {[
            { label: 'Total', value: campaign.summary.total_leads, color: 'text-ink' },
            { label: 'Enriched', value: campaign.summary.enriched, color: 'text-purple-600' },
            { label: 'Approved', value: campaign.summary.approved, color: 'text-status-approved' },
            { label: 'Review', value: campaign.summary.review, color: 'text-status-review' },
            { label: 'Rejected', value: campaign.summary.rejected, color: 'text-status-rejected' },
            { label: 'Emails', value: campaign.summary.emails_written, color: 'text-brand-600' },
            {
              label: 'Converted',
              value: campaign.summary.converted ?? 0,
              color: 'text-emerald-600',
            },
          ].map(({ label, value, color }) => (
            <div key={label} className="card p-4 text-center">
              <p className="text-xs text-ink-subtle mb-1">{label}</p>
              <p className={cn('text-xl font-semibold', color)}>{value}</p>
            </div>
          ))}
        </div>
      )}

      {/* Tabs */}
      <div className="flex items-center gap-1 mb-6 border-b border-surface-200 pb-1">
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={cn('tab flex items-center gap-2', tab === id && 'tab-active')}
          >
            <Icon size={14} />
            {label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="animate-fade-in" key={tab}>
        {tab === 'overview'  && <OverviewTab campaign={campaign} pipeline={pipelineStatus} />}
        {tab === 'icp'       && <ICPTab    campaignId={campaignId} />}
        {tab === 'brief'     && <BriefTab  campaignId={campaignId} />}
        {tab === 'leads'     && (
          <LeadsTab campaignId={campaignId} onCampaignMutated={loadCampaign} />
        )}
        {tab === 'emails'    && <EmailsTab campaignId={campaignId} />}
      </div>

      <ConfirmDialog
        open={deleteOpen}
        title="Delete campaign?"
        description="This will cancel and delete the campaign. Leads and emails are preserved for audit."
        confirmLabel="Delete"
        danger
        onConfirm={handleDelete}
        onCancel={() => setDeleteOpen(false)}
        loading={deleting}
      />
    </div>
  )
}

// ── Overview tab ─────────────────────────────────────────────────────────────
function OverviewTab({
  campaign, pipeline
}: {
  campaign: CampaignResponse
  pipeline: PipelineStatusResponse | null
}) {
  return (
    <div className="space-y-4">
      <div className="card p-6">
        <h3 className="text-sm font-semibold text-ink mb-4">Campaign Details</h3>
        <dl className="grid grid-cols-2 gap-x-8 gap-y-4 text-sm">
          {[
            ['Campaign ID',     campaign.id],
            ['Status',          statusLabel(campaign.status)],
            ['Website',         campaign.website_url || '—'],
            ['Company',         campaign.company_name || '—'],
            ['Pipeline Version',campaign.pipeline_version],
            ['Created',         formatDateTime(campaign.created_at)],
            ['Last Updated',    formatDateTime(campaign.updated_at)],
            ['Completed',       campaign.completed_at ? formatDateTime(campaign.completed_at) : '—'],
          ].map(([k, v]) => (
            <div key={k}>
              <dt className="text-xs text-ink-subtle mb-0.5">{k}</dt>
              <dd className="text-ink font-medium truncate">{v}</dd>
            </div>
          ))}
        </dl>
      </div>

      {pipeline && (
        <div className="card p-6">
          <h3 className="text-sm font-semibold text-ink mb-4">Pipeline Status</h3>
          <dl className="grid grid-cols-2 gap-x-8 gap-y-4 text-sm">
            {[
              ['Current Stage', pipeline.current_stage ? statusLabel(pipeline.current_stage) : '—'],
              ['Is Running',    pipeline.is_running ? 'Yes' : 'No'],
              ['Is Complete',   pipeline.is_complete ? 'Yes' : 'No'],
              ['Failed',        pipeline.is_failed ? 'Yes' : 'No'],
            ].map(([k, v]) => (
              <div key={k}>
                <dt className="text-xs text-ink-subtle mb-0.5">{k}</dt>
                <dd className="text-ink font-medium">{v}</dd>
              </div>
            ))}
          </dl>
          {pipeline.failure_reason && (
            <div className="mt-4 p-3 bg-red-50 rounded-xl text-xs text-red-600">
              {pipeline.failure_reason}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
