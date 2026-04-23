'use client'
import { useState, useEffect, useCallback } from 'react'
import Link from 'next/link'
import { useApiClient } from '@/hooks/useApiClient'
import { Empty, ConfirmDialog, Spinner } from '@/components/ui'
import { formatDate, statusLabel, campaignStatusColor, cn } from '@/lib/utils'
import type { CampaignResponse } from '@/types/api'
import { toast } from 'sonner'
import {
  Plus, Megaphone, Trash2, ArrowRight,
  Users, CheckCircle, Mail, RefreshCw,
} from 'lucide-react'

export default function CampaignsPage() {
  const { getClient } = useApiClient()

  const [campaigns, setCampaigns] = useState<CampaignResponse[]>([])
  const [loading, setLoading]     = useState(true)
  const [deleteId, setDeleteId]   = useState<string | null>(null)
  const [deleting, setDeleting]   = useState(false)

  const load = useCallback(async () => {
    try {
      const client = await getClient()
      const res = await client.listCampaigns()
      setCampaigns(res.campaigns.sort(
        (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
      ))
    } catch {
      toast.error('Failed to load campaigns')
    } finally {
      setLoading(false)
    }
  }, [getClient])

  useEffect(() => { load() }, [load])

  const handleDelete = async () => {
    if (!deleteId) return
    setDeleting(true)
    try {
      const client = await getClient()
      await client.deleteCampaign(deleteId)
      setCampaigns((prev) => prev.filter((c) => c.id !== deleteId))
      toast.success('Campaign deleted')
    } catch {
      toast.error('Failed to delete campaign')
    } finally {
      setDeleting(false)
      setDeleteId(null)
    }
  }

  const statusDot = (status: string) => {
    const isRunning = ['running','onboarding','ingesting','enriching','qualifying','generating_emails'].includes(status)
    const isComplete = status === 'campaign_complete'
    const isFailed   = ['failed','onboarding_failed'].includes(status)
    if (isRunning)  return <span className="stage-dot bg-brand-500 animate-pulse-soft" />
    if (isComplete) return <span className="stage-dot bg-green-500" />
    if (isFailed)   return <span className="stage-dot bg-red-500" />
    return <span className="stage-dot bg-surface-300" />
  }

  return (
    <div className="p-8 max-w-5xl mx-auto animate-fade-in">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-semibold text-ink tracking-tight">Campaigns</h1>
          <p className="text-sm text-ink-muted mt-1">
            {loading ? '' : `${campaigns.length} campaign${campaigns.length !== 1 ? 's' : ''}`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={load}
            className="btn-ghost"
            title="Refresh"
          >
            <RefreshCw size={15} />
          </button>
          <Link href="/campaigns/new" className="btn-primary">
            <Plus size={15} /> New Campaign
          </Link>
        </div>
      </div>

      {/* List */}
      {loading ? (
        <div className="space-y-3">
          {[1,2,3,4].map(i => <div key={i} className="skeleton h-20" />)}
        </div>
      ) : campaigns.length === 0 ? (
        <div className="card">
          <Empty
            icon={<Megaphone size={22} />}
            title="No campaigns yet"
            description="Create your first campaign to start generating and qualifying leads automatically."
            action={
              <Link href="/campaigns/new" className="btn-primary btn-sm">
                <Plus size={13} /> New Campaign
              </Link>
            }
          />
        </div>
      ) : (
        <div className="card divide-y divide-surface-100">
          {campaigns.map((c) => (
            <div key={c.id} className="flex items-center gap-4 px-6 py-4 hover:bg-surface-50 transition-colors group">
              <div className="flex-1 min-w-0">
                <Link href={`/campaigns/${c.id}`} className="block">
                  <div className="flex items-center gap-2 mb-0.5">
                    {statusDot(c.status)}
                    <p className="text-sm font-medium text-ink group-hover:text-brand-700 transition-colors truncate">
                      {c.name}
                    </p>
                  </div>
                  <div className="flex items-center gap-2 pl-4">
                    <span className={cn('text-xs font-medium', campaignStatusColor(c.status))}>
                      {statusLabel(c.status)}
                    </span>
                    {c.website_url && (
                      <>
                        <span className="text-ink-ghost text-xs">·</span>
                        <span className="text-xs text-ink-subtle truncate max-w-[200px]">{c.website_url}</span>
                      </>
                    )}
                    <span className="text-ink-ghost text-xs">·</span>
                    <span className="text-xs text-ink-subtle">{formatDate(c.updated_at)}</span>
                  </div>
                </Link>
              </div>

              {/* Summary chips */}
              {c.summary && (
                <div className="hidden md:flex items-center gap-4 text-xs text-ink-muted flex-shrink-0">
                  <span className="flex items-center gap-1" title="Total leads">
                    <Users size={12} /> {c.summary.total_leads}
                  </span>
                  <span className="flex items-center gap-1 text-status-approved" title="Approved">
                    <CheckCircle size={12} /> {c.summary.approved}
                  </span>
                  <span className="flex items-center gap-1 text-brand-600" title="Emails written">
                    <Mail size={12} /> {c.summary.emails_written}
                  </span>
                </div>
              )}

              {/* Actions */}
              <div className="flex items-center gap-1 flex-shrink-0">
                <button
                  onClick={(e) => { e.preventDefault(); setDeleteId(c.id) }}
                  className="btn-ghost btn-sm text-ink-ghost hover:text-red-500 opacity-0 group-hover:opacity-100 transition-all"
                  title="Delete campaign"
                >
                  <Trash2 size={14} />
                </button>
                <Link href={`/campaigns/${c.id}`} className="btn-ghost btn-sm">
                  <ArrowRight size={14} />
                </Link>
              </div>
            </div>
          ))}
        </div>
      )}

      <ConfirmDialog
        open={!!deleteId}
        title="Delete campaign?"
        description="This will cancel and delete the campaign. Leads and emails are preserved for audit purposes."
        confirmLabel="Delete"
        danger
        onConfirm={handleDelete}
        onCancel={() => setDeleteId(null)}
        loading={deleting}
      />
    </div>
  )
}
