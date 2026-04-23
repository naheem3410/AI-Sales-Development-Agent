'use client'
import { useState, useEffect, useCallback, useRef } from 'react'
import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import { useApiClient } from '@/hooks/useApiClient'
import { usePolling } from '@/hooks/usePolling'
import { Badge, Spinner, ConfirmDialog } from '@/components/ui'
import { cn, statusLabel, campaignStatusColor, formatDateTime } from '@/lib/utils'
import { config } from '@/config'
import type { CampaignResponse, PipelineStatusResponse } from '@/types/api'
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
  { key: 'onboarding',        label: 'Onboarding'    },
  { key: 'ingesting',         label: 'Ingestion'     },
  { key: 'enriching',         label: 'Enrichment'    },
  { key: 'qualifying',        label: 'Qualification' },
  { key: 'generating_emails', label: 'Emails'        },
  { key: 'campaign_complete', label: 'Complete'      },
]

function stageIndex(status: string): number {
  return PIPELINE_STAGES.findIndex((s) => s.key === status)
}

/** Campaign is still moving through onboarding or pipeline — keep GET /campaign fresh */
const ACTIVE_CAMPAIGN_STATUSES = new Set([
  'onboarding',
  'running',
  'ingesting',
  'enriching',
  'qualifying',
  'generating_emails',
])

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
      setCampaign(camp)
      if (pipeline) setPipeline(pipeline)
    } catch {
      toast.error('Failed to load campaign')
    } finally {
      setLoading(false)
    }
  }, [getClient, campaignId])

  useEffect(() => { loadCampaign() }, [loadCampaign])

  const pipelineRunningRef = useRef(false)
  useEffect(() => {
    pipelineRunningRef.current = !!pipelineStatus?.is_running
  }, [pipelineStatus?.is_running])

  // ── Poll campaign while onboarding / pipeline stages advance ─────────────
  const shouldPollCampaign =
    !!campaign &&
    (ACTIVE_CAMPAIGN_STATUSES.has(campaign.status) || !!pipelineStatus?.is_running)

  const campaignPoll = usePolling<CampaignResponse>({
    fetcher: async () => {
      const client = await getClient()
      return client.getCampaign(campaignId)
    },
    // While the pipeline worker runs, keep refreshing campaign — otherwise
    // onboarding_complete + is_running would stop the poll before status advances.
    shouldStop: (data) => {
      if (pipelineRunningRef.current) return false
      return !ACTIVE_CAMPAIGN_STATUSES.has(data.status)
    },
    interval: config.polling.onboardingInterval,
    enabled: shouldPollCampaign,
    onError: () => {},
  })

  useEffect(() => {
    if (campaignPoll.data) setCampaign(campaignPoll.data)
  }, [campaignPoll.data])

  const prevCampaignStatusRef = useRef<string | undefined>(undefined)

  /** When onboarding finishes, refetch campaign + pipeline so summary and Run Pipeline visibility match server state. */
  useEffect(() => {
    const prev = prevCampaignStatusRef.current
    prevCampaignStatusRef.current = campaign?.status
    if (prev !== 'onboarding' || campaign?.status !== 'onboarding_complete') return
    void loadCampaign()
  }, [campaign?.status, loadCampaign])

  // ── Poll pipeline status while worker reports running ─────────────────────
  const isRunning = pipelineStatus?.is_running || false

  const pipelinePoll = usePolling<PipelineStatusResponse>({
    fetcher: async () => {
      const client = await getClient()
      return client.getPipelineStatus(campaignId)
    },
    shouldStop: (data) => !data.is_running,
    interval: config.polling.pipelineInterval,
    enabled: isRunning,
    onError: () => {},
  })

  useEffect(() => {
    if (pipelinePoll.data) setPipeline(pipelinePoll.data)
  }, [pipelinePoll.data])

  // ── Run pipeline ─────────────────────────────────────────────────────────
  const handleRun = async () => {
    if (!campaign) return
    setRunLoading(true)
    try {
      const client = await getClient()
      await client.runPipeline(campaignId, {
        provider: 'prospeo',
        fetch_all: false,
        enrich_mobile: false,
        target_lead_count: config.leads.defaultTargetCount,
      })
      toast.success('Pipeline started')
      await loadCampaign()
    } catch (err: unknown) {
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
  const canRun = campaign &&
    ['onboarding_complete', 'failed'].includes(campaign.status) &&
    !pipelineStatus?.is_running

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
          {isRunning && (
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
      {campaign.status === 'onboarding' && (
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
